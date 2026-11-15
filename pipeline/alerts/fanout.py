"""
HimalWatch — Alert Fan-out

Runs after dbt + GIF generation. Notifies about lakes that are GROWING
steadily, and lakes that changed in one SUDDEN step such as a new reservoir
(both rules are in dbt/models/marts/mart_lake_inventory.sql), and that have
not been notified before for this severity.

Channels:
  1. GitHub Issue — one digest issue per run, @-mentioning the repo owner.
     GitHub emails the owner, so this is the zero-setup email path.
  2. Email via Resend — optional, a nicer HTML email with the GIFs inline.
     Needs secrets RESEND_API_KEY and ALERT_EMAIL_TO.
  3. Atom feed — alerts.atom in R2 with all current alerts.

What has been notified is remembered in R2 (alerts/notified.json), so weekly
re-runs over the same season stay silent.

Env:
  R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME
  R2_PUBLIC_URL      public bucket URL (links + GIFs)
  GITHUB_TOKEN, GITHUB_REPO
  RESEND_API_KEY     optional
  ALERT_EMAIL_TO     optional, comma-separated recipients
  ALERT_EMAIL_FROM   optional, default "HimalWatch <onboarding@resend.dev>"
                     (Resend's shared sender: delivers only to the address the
                     Resend account was created with — fine for personal alerts)
  DASHBOARD_URL      optional
  DRY_RUN=1          print instead of sending; do not update state
  ALERT_HOLD         optional, comma-separated severities that are shown on the
                     dashboard but not notified yet (e.g. "SUDDEN" while a new
                     alert type is being checked by hand). They are sent once
                     the hold is lifted.
"""
from __future__ import annotations

import html
import io
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

BUCKET      = os.getenv("R2_BUCKET_NAME", "himalwatch-data")
PUBLIC_URL  = os.getenv("R2_PUBLIC_URL", "").rstrip("/")
STATE_KEY   = "alerts/notified.json"
DRY_RUN     = os.getenv("DRY_RUN") == "1"
HOLD        = {s.strip().upper() for s in os.getenv("ALERT_HOLD", "").split(",") if s.strip()}
MAX_GIFS    = 8      # GIFs embedded per notification
SEV_ORDER   = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "SUDDEN": 3}
SEV_COLOUR  = {"HIGH": "#ef4444", "MEDIUM": "#f97316", "LOW": "#eab308", "SUDDEN": "#a855f7"}


def _s3():
    import boto3
    return boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT_URL"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )


def _exists(s3, key: str) -> bool:
    try:
        s3.head_object(Bucket=BUCKET, Key=key)
        return True
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# Pure helpers (unit-testable without network)
# ---------------------------------------------------------------------------

def alert_key(a: dict) -> str:
    """Identity of one notification: a lake is announced once per severity tier."""
    return f"{a['lake_id']}:{a['alert_severity']}"


def enrich(a: dict, gif_ids: set) -> dict:
    lat, lon = float(a["centroid_lat"]), float(a["centroid_lon"])
    a = dict(a)
    name, hint = a.get("name"), a.get("name_hint")
    if not isinstance(name, str) or not name:
        name = (f"Unnamed lake {hint}" if isinstance(hint, str) and hint
                else f"Unnamed lake {a['lake_id']}")
    a["name"]    = name
    a["map_url"] = f"https://www.google.com/maps/@{lat:.5f},{lon:.5f},2500m/data=!3m1!1e3"
    a["gif_url"] = (f"{PUBLIC_URL}/media/lakes/{a['lake_id']}/growth.gif"
                    if a["lake_id"] in gif_ids else None)
    rank = a.get("icimod_rank")
    if isinstance(rank, str) and rank:      # on ICIMOD's 2020 dangerous-lake list
        name += f" · ICIMOD Rank {rank}"
        a["name"] = name
    a["sudden"] = a["alert_severity"] == "SUDDEN"
    if a["sudden"]:
        # before = largest season before the jump, now = smallest season since
        a["now_ha"]  = float(a["sudden_after_sqm"]) / 1e4
        a["base_ha"] = float(a["sudden_before_sqm"]) / 1e4
        a["growth_pct"] = (a["now_ha"] / a["base_ha"] - 1) * 100
    else:
        a["now_ha"]  = float(a["recent_area_sqm"]) / 1e4
        a["base_ha"] = float(a["baseline_area_sqm"]) / 1e4
    return a


def select_new(alerts: list, notified: dict) -> list:
    new = [a for a in alerts if alert_key(a) not in notified]
    return sorted(new, key=lambda a: (SEV_ORDER.get(a["alert_severity"], 9), -float(a["growth_pct"])))


def subject_for(new: list) -> str:
    high = sum(a["alert_severity"] == "HIGH" for a in new)
    sudden = sum(a["sudden"] for a in new)
    n = len(new) - sudden
    parts = []
    if n:
        parts.append(f"{n} glacial lake{'s' if n != 1 else ''} growing"
                     + (f" ({high} HIGH)" if high else ""))
    if sudden:
        parts.append(f"{sudden} sudden change{'s' if sudden != 1 else ''}")
    return "HimalWatch: " + ", ".join(parts)


def _where(a: dict) -> str:
    country = f", {a['country']}" if isinstance(a.get("country"), str) else ""
    return f"({a['centroid_lat']:.4f}°N, {a['centroid_lon']:.4f}°E, {a['tile']}{country})"


def issue_body(new: list, owner: str, dashboard: str) -> str:
    season = max(int(a["latest_detection_year"]) for a in new)
    growing = [a for a in new if not a["sudden"]]
    sudden = [a for a in new if a["sudden"]]
    lines = [f"@{owner} — new from the {season} season."]
    if growing:
        lines += [
            "", f"### {len(growing)} lake(s) growing steadily", "",
            "| Severity | Lake | Recent area | Early area | Growth | Seasons seen | Elevation |",
            "|---|---|---|---|---|---|---|",
        ]
        for a in growing:
            lines.append(
                f"| **{a['alert_severity']}** | [{a['name']}]({a['map_url']}) {_where(a)} "
                f"| {a['now_ha']:.1f} ha | {a['base_ha']:.1f} ha | **{a['growth_pct']:+.0f}%** "
                f"| {int(a['detection_count'])} | {float(a['mean_elevation']):.0f} m |"
            )
    if sudden:
        lines += [
            "", f"### {len(sudden)} sudden change(s)", "",
            "A one-step jump that has held for at least two seasons — typically a new "
            "reservoir or a dammed river rather than a growing glacial lake. Any country.", "",
            "| Lake | Before | Since | Jump year | Elevation |",
            "|---|---|---|---|---|",
        ]
        for a in sudden:
            lines.append(
                f"| [{a['name']}]({a['map_url']}) {_where(a)} "
                f"| {a['base_ha']:.1f} ha | ≥ {a['now_ha']:.1f} ha "
                f"| {int(a['sudden_year'])} | {float(a['mean_elevation']):.0f} m |"
            )
    gifs = [a for a in new if a["gif_url"]][:MAX_GIFS]
    if gifs:
        lines += ["", "### Satellite time-lapse (Sentinel-2, Sep–Oct each year)", ""]
        for a in gifs:
            lines += [f"**{a['name']}** — {a['growth_pct']:+.0f}%", "",
                      f"![{a['name']}]({a['gif_url']})", ""]
    lines += [
        "---",
        "*ICIMOD Rank I–III = on the ICIMOD/UNDP 2020 list of potentially dangerous glacial lakes "
        "(https://doi.org/10.53055/ICIMOD.773); Rank I is the most critical.*",
        "",
        "*Sudden change = every season since the jump is ≥ 3× and ≥ 5 ha larger than every season before it.*",
        "",
        "*Growing = seen in ≥ 5 seasons, area rising consistently year over year, and recent seasons ≥ 10% and ≥ 1 ha larger than the earliest seasons. Areas are medians of the first / last "
        "seasons observed. Automated detection — check the imagery before acting on it.*",
    ]
    if dashboard:
        lines.append(f"\n[Open dashboard]({dashboard})")
    return "\n".join(lines)


def email_html(new: list, dashboard: str) -> str:
    e = html.escape
    rows = "".join(
        f"""<tr>
  <td style="padding:8px;border-bottom:1px solid #2a2d3a"><b style="color:{SEV_COLOUR.get(a['alert_severity'], '#fff')}">{e(a['alert_severity'])}</b></td>
  <td style="padding:8px;border-bottom:1px solid #2a2d3a"><a href="{e(a['map_url'])}" style="color:#60a5fa">{e(a['name'])}</a><br><span style="color:#8892a4;font-size:12px">{a['centroid_lat']:.4f}°N {a['centroid_lon']:.4f}°E · {e(str(a['tile']))}</span></td>
  <td style="padding:8px;border-bottom:1px solid #2a2d3a">{a['base_ha']:.1f} → {a['now_ha']:.1f} ha</td>
  <td style="padding:8px;border-bottom:1px solid #2a2d3a"><b>{a['growth_pct']:+.0f}%</b></td>
</tr>""" for a in new)
    gifs = "".join(
        f"""<p style="margin:20px 0 6px"><b>{e(a['name'])}</b> — {a['growth_pct']:+.0f}%</p>
<img src="{e(a['gif_url'])}" width="480" style="max-width:100%;border-radius:6px" alt="{e(a['name'])} time-lapse">"""
        for a in [a for a in new if a["gif_url"]][:MAX_GIFS])
    dash = f'<p><a href="{e(dashboard)}" style="color:#60a5fa">Open dashboard</a></p>' if dashboard else ""
    return f"""<div style="font-family:sans-serif;background:#0f1117;color:#e2e8f0;padding:24px;max-width:640px">
<h2 style="color:#60a5fa;margin:0 0 4px">HimalWatch</h2>
<p style="color:#8892a4;margin:0 0 16px">Glacial lake monitoring · Nepal Himalaya</p>
<p>{len(new)} lake(s) newly flagged: {sum(not a['sudden'] for a in new)} growing steadily, {sum(a['sudden'] for a in new)} sudden change(s) (a one-step jump that has held, such as a new reservoir).</p>
<table style="width:100%;border-collapse:collapse;font-size:14px">
<thead><tr style="background:#1a1d27;color:#8892a4;font-size:11px;text-align:left">
<th style="padding:8px">Severity</th><th style="padding:8px">Lake</th><th style="padding:8px">Area (before → now)</th><th style="padding:8px">Change</th></tr></thead>
<tbody>{rows}</tbody></table>
{gifs}
{dash}
<p style="color:#8892a4;font-size:11px;margin-top:24px">Growing = seen in ≥ 5 seasons, area rising consistently year over year, and recent seasons ≥ 10% and ≥ 1 ha larger than the earliest seasons. Automated detection from Sentinel-2 — verify before acting.</p>
</div>"""


def atom_feed(alerts: list, repo_url: str) -> str:
    e = html.escape
    now = datetime.now(timezone.utc).isoformat()
    entries = "".join(f"""
  <entry>
    <id>{e(repo_url)}/alerts/{e(alert_key(a))}</id>
    <title>[{e(a['alert_severity'])}] {e(a['name'])} {'jumped' if a['sudden'] else 'growing'} {a['growth_pct']:+.0f}%</title>
    <updated>{now}</updated>
    <summary>{e(a['name'])} ({a['centroid_lat']:.4f}N, {a['centroid_lon']:.4f}E, {e(str(a['tile']))}): {a['base_ha']:.1f} ha early, {a['now_ha']:.1f} ha recent.</summary>
    <link href="{e(a['map_url'])}" rel="related"/>
  </entry>""" for a in alerts[:50])
    return f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>HimalWatch — Growing glacial lakes</title>
  <id>{e(repo_url)}</id>
  <link href="{e(repo_url)}" rel="alternate"/>
  <link href="{e(PUBLIC_URL)}/alerts.atom" rel="self"/>
  <updated>{now}</updated>
  <author><name>HimalWatch Pipeline</name></author>{entries}
</feed>"""


# ---------------------------------------------------------------------------
# Channels
# ---------------------------------------------------------------------------

def create_issue(title: str, body: str) -> bool:
    token, repo = os.getenv("GITHUB_TOKEN"), os.getenv("GITHUB_REPO")
    if not token or not repo:
        print("  Skipping GitHub Issue — GITHUB_TOKEN or GITHUB_REPO not set.")
        return False
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    url = f"https://api.github.com/repos/{repo}/issues"
    resp = requests.post(url, headers=headers, timeout=20,
                         json={"title": title, "body": body, "labels": ["alert"]})
    if resp.status_code == 422:      # label problem — retry bare
        resp = requests.post(url, headers=headers, timeout=20, json={"title": title, "body": body})
    if resp.status_code == 201:
        print(f"  GitHub Issue created: {resp.json()['html_url']}")
        return True
    print(f"  GitHub Issue failed: {resp.status_code} {resp.text[:300]}")
    return False


def send_email(subject: str, body_html: str) -> bool:
    key = os.getenv("RESEND_API_KEY")
    to = [t.strip() for t in os.getenv("ALERT_EMAIL_TO", "").split(",") if t.strip()]
    if not key or not to:
        print("  Skipping Resend email — RESEND_API_KEY / ALERT_EMAIL_TO not set "
              "(the GitHub Issue notification is the email in that case).")
        return False
    resp = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {key}"},
        json={"from": os.getenv("ALERT_EMAIL_FROM") or "HimalWatch <onboarding@resend.dev>",
              "to": to, "subject": subject, "html": body_html},
        timeout=20,
    )
    if resp.status_code in (200, 201):
        print(f"  Email sent ({len(to)} recipient(s)): {resp.json().get('id')}")
        return True
    print(f"  Email failed: {resp.status_code} {resp.text[:300]}")
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=== HimalWatch Alert Fan-out ===")
    s3 = _s3()

    buf = io.BytesIO()
    s3.download_fileobj(BUCKET, "marts/mart_change_alerts.parquet", buf)
    buf.seek(0)
    current = pd.read_parquet(buf).to_dict("records")
    print(f"{len(current)} lake(s) currently flagged (growing or sudden change).")

    gif_ids = {a["lake_id"] for a in current
               if _exists(s3, f"media/lakes/{a['lake_id']}/growth.gif")}
    current = [enrich(a, gif_ids) for a in current]

    try:
        notified = json.loads(s3.get_object(Bucket=BUCKET, Key=STATE_KEY)["Body"].read())
    except Exception:  # noqa: BLE001 — first run
        notified = {}

    new = select_new(current, notified)
    held = [a for a in new if a["alert_severity"] in HOLD]
    if held:
        new = [a for a in new if a["alert_severity"] not in HOLD]
        print(f"{len(held)} new alert(s) held back by ALERT_HOLD={','.join(sorted(HOLD))}: "
              + ", ".join(a["name"] for a in held))
    print(f"{len(new)} new since last notification.")

    repo = os.getenv("GITHUB_REPO", "")
    repo_url = f"https://github.com/{repo}"
    dashboard = os.getenv("DASHBOARD_URL", "")

    if not DRY_RUN:
        s3.put_object(Bucket=BUCKET, Key="alerts.atom",
                      Body=atom_feed(current, repo_url).encode(),
                      ContentType="application/atom+xml",
                      CacheControl="public, max-age=3600")

    if not new:
        print("Nothing new — no notification sent.")
        return

    subject = subject_for(new)
    body = issue_body(new, repo.split("/")[0] or "owner", dashboard)
    if DRY_RUN:
        print(subject, "\n", body)
        return

    sent_issue = create_issue(subject, body)
    sent_email = send_email(subject, email_html(new, dashboard))

    if sent_issue or sent_email:
        stamp = datetime.now(timezone.utc).isoformat()
        notified.update({alert_key(a): stamp for a in new})
        s3.put_object(Bucket=BUCKET, Key=STATE_KEY,
                      Body=json.dumps(notified, indent=1).encode(),
                      ContentType="application/json")
        print("Notification state saved.")
    else:
        print("No channel succeeded — will retry next run.")
        sys.exit(1)


if __name__ == "__main__":
    main()
