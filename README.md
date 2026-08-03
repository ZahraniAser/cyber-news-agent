# Weekly Cybersecurity Digest Agent (Free, powered by Gemini 3.6 Flash)

Pulls the past week's cybersecurity news, advisories, and CVEs from official
RSS feeds (CISA, NVD, MSRC, SANS ISC, Krebs, The Hacker News,
BleepingComputer), summarizes them into a clean digest using **Gemini 3.6
Flash** (Google's latest model, free tier), and emails it to one recipient
every Monday via GitHub Actions. No server needed.

## Why this is free
- **GitHub Actions**: free tier covers a weekly run easily (private repos
  get 2,000 free minutes/month; this job takes under a minute).
- **RSS feeds**: public and official, no API key or cost.
- **Gemini 3.6 Flash**: used via Google's free tier through AI Studio.
  Free tier is subject to rate limits (requests/day), but a single weekly
  summarization call is nowhere near those limits.
- **Gmail SMTP**: free for personal-volume sending.

## Setup (10 minutes)

### 1. Create a new GitHub repo
Create a new **private** repo (recommended, since it'll hold secrets) and
push these files:

```
git init
git add .
git commit -m "Weekly cyber news agent"
git branch -M main
git remote add origin https://github.com/<your-username>/<repo-name>.git
git push -u origin main
```

### 2. Get a free Gemini API key
Go to [aistudio.google.com/apikey](https://aistudio.google.com/apikey),
sign in with a Google account, and create a free API key. No billing
required for free-tier usage.

### 3. Create a Gmail App Password
1. Go to your Google Account → Security → 2-Step Verification (must be enabled)
2. Search "App Passwords" in your Google Account settings
3. Generate one for "Mail" — copy the 16-character password

### 4. Add repo secrets
In your GitHub repo: **Settings → Secrets and variables → Actions → New repository secret**.
Add these four:

| Secret name | Value |
|---|---|
| `GEMINI_API_KEY` | your free Gemini API key from step 2 |
| `GMAIL_USER` | the Gmail address sending the digest |
| `GMAIL_APP_PASSWORD` | the 16-character app password from step 3 |
| `RECIPIENT_EMAIL` | the email address that should receive the digest |

### 5. Test it manually
Go to the **Actions** tab in your repo → "Weekly Cybersecurity Digest" →
**Run workflow**. Check the recipient inbox after a minute or two.

### 6. Let it run
Scheduled for every Monday at 06:00 UTC (~09:00 Riyadh time). Edit the
`cron` line in `.github/workflows/weekly-cyber-news.yml` for a different
day/time (use [crontab.guru](https://crontab.guru) to build one).

## Customizing

- **Add/remove sources**: edit the `FEEDS` dict in `fetch_cyber_news.py`.
- **Change lookback window**: edit `DAYS_BACK` (default 7).
- **Items per source**: edit the `[:10]` cap in `collect_raw_items()`.
- **Digest style/sections**: edit the prompt inside `summarize_with_gemini()`.
- **Multiple recipients**: pass a comma-separated string to `sendmail()`.

## Local testing (optional)

```bash
pip install -r requirements.txt
export GEMINI_API_KEY="your-key"
export GMAIL_USER="you@gmail.com"
export GMAIL_APP_PASSWORD="xxxx xxxx xxxx xxxx"
export RECIPIENT_EMAIL="recipient@example.com"
python fetch_cyber_news.py
```

## Notes
- Gemini's free tier has daily request limits that can change — check
  [ai.google.dev/gemini-api/docs/rate-limits](https://ai.google.dev/gemini-api/docs/rate-limits)
  if you ever see quota errors. One run/week is far below typical free-tier caps.
- If an RSS feed URL changes or breaks, the script skips it and logs a
  warning rather than failing the whole run.
