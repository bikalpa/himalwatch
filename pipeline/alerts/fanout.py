"""
HimalWatch — Alert Fan-out

Runs after the pipeline + dbt step. Diffs the new mart_change_alerts
against the previous run's snapshot and fans out NEW high-severity alerts to:

  1. GitHub Issues  — public audit trail, auto-created for HIGH alerts
  2. RSS/Atom feed  — alerts.atom written to R2, subscribable by researchers
  3. Email          — via Resend API (opt-in, free tier 100/day)

"New" means: alert exists in today's mart but NOT in yesterday's snapshot.
This prevents re-notifying for ongoing alerts on every weekly run.

Required env vars:
  R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME
  R2_PUBLIC_URL          — public bucket URL for links in notifications
  GITHUB_TOKEN           — provided automatically by GitHub Actions
  GITHUB_REPO            — e.g. "bikalpa/himalwatch"
  RESEND_API_KEY         — optional; skip email if not set
"""

import io
import json
import os
import sys
from datetime import datetime, timezone
from email.utils import formatdate
from pathlib import Path
from typing import List

import boto3
import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")

# ---------------------------------------------------------------------------
# R2 client
# ---------------------------------------------------------------------------

def _s3():
    return boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT_URL"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
    )

BUCKET     = os.getenv("R2_BUCKET_NAME", "himalwatch-data")
PUBLIC_URL = os.getenv("R2_PUBLIC_URL", "")


def _download_parquet(key: str) -> pd.DataFrame:
    buf = io.BytesIO()
    _s3().download_fileobj(BUCKET, key, buf)
    buf.seek(0)
    return pd.read_parquet(buf)


def _key_exists(key: str) -> bool:
    try:
        _s3().head_object(Bucket=BUCKET, Key=key)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Diff — find alerts that are new since last run
# ---------------------------------------------------------------------------

def find_new_alerts(current: pd.DataFrame) -> pd.DataFrame:
    """
    Compare current alerts against the most recent previous snapshot.
    Returns rows in current that are not in the previous run.
    """
    # Find latest previous snapshot
    today = datetime.now(timezone.utc).date().isoformat()
    paginator = _s3().get_paginator("list_objects_v2")
    snapshots = []

    for page in paginator.paginate(Bucket=BUCKET, Prefix="marts/snapshots/"):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if "mart_change_alerts" in key and today not in key:
                snapshots.append(key)

    if not snapshots:
        print("No previous snapshot found — treating all current alerts as new.")
        return current

    # Use the most recent snapshot
    latest_snap_key = sorted(snapshots)[-1]
    print(f"Comparing against: {latest_snap_key}")

    try:
        prev = _download_parquet(latest_snap_key)
        prev_ids = set(prev["lake_id"].tolist())
        new_alerts = current[~current["lake_id"].isin(prev_ids)]
        print(f"  {len(current)} current alerts, {len(prev_ids)} previous, "
              f"{len(new_alerts)} NEW")
        return new_alerts
    except Exception as e:
        print(f"Could not load previous snapshot: {e} — treating all as new.")
        return current


# ---------------------------------------------------------------------------
# Channel 1 — GitHub Issues
# ---------------------------------------------------------------------------

def create_github_issue(alert: dict):
    token = os.getenv("GITHUB_TOKEN")
    repo  = os.getenv("GITHUB_REPO")
    if not token or not repo:
        print("  Skipping GitHub Issue — GITHUB_TOKEN or GITHUB_REPO not set.")
        return

    chg = f"{alert.get('area_change_pct', 0):+.1f}%"
    vol = f"{alert.get('volume_change_mcm', 0):+.3f} MCM"
    run = alert.get("days_since_observation", "?")
    sev = alert["alert_severity"]

    title = f"[{sev}] Lake {alert['lake_id']} area change {chg} — {alert['tile']}"
    body  = f"""## Glacial Lake Alert — {sev} Severity

**Lake ID**: `{alert['lake_id']}`
**Tile**: {alert['tile']}
**Coordinates**: {alert['centroid_lat']:.4f}°N, {alert['centroid_lon']:.4f}°E
**Elevation**: {alert.get('mean_elevation', '?'):.0f} m

### Change Summary
| Metric | Value |
|--------|-------|
| Area change | **{chg}** |
| Volume change | **{vol}** |
| First detected | {alert.get('first_detected_date', '?')} |
| Latest detection | {alert.get('latest_detection_date', '?')} |
| Days since observation | {run} |

### Areas at Risk
- Runout distance estimate: {alert.get('runout_km', '?')} km
- Settlements in runout zone: {alert.get('settlements_in_runout', '?')}
- Population estimate: {alert.get('population_estimate', '?')}

### Data Links
- [Lake inventory]({PUBLIC_URL}/marts/mart_lake_inventory.parquet)
- [All alerts]({PUBLIC_URL}/marts/mart_change_alerts.parquet)

---
*Auto-generated by HimalWatch pipeline. Verify against optical imagery before action.*
*Alert threshold: area change >30% with ≥2 detections within 90 days.*
"""

    resp = requests.post(
        f"https://api.github.com/repos/{repo}/issues",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept":        "application/vnd.github+json",
        },
        json={
            "title":  title,
            "body":   body,
            "labels": ["alert", sev.lower(), alert["tile"]],
        },
        timeout=15,
    )

    if resp.status_code == 201:
        print(f"  GitHub Issue created: {resp.json()['html_url']}")
    else:
        print(f"  GitHub Issue failed: {resp.status_code} {resp.text[:200]}")


# ---------------------------------------------------------------------------
# Channel 2 — RSS/Atom feed
# ---------------------------------------------------------------------------

def update_rss_feed(all_alerts: List[dict]):
    """Write an Atom feed of current alerts to R2."""
    now_rfc  = formatdate(usegmt=True)
    now_iso  = datetime.now(timezone.utc).isoformat()
    repo_url = f"https://github.com/{os.getenv('GITHUB_REPO', 'bikalpa/himalwatch')}"

    entries = ""
    for a in all_alerts[:20]:  # Atom spec: latest 20
        chg = f"{a.get('area_change_pct', 0):+.1f}%"
        sev = a["alert_severity"]
        entries += f"""
  <entry>
    <id>{repo_url}/issues/auto/{a['lake_id']}</id>
    <title>[{sev}] Lake {a['lake_id']} area {chg} — {a['tile']}</title>
    <updated>{now_iso}</updated>
    <summary>
      Glacial lake {a['lake_id']} in {a['tile']} tile shows {chg} area change.
      Elevation: {a.get('mean_elevation', '?'):.0f}m.
      Volume change: {a.get('volume_change_mcm', '?'):+.3f} MCM.
      Alert severity: {sev}.
    </summary>
    <link href="{PUBLIC_URL}/marts/mart_change_alerts.parquet" rel="related"/>
  </entry>"""

    feed = f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>HimalWatch — Glacial Lake Change Alerts</title>
  <subtitle>Automated alerts for anomalous glacial lake area change in Nepal Himalaya</subtitle>
  <id>{repo_url}</id>
  <link href="{repo_url}" rel="alternate"/>
  <link href="{PUBLIC_URL}/alerts.atom" rel="self"/>
  <updated>{now_iso}</updated>
  <author><name>HimalWatch Pipeline</name></author>
  {entries}
</feed>"""

    _s3().put_object(
        Bucket=BUCKET,
        Key="alerts.atom",
        Body=feed.encode(),
        ContentType="application/atom+xml",
        CacheControl="public, max-age=3600",
    )
    print(f"  RSS feed updated -> {PUBLIC_URL}/alerts.atom")


# ---------------------------------------------------------------------------
# Channel 3 — Email via Resend
# ---------------------------------------------------------------------------

def send_email_alerts(new_alerts: List[dict]):
    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        print("  Skipping email — RESEND_API_KEY not set.")
        return

    if not new_alerts:
        return

    high   = [a for a in new_alerts if a["alert_severity"] == "HIGH"]
    medium = [a for a in new_alerts if a["alert_severity"] == "MEDIUM"]

    subject = f"HimalWatch: {len(new_alerts)} new alert(s)"
    if high:
        subject = f"HimalWatch: {len(high)} HIGH severity glacial lake alert(s)"

    rows = "".join(f"""
    <tr>
      <td style="padding:6px 8px;border-bottom:1px solid #2a2d3a">
        <b style="color:{'#ef4444' if a['alert_severity']=='HIGH' else '#f97316'}">[{a['alert_severity']}]</b>
        {a['lake_id']}
      </td>
      <td style="padding:6px 8px;border-bottom:1px solid #2a2d3a">{a['tile']}</td>
      <td style="padding:6px 8px;border-bottom:1px solid #2a2d3a">{a.get('area_change_pct', 0):+.1f}%</td>
      <td style="padding:6px 8px;border-bottom:1px solid #2a2d3a">{a.get('mean_elevation', '?'):.0f} m</td>
    </tr>""" for a in new_alerts)

    html = f"""
    <div style="font-family:sans-serif;background:#0f1117;color:#e2e8f0;padding:24px;max-width:600px">
      <h2 style="color:#3b82f6;margin-bottom:4px">HimalWatch</h2>
      <p style="color:#8892a4;margin-bottom:16px">Glacial Lake Monitoring · Nepal Himalaya</p>
      <p>{len(new_alerts)} new lake alert(s) detected in the latest pipeline run.</p>
      <table style="width:100%;border-collapse:collapse;margin-top:16px">
        <thead>
          <tr style="background:#1a1d27">
            <th style="padding:8px;text-align:left;font-size:11px;color:#8892a4">Lake</th>
            <th style="padding:8px;text-align:left;font-size:11px;color:#8892a4">Tile</th>
            <th style="padding:8px;text-align:left;font-size:11px;color:#8892a4">Change</th>
            <th style="padding:8px;text-align:left;font-size:11px;color:#8892a4">Elevation</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
      <p style="margin-top:16px">
        <a href="{PUBLIC_URL}/marts/mart_change_alerts.parquet"
           style="color:#3b82f6">Download full alerts Parquet</a>
      </p>
      <p style="color:#8892a4;font-size:11px;margin-top:24px">
        Auto-generated by HimalWatch. Data under CC BY 4.0.
      </p>
    </div>"""

    resp = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "from":    "HimalWatch <alerts@himalwatch.earth>",
            "to":      ["bikalpa@gmail.com"],
            "subject": subject,
            "html":    html,
        },
        timeout=15,
    )

    if resp.status_code in (200, 201):
        print(f"  Email sent: {resp.json().get('id')}")
    else:
        print(f"  Email failed: {resp.status_code} {resp.text[:200]}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== HimalWatch Alert Fan-out ===")

    try:
        current = _download_parquet("marts/mart_change_alerts.parquet")
        print(f"Loaded {len(current)} current alerts.")
    except Exception as e:
        print(f"No alerts parquet found: {e}")
        sys.exit(0)

    if current.empty:
        print("No active alerts — nothing to fan out.")
        sys.exit(0)

    new_alerts = find_new_alerts(current)
    all_alerts = current.to_dict("records")
    new_list   = new_alerts.to_dict("records") if not new_alerts.empty else []

    print(f"\n{len(new_list)} new alert(s) to notify.")

    # Channel 1: GitHub Issues (HIGH only — avoid issue spam)
    for alert in new_list:
        if alert["alert_severity"] == "HIGH":
            print(f"Creating GitHub Issue for {alert['lake_id']} ...")
            create_github_issue(alert)

    # Channel 2: RSS feed (all current alerts)
    print("Updating RSS feed ...")
    update_rss_feed(all_alerts)

    # Channel 3: Email (new HIGH + MEDIUM only)
    notify = [a for a in new_list if a["alert_severity"] in ("HIGH", "MEDIUM")]
    if notify:
        print(f"Sending email for {len(notify)} alert(s) ...")
        send_email_alerts(notify)

    print("\nFan-out complete.")
