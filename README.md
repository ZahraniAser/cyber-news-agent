Weekly Cyber & AI Digest Agent (Free, powered by Gemini 3.6 Flash)

Pulls the past week's news from official cybersecurity AND AI industry RSS feeds, uses Gemini 3.6 Flash (Google's latest model, free tier) to write a newspaper-style summary split into two sections — Cybersecurity and Artificial Intelligence — plus a "Worth Watching" section, and emails a styled HTML digest to one or more recipients every Monday. No server needed, no CVE/breach lists, no ongoing cost.

What the digest looks like
A newspaper-style masthead header with issue number and date
Two columns: Cybersecurity (teal accent) and Artificial Intelligence (indigo accent), each with 5-8 stories
Each story: headline, 2-4 sentence newspaper-style summary, a one-line editorial "insight," and a colored source tag
A Worth Watching section (amber accent) with 3-5 forward-looking notes
Sent as a proper HTML email (with a plain-text fallback for clients that need it)
Why this is free
GitHub Actions: free tier covers a weekly run easily (private repos get 2,000 free minutes/month; this job takes under a minute).
RSS feeds: public and official, no API key or cost.
Gemini 3.6 Flash: used via Google's free tier through AI Studio. Free tier is subject to rate limits (requests/day), but a single weekly summarization call is nowhere near those limits.
Gmail SMTP: free for personal-volume sending.
cron-job.org (optional, see below): also entirely free.
Sources

Cybersecurity: CISA Alerts, SANS Internet Storm Center, Krebs on Security, The Hacker News, BleepingComputer, Microsoft Security Response Center.

AI: OpenAI Blog, Anthropic News, Google DeepMind Blog, Google AI Blog, MIT Technology Review (AI section).

Edit CYBERSECURITY_FEEDS and AI_FEEDS in fetch_cyber_news.py to add/remove sources — any site with an RSS/Atom feed works.

Setup (10 minutes)
1. Create a new GitHub repo

Create a new private repo (recommended, since it'll hold secrets) and push these files, keeping the folder structure intact (the workflow file must stay under .github/workflows/):

git init
git add .
git commit -m "Weekly cyber & AI digest agent"
git branch -M main
git remote add origin https://github.com/<your-username>/<repo-name>.git
git push -u origin main
2. Get a free Gemini API key

Go to aistudio.google.com/apikey, sign in with a Google account, and create a free API key. No billing required for free-tier usage.

3. Create a Gmail App Password

Use a dedicated Gmail account for sending (recommended, keeps your personal account's app password out of it):

Go to that account's Google Account → Security → 2-Step Verification (must be enabled first)
Search "App Passwords" in Google Account settings
Generate one for "Mail" — copy the 16-character password immediately (shown once)
4. Add repo secrets

In your GitHub repo: Settings → Secrets and variables → Actions → New repository secret. Add these four:

Secret name	Value
GEMINI_API_KEY	your free Gemini API key from step 2
GMAIL_USER	the dedicated Gmail address sending the digest
GMAIL_APP_PASSWORD	the 16-character app password from step 3
RECIPIENT_EMAIL	one or more emails, comma-separated (e.g. a@gmail.com,b@gmail.com)
5. Test it manually

Go to the Actions tab in your repo → "Weekly Cybersecurity Digest" → Run workflow. Check the recipient inbox(es) after about a minute.

6. Let it run

The workflow includes GitHub's own schedule: trigger, set for every Monday at 06:00 UTC (~09:00 Riyadh time). Edit the cron line in .github/workflows/weekly-cyber-news.yml for a different day/time (use crontab.guru to build one).

Known limitation: GitHub's own scheduler is not precise — runs can be delayed anywhere from a few minutes to a couple of hours during high load, since scheduled workflows are deprioritized behind paid usage. For a weekly digest this is low-stakes, but if exact timing matters to you, see the optional precision-scheduling setup below.

Optional: precise scheduling with cron-job.org

Since GitHub's built-in scheduler can run late, this workflow also accepts an external trigger via repository_dispatch. Pairing it with cron-job.org (free, fires to the minute) gives much more reliable timing.

1. Create a fine-grained GitHub Personal Access Token

github.com/settings/tokens → Fine-grained tokens → Generate new token

Repository access: Only select repositories → this repo
Permissions → Repository permissions → Contents: Read and write (Metadata: Read-only gets added automatically — that's normal)
Copy the token immediately (github_pat_...) — shown once
2. Create a free cron-job.org account and job
URL: https://api.github.com/repos/<your-username>/<repo-name>/dispatches
Method: POST
Headers:
Authorization: Bearer YOUR_TOKEN_HERE
Accept: application/vnd.github+json
Content-Type: application/json
Body: {"event_type": "send-digest"}
Schedule: custom crontab expression, e.g. 0 6 * * 1 for every Monday 06:00 UTC (times shown in the job's individual timezone, which defaults to UTC)

Use cron-job.org's Test Run button to fire it immediately and confirm it works — check the Actions tab for a run triggered by repository_dispatch rather than schedule.

With both triggers active, GitHub's own schedule acts as a backup in case cron-job.org ever has an outage.

Customizing
Add/remove sources: edit CYBERSECURITY_FEEDS / AI_FEEDS in fetch_cyber_news.py.
Change lookback window: edit DAYS_BACK (default 7).
Items per source fetched from RSS: edit ITEMS_PER_SOURCE_CAP.
Number of stories per category in the digest: edit the "Rules" section of the prompt inside build_prompt().
Colors / layout: edit the SLATE, CYBER_COLOR, AI_COLOR, WATCH_COLOR constants and the HTML in build_html_digest().
Multiple recipients: already supported — comma-separate them in the RECIPIENT_EMAIL secret.
Digest tone/structure: edit the prompt inside build_prompt().
Reliability features
Gemini retries: if Gemini returns a server error (e.g. temporary overload), the script retries up to 4 times with exponential backoff (15s, 30s, 60s) before giving up.
Fallback digest: if Gemini is still unavailable after all retries, the script doesn't fail silently — it emails a plain raw-feed digest instead (clearly labeled as a fallback), so you never miss a week.
Per-feed failure isolation: if one RSS feed is down or its URL has changed, that source is skipped with a logged warning; the rest of the run continues normally.
Local testing (optional)
bash
pip install -r requirements.txt
export GEMINI_API_KEY="your-key"
export GMAIL_USER="you@gmail.com"
export GMAIL_APP_PASSWORD="xxxx xxxx xxxx xxxx"
export RECIPIENT_EMAIL="recipient@example.com"
python fetch_cyber_news.py
Notes
Gemini's free tier has daily request limits that can change — check ai.google.dev/gemini-api/docs/rate-limits if you ever see quota errors. One run/week is far below typical free-tier caps.
The GitHub Personal Access Token used for cron-job.org is scoped to this one repo with Contents: Read/write only — if you set it to "No expiration," you can revoke or regenerate it anytime from github.com/settings/tokens.
