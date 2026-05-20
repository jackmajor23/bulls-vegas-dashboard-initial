#!/usr/bin/env python3
"""
Bradford Bulls – Vegas 2027 Dashboard Data Fetcher
===================================================
Fetches from:
  • Google Analytics 4 (GA4 Data API)
  • WordPress REST API  (CF7 via CF7 Advanced DB plugin — default)
  • YouTube Data API v3

Run manually:   python scripts/fetch_data.py
Run via CI:     GitHub Actions (see .github/workflows/update-data.yml)

Required environment variables (set as GitHub Secrets):
  GA4_PROPERTY_ID               e.g.  properties/123456789
  GOOGLE_SERVICE_ACCOUNT_JSON   full JSON string of a GCP service-account key
  YOUTUBE_API_KEY               a YouTube Data API v3 key
  YOUTUBE_VIDEO_ID              the video ID  (e.g. dQw4w9WgXcQ)
  WP_BASE_URL                   e.g.  https://bradfordbulls.co.uk
  WP_USERNAME                   WordPress username
  WP_APP_PASSWORD               WordPress Application Password (Settings → Users → Application Passwords)

Optional (social media — leave blank to show '—' on the dashboard):
  META_ACCESS_TOKEN             Facebook/Instagram Graph API long-lived page token
  META_PAGE_ID                  Facebook Page ID
  META_IG_USER_ID               Instagram Business Account ID

CF7 data source:
  Default: CF7 Advanced DB plugin (stores submissions in wp_cf7_submissions / wp_cf7_submission_data).
  The custom REST endpoint (added via functions.php) queries the Advanced DB tables directly,
  summing the 'adults' and 'children' fields from each submission row.
  Fallback: if Advanced DB tables are absent the endpoint falls back to counting Flamingo rows.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

# ── Optional GA4 imports (skip if not installed)
try:
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import (
        DateRange, Dimension, Filter, FilterExpression, Metric, RunReportRequest,
    )
    from google.oauth2 import service_account
    GA4_AVAILABLE = True
except ImportError:
    GA4_AVAILABLE = False
    print("⚠  google-analytics-data not installed – GA4 section will be skipped.")

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION (read from env)
# ─────────────────────────────────────────────────────────────────────────────
GA4_PROPERTY_ID            = os.environ.get("GA4_PROPERTY_ID", "")
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
YOUTUBE_API_KEY            = os.environ.get("YOUTUBE_API_KEY", "")
YOUTUBE_VIDEO_ID           = os.environ.get("YOUTUBE_VIDEO_ID", "")
WP_BASE_URL                = os.environ.get("WP_BASE_URL", "").rstrip("/")
WP_USERNAME                = os.environ.get("WP_USERNAME", "")
WP_APP_PASSWORD            = os.environ.get("WP_APP_PASSWORD", "")
META_ACCESS_TOKEN          = os.environ.get("META_ACCESS_TOKEN", "")
META_PAGE_ID               = os.environ.get("META_PAGE_ID", "")
META_IG_USER_ID            = os.environ.get("META_IG_USER_ID", "")

# Date range: rolling 30 days
NOW       = datetime.now(timezone.utc)
END_DATE  = NOW.strftime("%Y-%m-%d")
START_DATE = (NOW - timedelta(days=30)).strftime("%Y-%m-%d")
PREV_END  = (NOW - timedelta(days=31)).strftime("%Y-%m-%d")
PREV_START = (NOW - timedelta(days=61)).strftime("%Y-%m-%d")

# ─────────────────────────────────────────────────────────────────────────────
# ★  PAGES TO TRACK  ★
# ─────────────────────────────────────────────────────────────────────────────
# Add or remove pages here. Each entry needs:
#   "name"  — display label shown on the dashboard
#   "url"   — the exact page path on your site (used for the clickable link)
#   "match" — a unique string that appears in the GA4 page path for this page
#             (partial match — e.g. "las-vegas-2027" matches /las-vegas-2027/
#              and any sub-pages like /las-vegas-2027/faq/)
#
# The GA4 filter is built automatically from all "match" values, so overall
# traffic totals cover every page in this list.
#
# To add a page: copy a block, fill in name/url/match, save and push.
# To remove a page: delete its block entirely.
# ─────────────────────────────────────────────────────────────────────────────
PAGES_TO_TRACK = [
    {
        "name":  "Las Vegas 2027 Hub",
        "url":   "/las-vegas-2027/",
        "match": "las-vegas-2027",        # must appear in the GA4 page path
    },
    {
        "name":  "CEO Statement",
        "url":   "/news/ceo-jason-hirst-issues-statement/",
        "match": "ceo-jason-hirst",
    },
    {
        "name":  "We're Heading to Vegas",
        "url":   "/news/were-heading-to-vegas/",
        "match": "were-heading-to-vegas",
    },
    # ── Add more pages below — copy a block above and fill in your values ──────
    # {
    #     "name":  "Vegas FAQ",
    #     "url":   "/las-vegas-2027/faq/",
    #     "match": "las-vegas-2027/faq",
    # },
    # {
    #     "name":  "Vegas Ticket Packages",
    #     "url":   "/las-vegas-2027/tickets/",
    #     "match": "las-vegas-2027/tickets",
    # },
]

# Which page hosts the CF7 interest form?
# Set to the "match" value of that page — used to calculate the conversion rate.
CF7_HUB_MATCH = "las-vegas-2027"

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def fmt(n: int) -> str:
    """Format integer as '12.3K', '1.2M', etc."""
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)

def secs_to_mmss(s: float) -> str:
    s = int(s)
    return f"{s // 60}:{s % 60:02d}"

def pct_delta(current: int, prev: int) -> str:
    if prev == 0:
        return ""
    pct = round((current - prev) / prev * 100)
    arrow = "↑" if pct >= 0 else "↓"
    return f"{arrow} {abs(pct)}% vs prev. period"


# ─────────────────────────────────────────────────────────────────────────────
# GA4
# ─────────────────────────────────────────────────────────────────────────────
def fetch_ga4():
    if not GA4_AVAILABLE:
        return {}, [], 0
    if not GA4_PROPERTY_ID or not GOOGLE_SERVICE_ACCOUNT_JSON:
        print("⚠  GA4 env vars not set – skipping.")
        return {}, [], 0

    print("→ Fetching GA4 data…")
    creds_info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    credentials = service_account.Credentials.from_service_account_info(
        creds_info,
        scopes=["https://www.googleapis.com/auth/analytics.readonly"],
    )
    client = BetaAnalyticsDataClient(credentials=credentials)

    # Build an OR filter across all page match strings from PAGES_TO_TRACK
    from google.analytics.data_v1beta.types import FilterExpressionList

    def make_path_filter(match_value):
        return FilterExpression(
            filter=Filter(
                field_name="pagePath",
                string_filter=Filter.StringFilter(
                    match_type=Filter.StringFilter.MatchType.CONTAINS,
                    value=match_value,
                ),
            )
        )

    if len(PAGES_TO_TRACK) == 1:
        combined_filter = make_path_filter(PAGES_TO_TRACK[0]["match"])
    else:
        combined_filter = FilterExpression(
            or_group=FilterExpressionList(
                expressions=[make_path_filter(p["match"]) for p in PAGES_TO_TRACK]
            )
        )

    def run(date_ranges, metrics, dimensions=None, dim_filter=None):
        req = RunReportRequest(
            property=GA4_PROPERTY_ID,
            date_ranges=date_ranges,
            metrics=metrics,
            dimension_filter=dim_filter,
        )
        if dimensions:
            req.dimensions = dimensions
        return client.run_report(req)

    # ── Overall totals (current period)
    r = run(
        [DateRange(start_date=START_DATE, end_date=END_DATE)],
        [Metric(name="screenPageViews"), Metric(name="sessions"),
         Metric(name="activeUsers"),     Metric(name="averageSessionDuration")],
        dim_filter=combined_filter,
    )
    row = r.rows[0] if r.rows else None
    pv  = int(row.metric_values[0].value) if row else 0
    ses = int(row.metric_values[1].value) if row else 0
    usr = int(row.metric_values[2].value) if row else 0
    dur = float(row.metric_values[3].value) if row else 0.0

    # ── Overall totals (previous period for delta)
    rp = run(
        [DateRange(start_date=PREV_START, end_date=PREV_END)],
        [Metric(name="screenPageViews"), Metric(name="sessions"), Metric(name="activeUsers")],
        dim_filter=combined_filter,
    )
    rowp = rp.rows[0] if rp.rows else None
    pv_p  = int(rowp.metric_values[0].value) if rowp else 0
    ses_p = int(rowp.metric_values[1].value) if rowp else 0
    usr_p = int(rowp.metric_values[2].value) if rowp else 0

    traffic = {
        "pageviews": fmt(pv),
        "sessions":  fmt(ses),
        "users":     fmt(usr),
        "avg_time":  secs_to_mmss(dur),
        "delta": {
            "pageviews": pct_delta(pv, pv_p),
            "sessions":  pct_delta(ses, ses_p),
            "users":     pct_delta(usr, usr_p),
            "avg_time":  "",
        },
    }

    # ── Per-page breakdown
    rp2 = run(
        [DateRange(start_date=START_DATE, end_date=END_DATE)],
        [Metric(name="screenPageViews"), Metric(name="averageSessionDuration"), Metric(name="bounceRate")],
        dimensions=[Dimension(name="pagePath"), Dimension(name="pageTitle")],
        dim_filter=combined_filter,
    )

    # Collect all GA4 rows, summing views per path
    raw_by_path: dict = {}
    for row in rp2.rows:
        path   = row.dimension_values[0].value
        title  = row.dimension_values[1].value
        views  = int(row.metric_values[0].value)
        avg_dur = float(row.metric_values[1].value)
        bounce  = float(row.metric_values[2].value)
        if path in raw_by_path:
            raw_by_path[path]["views"] += views
        else:
            raw_by_path[path] = {"url": path, "name": title, "views": views,
                                  "avg_dur": avg_dur, "bounce": bounce}

    # Match GA4 rows back to PAGES_TO_TRACK in the order they are defined,
    # preserving the configured display name and URL even if GA4's page title differs.
    pages = []
    hub_raw = 0
    for page_cfg in PAGES_TO_TRACK:
        matched = next(
            (r for r in raw_by_path.values() if page_cfg["match"] in r["url"]),
            None
        )
        if matched:
            views_int = matched["views"]
            pages.append({
                "name":     page_cfg["name"],
                "url":      page_cfg["url"],
                "views":    fmt(views_int),
                "avg_time": secs_to_mmss(matched["avg_dur"]),
                "bounce":   f"{matched['bounce']*100:.0f}%",
                "share":    0,   # filled in below once we know the max
                "_views_raw": views_int,
            })
            if page_cfg["match"] == CF7_HUB_MATCH:
                hub_raw = views_int
        else:
            # Page exists in config but had no GA4 traffic this period
            pages.append({
                "name":     page_cfg["name"],
                "url":      page_cfg["url"],
                "views":    "0",
                "avg_time": "—",
                "bounce":   "—",
                "share":    0,
                "_views_raw": 0,
            })

    # Calculate share bars relative to the top page
    max_views = max((p["_views_raw"] for p in pages), default=1) or 1
    for p in pages:
        p["share"] = round(p["_views_raw"] / max_views * 100)
        del p["_views_raw"]   # clean up before writing to JSON

    return traffic, pages, hub_raw


# ─────────────────────────────────────────────────────────────────────────────
# WORDPRESS / CF7  (via CF7 Advanced DB plugin — default)
# ─────────────────────────────────────────────────────────────────────────────
def fetch_cf7(hub_views: int = 0):
    """
    Calls the custom REST endpoint added by the WordPress snippet in README.md.
    Endpoint: GET /wp-json/bulls/v1/cf7-stats
    Returns: submissions count, total adults, total children, total people.
    Authentication: WordPress Application Password (Basic Auth).

    The endpoint queries CF7 Advanced DB tables (wp_cf7_submissions +
    wp_cf7_submission_data) by default, with a Flamingo fallback.
    """
    if not WP_BASE_URL or not WP_USERNAME or not WP_APP_PASSWORD:
        print("⚠  WordPress env vars not set – skipping CF7.")
        return {
            "submissions": 0,
            "adults":      0,
            "children":    0,
            "total_people": 0,
            "conversion_rate": "—",
        }

    print("→ Fetching CF7 data (CF7 Advanced DB)…")
    url = f"{WP_BASE_URL}/wp-json/bulls/v1/cf7-stats"
    try:
        resp = requests.get(
            url,
            auth=(WP_USERNAME, WP_APP_PASSWORD),
            timeout=15,
        )
        resp.raise_for_status()
        data       = resp.json()
        submissions = int(data.get("submissions", 0))
        adults      = int(data.get("adults",      0))
        children    = int(data.get("children",    0))
        total_people = adults + children
    except Exception as e:
        print(f"  ✗ CF7 error: {e}")
        return {
            "submissions": 0,
            "adults":      0,
            "children":    0,
            "total_people": 0,
            "conversion_rate": "—",
        }

    rate = f"{submissions / hub_views * 100:.1f}" if hub_views > 0 else "—"
    return {
        "submissions":   submissions,
        "adults":        adults,
        "children":      children,
        "total_people":  total_people,
        "conversion_rate": rate,
    }


# ─────────────────────────────────────────────────────────────────────────────
# YOUTUBE
# ─────────────────────────────────────────────────────────────────────────────
def fetch_youtube():
    if not YOUTUBE_API_KEY or not YOUTUBE_VIDEO_ID:
        print("⚠  YouTube env vars not set – skipping.")
        return {}

    print("→ Fetching YouTube data…")
    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {
        "part":  "snippet,statistics",
        "id":    YOUTUBE_VIDEO_ID,
        "key":   YOUTUBE_API_KEY,
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        items = resp.json().get("items", [])
        if not items:
            print("  ✗ Video not found.")
            return {}
        item    = items[0]
        stats   = item["statistics"]
        snippet = item["snippet"]
        return {
            "title":      snippet.get("title", ""),
            "published":  snippet.get("publishedAt", "")[:10],
            "views":      fmt(int(stats.get("viewCount",    0))),
            "likes":      fmt(int(stats.get("likeCount",    0))),
            "comments":   fmt(int(stats.get("commentCount", 0))),
            "watch_time": "—",   # requires YouTube Analytics API (OAuth)
        }
    except Exception as e:
        print(f"  ✗ YouTube error: {e}")
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# SOCIAL (Instagram + Facebook via Meta Graph API — optional)
# ─────────────────────────────────────────────────────────────────────────────
def fetch_social():
    social = {}

    if META_ACCESS_TOKEN and META_PAGE_ID:
        print("→ Fetching Facebook page insights…")
        try:
            url = f"https://graph.facebook.com/v19.0/{META_PAGE_ID}/insights"
            params = {
                "metric": "page_impressions,page_post_engagements",
                "period": "month",
                "access_token": META_ACCESS_TOKEN,
            }
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            items = {i["name"]: i["values"][-1]["value"] for i in resp.json().get("data", [])}
            impressions = items.get("page_impressions", 0)
            engagements = items.get("page_post_engagements", 0)
            social["facebook"] = {
                "reach": fmt(impressions),
                "eng1":  fmt(engagements),
                "eng2":  "—",
                "manual": False,
            }
        except Exception as e:
            print(f"  ✗ Facebook error: {e}")

    if META_ACCESS_TOKEN and META_IG_USER_ID:
        print("→ Fetching Instagram insights…")
        try:
            url = f"https://graph.facebook.com/v19.0/{META_IG_USER_ID}/insights"
            params = {
                "metric": "impressions,reach",
                "period": "month",
                "access_token": META_ACCESS_TOKEN,
            }
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            items = {i["name"]: i["values"][-1]["value"] for i in resp.json().get("data", [])}
            social["instagram"] = {
                "reach": fmt(items.get("reach", 0)),
                "eng1":  "—",
                "eng2":  "—",
                "manual": False,
            }
        except Exception as e:
            print(f"  ✗ Instagram error: {e}")

    # For platforms without API automation, load from social.json (manual override file)
    try:
        with open("social.json") as f:
            manual = json.load(f)

        # social.json should be: {"instagram": {reach,eng1,eng2,manual}, ...}
        # In case it contains unexpected values, don't blow up the whole script.
        for key, val in manual.items():
            if key in social:
                continue
            if isinstance(val, dict):
                out = dict(val)
                out["manual"] = True
                social[key] = out
            else:
                # Ignore malformed entries
                social[key] = {
                    "reach": str(val),
                    "eng1": "—",
                    "eng2": "—",
                    "manual": True,
                }
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"  ✗ social.json error: {e}")

    return social



# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    result = fetch_ga4()
    if len(result) == 3:
        traffic, pages, hub_raw = result
    else:
        traffic, pages, hub_raw = {}, [], 0

    cf7     = fetch_cf7(hub_views=hub_raw)
    youtube = fetch_youtube()
    social  = fetch_social()

    start_label = datetime.strptime(START_DATE, "%Y-%m-%d").strftime("%-d %b")
    end_label   = NOW.strftime("%-d %b %Y")

    data = {
        "period":  f"{start_label} – {end_label}",
        "updated": NOW.isoformat().replace("+00:00", "Z"),
        "traffic": traffic,
        "pages":   pages,
        "cf7":     cf7,
        "youtube": youtube,
        "social":  social,
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print("\n✓  data.json written successfully.")
    print(json.dumps(data, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
