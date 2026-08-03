"""
Weekly Cybersecurity News Digest Agent (Free version, using Gemini 3.6 Flash)
--------------------------------------------------------------------------------
Pulls the past 7 days of news from official cybersecurity RSS feeds, then
uses Gemini 3.6 Flash (free tier) to summarize them into a clean digest,
and emails it via Gmail SMTP.

Run manually:
    python fetch_cyber_news.py

Environment variables required (set as GitHub Actions secrets, or in a
local .env when testing):
    GEMINI_API_KEY         - free API key from https://aistudio.google.com/apikey
    GMAIL_USER             - the Gmail address sending the email
    GMAIL_APP_PASSWORD     - a Gmail "App Password" (NOT your normal password)
    RECIPIENT_EMAIL        - the email address that should receive the digest

Cost: $0. GitHub Actions free tier covers the scheduled run, RSS feeds are
free/public, Gemini 3.6 Flash is used on Google's free tier, and Gmail SMTP
is free for personal-volume sending.
"""

import os
import smtplib
import sys
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import feedparser
from google import genai

# Official / authoritative cybersecurity RSS feeds.
FEEDS = {
    "CISA Alerts": "https://www.cisa.gov/cybersecurity-advisories/all.xml",
    "NVD Recent CVEs": "https://nvd.nist.gov/feeds/xml/cve/misc/nvd-rss.xml",
    "SANS Internet Storm Center": "https://isc.sans.edu/rssfeed_full.xml",
    "Krebs on Security": "https://krebsonsecurity.com/feed/",
    "The Hacker News": "https://feeds.feedburner.com/TheHackersNews",
    "BleepingComputer": "https://www.bleepingcomputer.com/feed/",
    "Microsoft Security Response Center": "https://msrc.microsoft.com/blog/feed",
}

DAYS_BACK = 7
GEMINI_MODEL = "gemini-3.6-flash"


def parse_entry_date(entry):
    for field in ("published_parsed", "updated_parsed"):
        t = getattr(entry, field, None)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    return None


def collect_raw_items():
    """Fetch recent entries from each RSS feed, grouped by source."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)
    sections = {}

    for source_name, url in FEEDS.items():
        try:
            parsed = feedparser.parse(url)
        except Exception as e:
            print(f"WARNING: failed to fetch {source_name}: {e}", file=sys.stderr)
            continue

        recent_entries = []
        for entry in parsed.entries:
            entry_date = parse_entry_date(entry)
            if entry_date is None or entry_date >= cutoff:
                title = getattr(entry, "title", "(no title)")
                link = getattr(entry, "link", "")
                summary = getattr(entry, "summary", "")
                recent_entries.append({"title": title, "link": link, "summary": summary})

        if recent_entries:
            sections[source_name] = recent_entries[:10]  # cap per source

    return sections


def format_raw_items_for_prompt(sections: dict) -> str:
    lines = []
    for source_name, entries in sections.items():
        lines.append(f"### {source_name}")
        for e in entries:
            snippet = e["summary"][:300].replace("\n", " ") if e["summary"] else ""
            lines.append(f"- TITLE: {e['title']}\n  LINK: {e['link']}\n  SUMMARY: {snippet}")
        lines.append("")
    return "\n".join(lines)


def summarize_with_gemini(client: genai.Client, raw_text: str) -> str:
    today = datetime.now(timezone.utc).strftime("%B %d, %Y")

    prompt = f"""You are a cybersecurity news analyst. Today's date is {today}.

Below is raw RSS feed data collected from official cybersecurity sources
over the past 7 days. Turn it into a concise, well-organized weekly digest.

RAW FEED DATA:
{raw_text}

Produce the digest with this structure:

1. TOP HEADLINES (3-6 most significant stories this week, 1-2 sentences each)
2. CRITICAL VULNERABILITIES / CVEs (any high-severity CVEs mentioned, with CVE ID if present)
3. NOTABLE BREACHES OR ATTACKS (if any appear in the data)
4. WORTH WATCHING (1-2 emerging trends from the data)

Rules:
- Only use information present in the raw feed data above — do not invent details.
- Include the source name after each item (e.g. "via CISA").
- Include the original link for each item you mention.
- Keep it scannable: short bullet points, no fluff.
- Plain text output suitable for an email body — no markdown # headers, use CAPS or dashes for section titles instead.
- If the raw data is empty or has nothing significant, say so plainly.
"""

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
    )

    digest = (response.text or "").strip()
    if not digest:
        raise RuntimeError("No digest text returned from Gemini.")
    return digest


def send_email(digest: str) -> None:
    gmail_user = os.environ["GMAIL_USER"]
    gmail_password = os.environ["GMAIL_APP_PASSWORD"]
    # Supports one or more recipients: comma-separated in the RECIPIENT_EMAIL secret
    # e.g. "person1@gmail.com,person2@gmail.com"
    recipients_raw = os.environ["RECIPIENT_EMAIL"]
    recipients = [r.strip() for r in recipients_raw.split(",") if r.strip()]

    today = datetime.now(timezone.utc).strftime("%B %d, %Y")
    subject = f"Weekly Cybersecurity Digest — {today}"

    msg = MIMEMultipart()
    msg["From"] = gmail_user
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(digest, "plain"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(gmail_user, gmail_password)
        server.sendmail(gmail_user, recipients, msg.as_string())

    print(f"Email sent to {', '.join(recipients)}")


def main():
    gemini_api_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_api_key:
        print("ERROR: GEMINI_API_KEY environment variable not set.", file=sys.stderr)
        sys.exit(1)

    print("Fetching this week's cybersecurity news from RSS feeds...")
    sections = collect_raw_items()

    if not sections:
        digest = "No new items found in the past 7 days across tracked sources."
    else:
        raw_text = format_raw_items_for_prompt(sections)
        print("Summarizing with Gemini 3.6 Flash...")
        client = genai.Client(api_key=gemini_api_key)
        digest = summarize_with_gemini(client, raw_text)

    print("\n--- DIGEST PREVIEW ---\n")
    print(digest)
    print("\n----------------------\n")

    print("Sending email...")
    send_email(digest)


if __name__ == "__main__":
    main()
