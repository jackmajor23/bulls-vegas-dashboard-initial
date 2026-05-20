# Bradford Bulls — Vegas 2027 Campaign Dashboard

Automatically updates every 12 hours via GitHub Actions.
Live data from GA4, WordPress/CF7, and YouTube.

---

## What updates automatically

| Source | What it pulls | API used |
|---|---|---|
| Google Analytics 4 | Page views, sessions, users, avg. duration, per-page breakdown | GA4 Data API (service account) |
| WordPress / CF7 | Total form submissions from /las-vegas-2027/ | Custom WP REST endpoint + Flamingo plugin |
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

### 3 — WordPress — Add the CF7 count endpoint

1. Install the **Flamingo** plugin (free, by Takayuki Miyoshi — the CF7 author). It logs all CF7 submissions.
2. Add the following snippet to your theme's `functions.php` (or a custom plugin):

```php
/**
 * Bradford Bulls — CF7 submission count REST endpoint
 * GET /wp-json/bulls/v1/cf7-count
 * Auth: WordPress Application Password (Basic Auth)
 */
add_action( 'rest_api_init', function () {
    register_rest_route( 'bulls/v1', '/cf7-count', [
        'methods'             => 'GET',
        'callback'            => 'bulls_cf7_submission_count',
        'permission_callback' => function ( $request ) {
            return current_user_can( 'manage_options' );
        },
    ] );
} );

function bulls_cf7_submission_count() {
    global $wpdb;

    // Count Flamingo inbound messages for the Vegas page channel
    $count = $wpdb->get_var(
        $wpdb->prepare(
            "SELECT COUNT(*) FROM {$wpdb->prefix}flamingo_inbound
             WHERE channel LIKE %s",
            '%las-vegas%'
        )
    );

    // Fallback: count ALL Flamingo messages if channel filter returns 0
    if ( ! $count ) {
        $count = $wpdb->get_var(
            "SELECT COUNT(*) FROM {$wpdb->prefix}flamingo_inbound"
        );
    }

    return rest_ensure_response( [
        'count'   => (int) $count,
        'updated' => current_time( 'c' ),
    ] );
}
```

3. Create a WordPress **Application Password**:
   - In WP Admin, go to **Users → Your Profile → Application Passwords**.
   - Add a new one called `Dashboard API`. Copy the password it generates.

---

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
