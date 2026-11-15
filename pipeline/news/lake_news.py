"""
HimalWatch — News and coverage for named lakes

For every lake that has a real name, search Google News (RSS, no key) for
coverage, keep the items that are actually about the lake, and merge them into
news/lakes.json in R2: {lake_id: [{title, url, source, date}, ...]}, newest
first, de-duplicated. The file only ever grows, so a search that fails or is
rate-limited one week loses nothing.

pipeline/utils/lake_links.json holds hand-picked links per lake_id (for lakes
with no searchable name, e.g. a new reservoir) and is merged in the same way.

Unnamed lakes are skipped: there is nothing to search for.

AI review (optional, needs GEMINI_API_KEY or ANTHROPIC_API_KEY): keyword rules cannot tell the
Panch Pokhari in Sindhupalchok from the one in Sikkim, or spot the same wire
story under five headlines. When a key is set, Claude reads each lake's new
candidates next to the lake's location and decides which are really about that
lake and which repeat a story already kept. Every candidate is judged once:
rejected titles are remembered under "_rejected" so later runs skip them.
Without a key the keyword rules alone decide.

Providers: Google Gemini (GEMINI_API_KEY; has a free tier — on it Google may
use the content to improve its products, which is fine for public headlines)
or Claude (ANTHROPIC_API_KEY). If both keys are set Gemini is used unless
NEWS_PROVIDER=anthropic. NEWS_MODEL overrides the model.

Usage:
    python pipeline/news/lake_news.py                       # R2 in, R2 out
    python pipeline/news/lake_news.py --inventory inv.parquet --out news.json --limit 5
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

import pandas as pd
import requests

NEWS_KEY   = "news/lakes.json"
CURATED    = Path(__file__).parent.parent / "utils" / "lake_links.json"
RSS        = "https://news.google.com/rss/search"
PAUSE_S    = 1.5
AI_PAUSE_S = 6.0         # between AI calls: stays under free-tier requests-per-minute limits
MAX_ITEMS  = 40          # kept per lake
BUDGET_S   = 14 * 60         # stop collecting after this long and save what there is
AI_TIMEOUT_S = 90            # one AI call; a stuck call must not eat the whole budget
AI_MAX_FAILS = 3             # consecutive failed AI calls before falling back to keyword rules
REVIEWED   = "_ai_reviewed"  # store key: [lake_id whose stored items went through the AI review]
REJECTED   = "_rejected"  # store key: {lake_id: [normalised titles judged not relevant]}
AI_DEFAULT_MODEL = {"gemini": "gemini-3.8-flash", "anthropic": "claude-opus-5-5"}
AI_SCHEMA  = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "index":        {"type": "integer"},
            "about_lake":   {"type": "boolean"},
            "duplicate_of": {"type": "integer"},   # -1 = not a duplicate
        },
        "required": ["index", "about_lake", "duplicate_of"],
        "additionalProperties": False,
    }}},
    "required": ["items"],
    "additionalProperties": False,
}
# Words that say what a thing is, not which one — dropped to get the core name.
KIND_WORDS = {"lake", "lakes", "tsho", "tso", "cho", "co", "cuo", "tal", "taal",
              "pokhari", "kunda", "kund", "daha", "glacial", "glacier", "lower",
              "upper", "pond", "pool", "site", "the"}
# A title that has only the core name must also mention one of these.
CONTEXT    = re.compile(r"lake|tsho|tso\b|pokhari|\btal\b|kunda|glaci|glof|flood|"
                        r"himalaya|moraine|outburst|reservoir|dam\b", re.I)
MIN_CORE   = 5           # shorter core names ("Tara", "Kal") match too much
# Every search is tied to the region, otherwise "Lang Co" is a Vietnamese
# resort, "Ice Lake" an Intel chip and "Moon Lake" a park in Georgia.
REGION     = "(Nepal OR Tibet OR Himalaya OR Himalayan OR Sikkim OR glacial)"
# Not coverage: videos, weather pages, share prices, obituaries, property ads.
SKIP_SOURCE = re.compile(r"youtube|accuweather|legacy|livabl|tiktok|facebook|instagram", re.I)
SKIP_TITLE  = re.compile(r"\bIPO\b|\bshares\b|share price|markets$|weather forecast|obituary|"
                         r"co-(star|actor|founder|anchor|op)|hydro electric|hydropower l|"
                         r"vietnam|ayodhya|antarctic|pennsylvania|chandra taal", re.I)


def variants(name: str) -> list:
    """'Thulagi Lake (Dona Tal)' -> ['Thulagi Lake', 'Dona Tal']."""
    parts = [name] if "(" not in name else re.split(r"[()]", name)
    # a part that is only a kind of thing ("Kunda", "Lake") is not a name
    return [p.strip() for p in parts if p.strip() and core(p.strip())]


def core(variant: str) -> str:
    words = [w for w in re.split(r"\s+", variant) if w.lower() not in KIND_WORDS]
    return " ".join(words)


def is_about(title: str, variant: str) -> bool:
    if SKIP_TITLE.search(title):
        return False
    # Case-sensitive, so "Hidden Lake" the place is not "a hidden lake" the phrase.
    # The full name must not run on into another word ("Chang Co-Anchor", "Gong Co.").
    name = variant if not variant.islower() else variant.title()
    if re.search(rf"\b{re.escape(name)}\b(?![-.]\w?)", title):
        return True
    c = core(name)
    return len(c) >= MIN_CORE and re.search(rf"\b{re.escape(c)}\b", title) is not None \
        and CONTEXT.search(title) is not None


def norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", title.lower())


def parse_rss(xml_text: str) -> list:
    items = []
    for it in ET.fromstring(xml_text).iter("item"):
        src = it.find("source")
        source = src.text if src is not None else ""
        title = it.findtext("title") or ""
        # Google appends " - Publisher" to every title
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3]
        try:
            date = parsedate_to_datetime(it.findtext("pubDate")).date().isoformat()
        except Exception:  # noqa: BLE001
            date = None
        items.append({"title": title.strip(), "url": it.findtext("link"),
                      "source": source, "date": date})
    return items


def merge(existing: list, new: list) -> list:
    """De-duplicate by title (the same story is syndicated under many URLs), newest first."""
    seen, out = set(), []
    for it in sorted(existing + new, key=lambda i: i.get("date") or "", reverse=True):
        key = norm_title(it["title"])
        if not key or key in seen or not it.get("url"):
            continue
        seen.add(key)
        out.append(it)
    return out[:MAX_ITEMS]


def search(variant: str) -> list:
    q = f'"{variant}" {REGION}'
    r = requests.get(RSS, params={"q": q, "hl": "en", "gl": "NP", "ceid": "NP:en"},
                     headers={"User-Agent": "Mozilla/5.0 (compatible; lake-news-collector/1.0)"},
                     timeout=30)
    r.raise_for_status()
    return [i for i in parse_rss(r.text)
            if is_about(i["title"], variant) and not SKIP_SOURCE.search(i["source"] or "")]


def ai_provider():
    """'gemini' | 'anthropic' | None, from which keys are configured."""
    want = (os.getenv("NEWS_PROVIDER") or "").lower()
    have = [p for p, key in (("gemini", "GEMINI_API_KEY"), ("anthropic", "ANTHROPIC_API_KEY"))
            if os.getenv(key)]
    return want if want in have else (have[0] if have else None)


def ai_model(provider: str) -> str:
    return os.getenv("NEWS_MODEL") or AI_DEFAULT_MODEL[provider]


def ai_client():
    """(provider, client) if a key is configured, else None (keyword rules only)."""
    provider = ai_provider()
    if provider == "gemini":
        from google import genai
        from google.genai import types
        return provider, genai.Client(http_options=types.HttpOptions(   # reads GEMINI_API_KEY
            timeout=AI_TIMEOUT_S * 1000, retry_options=types.HttpRetryOptions(attempts=1)))
    if provider == "anthropic":
        import anthropic
        return provider, anthropic.Anthropic(timeout=AI_TIMEOUT_S, max_retries=1)   # reads ANTHROPIC_API_KEY
    return None


def _strip_additional(schema):
    """The same schema without additionalProperties, for Gemini."""
    if isinstance(schema, dict):
        return {k: _strip_additional(v) for k, v in schema.items() if k != "additionalProperties"}
    return schema


def _ask_gemini(client, prompt: str):
    """JSON answer from Gemini's Interactions API, or None (try again next run)."""
    try:
        interaction = client.interactions.create(
            model=ai_model("gemini"),
            input=prompt,
            response_format={"type": "text", "mime_type": "application/json",
                             "schema": _strip_additional(AI_SCHEMA)},
            generation_config={"thinking_level": "low"},
        )
        if interaction.status != "completed":
            print(f"  AI review ended with status {interaction.status}; candidates wait for the next run")
            return None
        return json.loads(interaction.output_text)
    except Exception as ex:  # noqa: BLE001 — free tier: rate limits are routine, never fatal
        print(f"  AI review failed ({type(ex).__name__}: {str(ex)[:120]}); candidates wait for the next run")
        return None


def _ask_anthropic(client, prompt: str):
    """JSON answer from Claude, or None (try again next run)."""
    import anthropic
    try:
        response = client.beta.messages.create(
            model=ai_model("anthropic"),
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "low",
                           "format": {"type": "json_schema", "schema": AI_SCHEMA}},
            messages=[{"role": "user", "content": prompt}],
        )
        if response.stop_reason != "end_turn":
            print(f"  AI review stopped with {response.stop_reason}; candidates wait for the next run")
            return None
        return json.loads(next(b.text for b in response.content if b.type == "text"))
    except anthropic.RateLimitError:
        print("  AI review rate-limited; candidates wait for the next run")
    except anthropic.APIStatusError as ex:
        print(f"  AI review failed ({ex.status_code}); candidates wait for the next run")
    except (anthropic.APIConnectionError, StopIteration, ValueError) as ex:
        print(f"  AI review failed ({type(ex).__name__}); candidates wait for the next run")
    return None


def ai_review(client, lake: dict, kept: list, candidates: list) -> tuple:
    """
    Ask Claude which candidates are about this lake and which repeat a story.
    client is (provider, sdk client). Returns (accepted, rejected); on any
    failure both are empty, so the candidates are simply judged next run.
    """
    provider, sdk = client
    listing = "\n".join(f"[{i}] {c.get('date') or 'undated'} | {c.get('source') or '?'} | {c['title']}"
                        for i, c in enumerate(candidates))
    already = "\n".join(f"- {k.get('date') or 'undated'} | {k['title']}" for k in kept[:MAX_ITEMS]) or "(none)"
    prompt = f"""You are curating a reading list for researchers studying one specific Himalayan lake.

The lake: {lake['name']}
Location: {lake['lat']:.3f}°N, {lake['lon']:.3f}°E, {lake['elev']:.0f} m elevation, in {lake['country']} \
({lake['region']} region of the Nepal Himalaya monitoring area).

Below are news search results whose headline matched the lake's name. Many place names here are shared: \
several lakes in Nepal, India and Tibet are called Panch Pokhari, Dudh Kunda or Tara Lake, and some names \
collide with unrelated things (a Vietnamese beach resort, a computer chip, a film). Only the headline, \
date and publisher are available, so use what you know about where things are.

For each numbered candidate decide:
- about_lake: true only if the item is about this particular lake or events at it (its growth, floods, \
studies, risk reduction, trekking and tourism to it, pilgrimage, ecology). False if it concerns a \
different place with the same name, a company or person named after it, or if the name is incidental. \
When a headline could plausibly be either this lake or a namesake and nothing settles it, answer false: \
a short accurate list is worth more to the reader than a long doubtful one.
- duplicate_of: if the item reports the same story as an EARLIER-numbered candidate (the same article \
syndicated or lightly reworded by another outlet), give that candidate's index. Separate articles about \
the same event by different newsrooms are not duplicates. If it repeats something in the already-kept \
list, set about_lake to false. Use -1 when it is not a duplicate.

Already kept for this lake:
{already}

Candidates:
{listing}

Return one entry per candidate index."""
    answer = (_ask_gemini if provider == "gemini" else _ask_anthropic)(sdk, prompt)
    try:
        verdicts = {int(v["index"]): v for v in answer["items"]} if answer else None
    except (KeyError, TypeError, ValueError):
        verdicts = None
    if verdicts is None:
        return [], []
    accepted, rejected = [], []
    for i, c in enumerate(candidates):
        v = verdicts.get(i)
        if v is None:
            continue                      # not judged: try again next run
        dup = v.get("duplicate_of")
        if v.get("about_lake") and not (isinstance(dup, int) and 0 <= dup < i):
            accepted.append(c)
        else:
            rejected.append(c)
    return accepted, rejected


def collect(named: dict, store: dict, limit: int | None = None,
            lakes: dict | None = None, client=None) -> dict:
    """
    named: {lake_id: name}; lakes: {lake_id: {name, lat, lon, elev, country, region}}
    for the AI review. Returns the updated store.
    """
    by_name = {}
    for lake_id, name in named.items():
        by_name.setdefault(name, []).append(lake_id)
    rejected_store = store.setdefault(REJECTED, {})
    reviewed = set(store.get(REVIEWED, []))
    failures = ai_fails = 0
    started = time.monotonic()
    # Resume after the name the last run stopped at, so a run cut short by the
    # time budget does not starve the end of the alphabet.
    order = sorted(by_name.items())
    cursor = store.pop("_cursor", "")
    order = [x for x in order if x[0] > cursor] + [x for x in order if x[0] <= cursor]
    for n, (name, ids) in enumerate(order):
        if limit and n >= limit:
            break
        if time.monotonic() - started > BUDGET_S:
            print(f"Time budget used up after {n} of {len(by_name)} names — saving; the rest wait for the next run.")
            store["_cursor"] = order[n - 1][0]
            break
        found = []
        for v in variants(name):
            try:
                found += search(v)
            except Exception as ex:  # noqa: BLE001 — keep what we have, try the rest
                failures += 1
                print(f"  {v}: search failed ({ex})")
                if failures >= 8:
                    print("Too many failures — stopping early, keeping earlier results.")
                    return store
            time.sleep(PAUSE_S)
        if found:
            print(f"  {name}: {len(found)} item(s)")
        for lake_id in ids:
            kept, pool = store.get(lake_id, []), found
            recheck = bool(client and lakes and kept and lake_id not in reviewed)
            if recheck:
                # Items kept earlier by the keyword rules alone are judged once too.
                pool, before, kept = found + kept, kept, []
            known = {norm_title(i["title"]) for i in kept} | set(rejected_store.get(lake_id, []))
            # oldest first, so a syndicated copy is the duplicate and the original is kept
            fresh = sorted((i for i in merge([], pool) if norm_title(i["title"]) not in known),
                           key=lambda i: i.get("date") or "")
            if client and lakes and fresh:
                # Two lakes can share a name, so each is judged against its own location.
                asked = len(fresh)
                fresh, rejected = ai_review(client, lakes[lake_id], kept, fresh)
                time.sleep(AI_PAUSE_S)
                if asked and not fresh and not rejected:   # the review failed
                    if recheck:
                        kept = before
                    ai_fails += 1
                    if ai_fails >= AI_MAX_FAILS:
                        print("AI review keeps failing — keyword rules only for the rest of this run.")
                        client = None
                else:
                    ai_fails = 0
                    reviewed.add(lake_id)
                    if rejected:
                        print(f"    {lakes[lake_id]['name']} ({lake_id}): kept {len(fresh)}, rejected {len(rejected)}")
                if rejected:
                    rejected_store[lake_id] = sorted(
                        set(rejected_store.get(lake_id, [])) | {norm_title(i["title"]) for i in rejected})
            merged = merge(kept, fresh)
            if merged:
                store[lake_id] = merged
            elif recheck:
                store.pop(lake_id, None)
            store[REVIEWED] = sorted(reviewed)
    return store


def add_curated(store: dict) -> dict:
    if CURATED.exists():
        for lake_id, links in json.loads(CURATED.read_text()).items():
            if lake_id.startswith("_"):
                continue
            store[lake_id] = merge(store.get(lake_id, []), links)
    return store


def _s3():
    import boto3
    return boto3.client("s3", endpoint_url=os.environ["R2_ENDPOINT_URL"],
                        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
                        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
                        region_name="auto")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inventory", type=Path, help="Local mart_lake_inventory parquet instead of R2")
    ap.add_argument("--out", type=Path, help="Write locally instead of uploading to R2")
    ap.add_argument("--limit", type=int, help="Only search the first N names (testing)")
    args = ap.parse_args()
    bucket = os.getenv("R2_BUCKET_NAME", "himalwatch-data")

    store = {}
    if args.inventory:
        inv = pd.read_parquet(args.inventory)
        if args.out and args.out.exists():
            store = json.loads(args.out.read_text())
    else:
        s3 = _s3()
        buf = io.BytesIO()
        s3.download_fileobj(bucket, "marts/mart_lake_inventory.parquet", buf)
        buf.seek(0)
        inv = pd.read_parquet(buf)
        try:
            store = json.loads(s3.get_object(Bucket=bucket, Key=NEWS_KEY)["Body"].read())
        except Exception:  # noqa: BLE001 — first run
            store = {}

    named = {r.lake_id: r.name_ for r in
             inv.rename(columns={"name": "name_"}).itertuples()
             if isinstance(r.name_, str) and r.name_ and not r.name_.islower()}
    print(f"{len(named)} named lakes, {len(set(named.values()))} distinct names")
    lakes = {r.lake_id: {"name": r.name_, "lat": r.centroid_lat, "lon": r.centroid_lon,
                         "elev": r.mean_elevation or 0, "country": getattr(r, "country", None) or "unknown",
                         "region": str(r.tile).replace("_", " ")}
             for r in inv.rename(columns={"name": "name_"}).itertuples() if r.lake_id in named}
    client = ai_client()
    print("AI review: " + (f"on ({client[0]}, {ai_model(client[0])})" if client
                           else "off (no GEMINI_API_KEY or ANTHROPIC_API_KEY) — keyword rules only"))
    store = add_curated(collect(named, store, args.limit, lakes, client))
    real = {k: v for k, v in store.items() if not k.startswith("_")}
    print(f"{sum(len(v) for v in real.values())} links for {len(real)} lakes")

    body = json.dumps(store, ensure_ascii=False, indent=1)
    if args.out:
        args.out.write_text(body)
    else:
        _s3().put_object(Bucket=bucket, Key=NEWS_KEY, Body=body.encode(),
                         ContentType="application/json")
        print(f"Uploaded -> {NEWS_KEY}")


if __name__ == "__main__":
    main()
