# Bradford Bulls — Vegas 2027 Campaign Dashboard

Automatically updates every 12 hours via GitHub Actions.
Live data from GA4, WordPress/CF7, and YouTube.

---

## What updates automatically

| Source | What it pulls | API used |
|---|---|---|
| Google Analytics 4 | Page views, sessions, users, avg. duration, per-page breakdown | GA4 Data API (service account) |
| WordPress / CF7 | Submissions count, total adults, total children, total people from /las-vegas-2027/ | Custom WP REST endpoint + **CF7 Advanced DB plugin** (Flamingo fallback) |
| YouTube | Views, likes, comments on the announcement video | YouTube Data API v3 |
| Instagram / Facebook | Reach & engagement (optional) | Meta Graph API (long-lived page token) |

**Social media (X, TikTok, LinkedIn)** — update `social.json` manually; commit and push.

---

## One-time setup (20–30 mins)

### 1 — Create the GitHub repository

1. Create a new repo at github.com (e.g. `bradford-bulls-vegas-dashboard`).
2. Push these files to the `main` branch.
3. Go to **Settings → Pages**, set source to `main` branch, root folder. Save.
4. Your dashboard will be live at `https://<your-org>.github.io/<repo-name>/`.

---

### 2 — Google Analytics 4

You need a **service account** (a bot user) that has read-only access to your GA4 property.

1. Go to [console.cloud.google.com](https://console.cloud.google.com).
2. Create a new project (or use an existing one).
3. Enable the **Google Analytics Data API** (`analyticsdata.googleapis.com`).
4. Go to **IAM & Admin → Service Accounts → Create service account**.
   - Name it something like `bulls-dashboard-reader`.
   - Grant it no project roles (click Continue, then Done).
5. Click the service account → **Keys → Add Key → JSON**. Download the file.
6. Open the JSON file — you'll paste its entire contents as a GitHub Secret in step 5.
7. In **Google Analytics** (analytics.google.com):
   - Go to Admin → Property → Property Access Management.
   - Add the service account email (looks like `xxx@yyy.iam.gserviceaccount.com`) with **Viewer** role.
8. Note your **GA4 Property ID** — it's the number under your property name (e.g. `123456789`). The secret needs the `properties/` prefix: `properties/123456789`.

---

### 3 — WordPress — CF7 Advanced DB (default) + REST endpoint

The dashboard uses **CF7 Advanced DB** as its primary data source. This plugin stores every CF7 submission — including individual field values — in dedicated database tables, so the REST endpoint can sum `adults` and `children` fields across all submissions automatically.

#### 3a — Install CF7 Advanced DB

1. In WP Admin go to **Plugins → Add New** and search for **Contact Form 7 Database Addon – CFDB7** (by Arshid).  
   Alternatively install [CF7 Advanced DB](https://wordpress.org/plugins/cf7-advanced-db/).
2. Activate the plugin. It will immediately start storing new submissions in `wp_cf7_submissions` + `wp_cf7_submission_data`.
3. Make sure your Vegas form fields are named exactly **`adults`** and **`children`** in the CF7 form editor (these are the `name=""` values in the shortcodes, e.g. `[number adults]` and `[number children]`).

#### 3b — Add the custom REST endpoint

Add the following snippet to your theme's `functions.php` (or a custom plugin):

```php
/**
 * Bradford Bulls — CF7 Advanced DB stats REST endpoint
 * GET /wp-json/bulls/v1/cf7-stats
 * Returns: submissions count, total adults, total children, total people
 * Auth: WordPress Application Password (Basic Auth)
 */
add_action( 'rest_api_init', function () {
    register_rest_route( 'bulls/v1', '/cf7-stats', [
        'methods'             => 'GET',
        'callback'            => 'bulls_cf7_advanced_db_stats',
        'permission_callback' => function () {
            return current_user_can( 'manage_options' );
        },
    ] );
} );

function bulls_cf7_advanced_db_stats() {
    global $wpdb;

    // ── Try CF7 Advanced DB tables first (default) ──────────────────────────
    $submissions_table = $wpdb->prefix . 'cf7_submissions';
    $data_table        = $wpdb->prefix . 'cf7_submission_data';

    $advanced_db_exists = $wpdb->get_var(
        $wpdb->prepare( "SHOW TABLES LIKE %s", $submissions_table )
    );

    if ( $advanced_db_exists ) {
        // Count submissions for the Vegas form (filter by form title or post ID)
        $submissions = (int) $wpdb->get_var(
            "SELECT COUNT(*) FROM {$submissions_table}
             WHERE form_title LIKE '%Vegas%' OR form_title LIKE '%Las Vegas%'"
        );

        // Fallback: count ALL submissions if Vegas filter returns 0
        if ( ! $submissions ) {
            $submissions = (int) $wpdb->get_var(
                "SELECT COUNT(*) FROM {$submissions_table}"
            );
        }

        // Sum adults field values
        $adults = (int) $wpdb->get_var(
            $wpdb->prepare(
                "SELECT COALESCE(SUM(CAST(d.value AS UNSIGNED)), 0)
                 FROM {$data_table} d
                 WHERE d.field_name = %s",
                'adults'
            )
        );

        // Sum children field values
        $children = (int) $wpdb->get_var(
            $wpdb->prepare(
                "SELECT COALESCE(SUM(CAST(d.value AS UNSIGNED)), 0)
                 FROM {$data_table} d
                 WHERE d.field_name = %s",
                'children'
            )
        );

        return rest_ensure_response( [
            'source'       => 'cf7_advanced_db',
            'submissions'  => $submissions,
            'adults'       => $adults,
            'children'     => $children,
            'total_people' => $adults + $children,
            'updated'      => current_time( 'c' ),
        ] );
    }

    // ── Fallback: Flamingo plugin ────────────────────────────────────────────
    $flamingo_table = $wpdb->prefix . 'flamingo_inbound';
    $flamingo_exists = $wpdb->get_var(
        $wpdb->prepare( "SHOW TABLES LIKE %s", $flamingo_table )
    );

    if ( $flamingo_exists ) {
        $count = (int) $wpdb->get_var(
            $wpdb->prepare(
                "SELECT COUNT(*) FROM {$flamingo_table} WHERE channel LIKE %s",
                '%las-vegas%'
            )
        );
        if ( ! $count ) {
            $count = (int) $wpdb->get_var( "SELECT COUNT(*) FROM {$flamingo_table}" );
        }
        return rest_ensure_response( [
            'source'       => 'flamingo_fallback',
            'submissions'  => $count,
            'adults'       => 0,
            'children'     => 0,
            'total_people' => 0,
            'updated'      => current_time( 'c' ),
        ] );
    }

    return new WP_Error( 'no_cf7_store', 'No CF7 storage plugin found.', [ 'status' => 404 ] );
}
```

#### 3c — Create a WordPress Application Password

1. In WP Admin go to **Users → Your Profile → Application Passwords**.
2. Add a new one called `Dashboard API`. Copy the generated password.



### 4 — YouTube Data API

1. At [console.cloud.google.com](https://console.cloud.google.com), in the same project as step 2.
2. Enable the **YouTube Data API v3**.
3. Go to **APIs & Services → Credentials → Create Credentials → API Key**.
4. Copy the key.
5. Find your video ID — it's the part after `v=` in the YouTube URL: `https://youtube.com/watch?v=`**`dQw4w9WgXcQ`**.

---

### 5 — Add GitHub Secrets

Go to your repository → **Settings → Secrets and variables → Actions → New repository secret**.

Add each of these:

| Secret name | Value |
|---|---|
| `GA4_PROPERTY_ID` | `properties/123456789` (your property ID with prefix) |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | The entire contents of the service account JSON file |
| `YOUTUBE_API_KEY` | Your YouTube Data API v3 key |
| `YOUTUBE_VIDEO_ID` | e.g. `dQw4w9WgXcQ` |
| `WP_BASE_URL` | `https://bradfordbulls.co.uk` |
| `WP_USERNAME` | Your WordPress username |
| `WP_APP_PASSWORD` | The Application Password from step 3 |

**Optional — Meta (Instagram + Facebook):**

| Secret name | Value |
|---|---|
| `META_ACCESS_TOKEN` | Long-lived Page Access Token (from Meta Business Suite → Settings → Advanced) |
| `META_PAGE_ID` | Your Facebook Page numeric ID |
| `META_IG_USER_ID` | Instagram Business Account ID (found in Meta Business Suite) |

---

### 6 — Trigger the first run

1. Go to **Actions → Update Dashboard Data → Run workflow**.
2. Check the run log — it should show data being fetched and committed.
3. Visit your GitHub Pages URL — the dashboard will now show live numbers.

After this, it refreshes automatically at 07:00 and 19:00 UTC every day.

---

## Entering interim data (before automation is live)

Until GitHub Actions is fully configured, you can populate the dashboard manually by editing the `manual_override` block in `data.json`. Set `"enabled": true` to activate it — these values take priority over the auto-fetched fields.

```json
"manual_override": {
  "enabled": true,
  "period":  "1 Jan – 20 May 2025",
  "updated": "20 May 2025",
  "traffic": {
    "pageviews": "14.8K",
    "sessions":  "9.2K",
    "users":     "7.8K",
    "avg_time":  "2:34"
  },
  "pages": [
    { "name": "Las Vegas 2027 Hub",  "url": "/las-vegas-2027/",                          "views": 8200, "sessions": 5100, "time": "3:10" },
    { "name": "CEO Statement",       "url": "/news/ceo-jason-hirst-issues-statement/",   "views": 4100, "sessions": 2800, "time": "1:55" },
    { "name": "We're Heading to Vegas", "url": "/news/were-heading-to-vegas/",           "views": 2523, "sessions": 1700, "time": "1:40" }
  ],
  "cf7": {
    "submissions":  412,
    "adults":       680,
    "children":     290,
    "total_people": 970
  },
  "youtube": {
    "title":      "Bradford Bulls are heading to Las Vegas! 🎰",
    "published":  "15 Jan 2025",
    "views":      "52.3K",
    "likes":      "1.8K",
    "comments":   "234",
    "watch_time": "1,240 hrs"
  }
}
```

Set `"enabled": false` once automation is running — the dashboard will then use live data from GitHub Actions.

---

## Updating social media figures manually

Edit `social.json` and commit it to `main`. The dashboard reads it on every page load.

```json
{
  "instagram": { "reach": "45.2K", "eng1": "2.1K", "eng2": "312", "manual": true },
  "x":         { "reach": "18.9K", "eng1": "980",  "eng2": "241", "manual": true }
}
```

For Instagram and Facebook you can also add `META_ACCESS_TOKEN` / `META_PAGE_ID` / `META_IG_USER_ID` secrets and the script will pull those automatically too.

---

## File structure

```
/
├── index.html                  ← Dashboard (reads data.json)
├── data.json                   ← Auto-generated by GitHub Actions
├── social.json                 ← Manual social media overrides
├── scripts/
│   └── fetch_data.py           ← Data fetcher (GA4, CF7, YouTube, Meta)
└── .github/
    └── workflows/
        └── update-data.yml     ← Scheduled automation
```
