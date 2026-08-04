"""
Weekly Cyber & AI Digest Agent (Free, Gemini 3.6 Flash, styled HTML email)
------------------------------------------------------------------------------
Pulls the past 7 days of news from official cybersecurity AND AI industry
RSS feeds, uses Gemini 3.6 Flash to write a newspaper-style summary for
each category plus a "Worth Watching" section, and emails a styled HTML
digest via Gmail SMTP.

Run manually:
    python fetch_cyber_news.py

Environment variables required (GitHub Actions secrets, or local .env):
    GEMINI_API_KEY         - free key from https://aistudio.google.com/apikey
    GMAIL_USER             - the Gmail address sending the email
    GMAIL_APP_PASSWORD     - a Gmail "App Password" (NOT your normal password)
    RECIPIENT_EMAIL        - one or more emails, comma-separated

Cost: $0 (GitHub Actions free tier, free RSS feeds, Gemini free tier, Gmail SMTP).
"""

import html
import json
import os
import re
import smtplib
import sys
import time
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import feedparser
from google import genai
from google.genai import errors as genai_errors

# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

CYBERSECURITY_FEEDS = {
    "CISA Alerts": "https://www.cisa.gov/cybersecurity-advisories/all.xml",
    "SANS Internet Storm Center": "https://isc.sans.edu/rssfeed_full.xml",
    "Krebs on Security": "https://krebsonsecurity.com/feed/",
    "The Hacker News": "https://feeds.feedburner.com/TheHackersNews",
    "BleepingComputer": "https://www.bleepingcomputer.com/feed/",
    "Microsoft Security Response Center": "https://msrc.microsoft.com/blog/feed",
}

AI_FEEDS = {
    "OpenAI Blog": "https://openai.com/blog/rss.xml",
    "Anthropic News": "https://www.anthropic.com/news/rss.xml",
    "Google DeepMind Blog": "https://deepmind.google/discover/blog/rss.xml",
    "Google AI Blog": "https://blog.google/technology/ai/rss/",
    "MIT Technology Review - AI": "https://www.technologyreview.com/topic/artificial-intelligence/feed",
}

DAYS_BACK = 7
GEMINI_MODEL = "gemini-3.6-flash"
ITEMS_PER_SOURCE_CAP = 15


# ---------------------------------------------------------------------------
# RSS collection
# ---------------------------------------------------------------------------

def parse_entry_date(entry):
    for field in ("published_parsed", "updated_parsed"):
        t = getattr(entry, field, None)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    return None


def collect_raw_items(feeds: dict) -> dict:
    """Fetch recent entries from each RSS feed in `feeds`, grouped by source."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)
    sections = {}

    for source_name, url in feeds.items():
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
            sections[source_name] = recent_entries[:ITEMS_PER_SOURCE_CAP]

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


def format_digest_from_sections(sections: dict) -> str:
    """Plain-text fallback with no AI involved."""
    lines = []
    for source_name, entries in sections.items():
        lines.append(f"--- {source_name} ---")
        for e in entries:
            lines.append(f"* {e['title']}")
            if e["link"]:
                lines.append(f"  {e['link']}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Gemini summarization -> structured JSON
# ---------------------------------------------------------------------------

def build_prompt(cyber_raw: str, ai_raw: str) -> str:
    today = datetime.now(timezone.utc).strftime("%B %d, %Y")
    return f"""You are the editor of a weekly newspaper-style digest covering
cybersecurity and artificial intelligence industry news. Today's date is {today}.

Below is raw RSS feed data from official sources, split into two groups.

CYBERSECURITY SOURCES:
{cyber_raw if cyber_raw else "(no items this week)"}

AI INDUSTRY SOURCES:
{ai_raw if ai_raw else "(no items this week)"}

Write the digest in a newspaper editorial tone — measured, factual, no hype,
no marketing language. Do NOT include a vulnerabilities/CVE list and do NOT
include a separate "breaches" list — fold anything vulnerability- or
breach-related naturally into the relevant headline items instead if it's
genuinely one of the week's top stories.

Return ONLY valid JSON (no markdown fences, no commentary) matching exactly
this shape:

{{
  "cybersecurity": [
    {{
      "headline": "Short newspaper-style headline",
      "body": "2-4 sentence newspaper-style summary of the story, factual and neutral.",
      "insight": "One sentence of editorial context or why it matters, written like a pull-quote.",
      "source": "Source name",
      "link": "URL"
    }}
  ],
  "ai": [
    {{
      "headline": "...",
      "body": "...",
      "insight": "...",
      "source": "...",
      "link": "..."
    }}
  ],
  "watch": [
    "One sentence each on a trend worth watching next week, across either category."
  ]
}}

Rules:
- 5-8 items in "cybersecurity", 5-8 items in "ai", based only on what's in the raw data above. Include every genuinely distinct story available, even minor ones, rather than trimming to a short list.
- 3-5 items in "watch".
- Only use information present in the raw data — never invent facts, links, or figures.
- If a category has no real news this week, return an empty list for it rather than inventing filler.
- Keep headlines under 12 words.
- Keep "body" to 2-4 sentences, "insight" to 1 sentence.
"""


def extract_json(text: str) -> dict:
    """Strip markdown code fences if present, then parse JSON."""
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned)


def summarize_with_gemini(client: genai.Client, cyber_raw: str, ai_raw: str) -> dict:
    prompt = build_prompt(cyber_raw, ai_raw)

    max_attempts = 4
    base_delay_seconds = 15  # 15s, 30s, 60s between retries
    last_error = None

    for attempt in range(1, max_attempts + 1):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
            )
            raw_text = (response.text or "").strip()
            if not raw_text:
                raise RuntimeError("No text returned from Gemini.")
            return extract_json(raw_text)

        except genai_errors.ServerError as e:
            last_error = e
            if attempt == max_attempts:
                break
            delay = base_delay_seconds * (2 ** (attempt - 1))
            print(
                f"Gemini server error (attempt {attempt}/{max_attempts}): {e}. Retrying in {delay}s...",
                file=sys.stderr,
            )
            time.sleep(delay)
        except json.JSONDecodeError as e:
            last_error = e
            if attempt == max_attempts:
                break
            print(f"Gemini returned invalid JSON (attempt {attempt}/{max_attempts}): {e}. Retrying...", file=sys.stderr)
            time.sleep(5)

    raise RuntimeError(f"Gemini failed after {max_attempts} attempts: {last_error}")


# ---------------------------------------------------------------------------
# HTML digest rendering
# ---------------------------------------------------------------------------

SLATE = "#1f2933"
ACCENT = "#0f9b8e"
CYBER_COLOR = "#0e7490"   # deep teal/cyan for cybersecurity
AI_COLOR = "#4338ca"      # indigo/violet for AI
WATCH_COLOR = "#b45309"   # amber for the watch section
LIGHT_BG = "#eef1f3"
TEXT_DARK = "#1a1a1a"
TEXT_MUTED = "#5a5a5a"


def esc(text: str) -> str:
    return html.escape(text or "", quote=False)


def render_items_column(items: list, accent_color: str) -> str:
    blocks = []
    for item in items:
        headline = esc(item.get("headline", ""))
        body = esc(item.get("body", ""))
        insight = esc(item.get("insight", ""))
        source = esc(item.get("source", ""))
        link = item.get("link", "") or "#"

        blocks.append(f"""
        <div style="margin-bottom:22px;">
          <a href="{html.escape(link, quote=True)}" style="color:{SLATE};text-decoration:none;">
            <div style="font-size:16px;font-weight:700;color:{SLATE};margin-bottom:7px;line-height:1.3;">{headline}</div>
          </a>
          <div style="font-size:14px;color:{TEXT_DARK};line-height:1.55;margin-bottom:9px;">{body}</div>
          <div style="border-left:3px solid {accent_color};padding-left:10px;font-size:13px;font-style:italic;color:{TEXT_MUTED};margin-bottom:8px;">
            {insight}
          </div>
          <span style="display:inline-block;background-color:{accent_color};color:#ffffff;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;padding:3px 9px;border-radius:10px;">{source}</span>
        </div>
        """)
    if not blocks:
        return f'<div style="font-size:13px;color:{TEXT_MUTED};font-style:italic;">No significant stories this week.</div>'
    return "\n".join(blocks)


def render_watch_section(watch_items: list) -> str:
    if not watch_items:
        return ""
    rows = "\n".join(
        f'<li style="margin-bottom:9px;font-size:14px;color:{TEXT_DARK};line-height:1.5;">{esc(w)}</li>'
        for w in watch_items
    )
    return f"""
    <tr>
      <td colspan="2" style="padding:26px 24px 10px 24px;">
        <div style="border-top:2px solid {WATCH_COLOR};padding-top:14px;margin-bottom:14px;">
          <span style="color:{WATCH_COLOR};font-size:15px;font-weight:800;text-transform:uppercase;letter-spacing:0.8px;">&#9733; Worth Watching</span>
        </div>
        <ul style="padding-left:18px;margin:0;">
          {rows}
        </ul>
      </td>
    </tr>
    """


def build_html_digest(data: dict, issue_number: int, date_str: str) -> str:
    cyber_html = render_items_column(data.get("cybersecurity", []), CYBER_COLOR)
    ai_html = render_items_column(data.get("ai", []), AI_COLOR)
    watch_html = render_watch_section(data.get("watch", []))

    return f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background-color:{LIGHT_BG};font-family:Georgia,'Times New Roman',serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:{LIGHT_BG};padding:24px 0;">
    <tr>
      <td align="center">
        <table role="presentation" width="640" cellpadding="0" cellspacing="0" style="background-color:#ffffff;max-width:640px;">

          <tr>
            <td style="padding:0;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td width="50%" style="height:5px;background-color:{CYBER_COLOR};font-size:0;line-height:0;">&nbsp;</td>
                  <td width="50%" style="height:5px;background-color:{AI_COLOR};font-size:0;line-height:0;">&nbsp;</td>
                </tr>
              </table>
            </td>
          </tr>

          <tr>
            <td style="padding:26px 24px 18px 24px;text-align:center;border-bottom:4px solid {SLATE};">
              <div style="font-size:11px;letter-spacing:2px;color:{ACCENT};text-transform:uppercase;font-weight:700;margin-bottom:6px;">The Weekly Signal</div>
              <div style="font-size:30px;font-weight:900;color:{SLATE};font-family:Georgia,'Times New Roman',serif;">Cyber &amp; AI Digest</div>
              <div style="font-size:12px;color:{TEXT_MUTED};margin-top:8px;">Issue No. {issue_number} &nbsp;&middot;&nbsp; {date_str}</div>
            </td>
          </tr>

          <tr>
            <td style="padding:20px 24px 0 24px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td width="50%" style="vertical-align:top;padding-right:16px;">
                    <div style="border-bottom:2px solid {CYBER_COLOR};padding-bottom:8px;margin-bottom:16px;">
                      <span style="color:{CYBER_COLOR};font-size:14px;font-weight:800;text-transform:uppercase;letter-spacing:0.8px;">&#128274; Cybersecurity</span>
                    </div>
                    {cyber_html}
                  </td>
                  <td width="50%" style="vertical-align:top;padding-left:16px;border-left:1px solid #d8dcdf;">
                    <div style="border-bottom:2px solid {AI_COLOR};padding-bottom:8px;margin-bottom:16px;">
                      <span style="color:{AI_COLOR};font-size:14px;font-weight:800;text-transform:uppercase;letter-spacing:0.8px;">&#129302; Artificial Intelligence</span>
                    </div>
                    {ai_html}
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
            {watch_html}
          </table>

          <tr>
            <td style="padding:20px 24px;text-align:center;color:#9a9a9a;font-size:11px;border-top:1px solid #e0e0e0;">
              Compiled from official cybersecurity and AI industry sources. Automated weekly digest.
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def build_plain_text_fallback(data_or_sections, is_raw_fallback: bool) -> str:
    """Plain-text alternative body (for email clients that don't render HTML),
    or the raw-feed fallback if Gemini failed entirely."""
    if is_raw_fallback:
        return data_or_sections  # already a formatted string in this case

    lines = ["WEEKLY CYBER & AI DIGEST", "=" * 40, "", "CYBERSECURITY", "-" * 20]
    for item in data_or_sections.get("cybersecurity", []):
        lines.append(f"* {item.get('headline','')}")
        lines.append(f"  {item.get('body','')}")
        lines.append(f"  -> {item.get('insight','')}")
        lines.append("")
    lines += ["ARTIFICIAL INTELLIGENCE", "-" * 20]
    for item in data_or_sections.get("ai", []):
        lines.append(f"* {item.get('headline','')}")
        lines.append(f"  {item.get('body','')}")
        lines.append(f"  -> {item.get('insight','')}")
        lines.append("")
    watch = data_or_sections.get("watch", [])
    if watch:
        lines += ["WORTH WATCHING", "-" * 20]
        for w in watch:
            lines.append(f"* {w}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Email sending
# ---------------------------------------------------------------------------

def send_email(subject: str, html_body: str, plain_body: str) -> None:
    gmail_user = os.environ["GMAIL_USER"]
    gmail_password = os.environ["GMAIL_APP_PASSWORD"]
    recipients_raw = os.environ["RECIPIENT_EMAIL"]
    recipients = [r.strip() for r in recipients_raw.split(",") if r.strip()]

    msg = MIMEMultipart("alternative")
    msg["From"] = gmail_user
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(plain_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(gmail_user, gmail_password)
        server.sendmail(gmail_user, recipients, msg.as_string())

    print(f"Email sent to {', '.join(recipients)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    gemini_api_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_api_key:
        print("ERROR: GEMINI_API_KEY environment variable not set.", file=sys.stderr)
        sys.exit(1)

    now = datetime.now(timezone.utc)
    date_str = now.strftime("%B %d, %Y")
    issue_number = now.isocalendar()[1]  # ISO week number of the year

    print("Fetching this week's cybersecurity news from RSS feeds...")
    cyber_sections = collect_raw_items(CYBERSECURITY_FEEDS)
    print("Fetching this week's AI industry news from RSS feeds...")
    ai_sections = collect_raw_items(AI_FEEDS)

    subject = f"Weekly Cyber & AI Digest — Issue #{issue_number} | {date_str}"

    if not cyber_sections and not ai_sections:
        html_body = build_html_digest({"cybersecurity": [], "ai": [], "watch": []}, issue_number, date_str)
        plain_body = "No new items found in the past 7 days across tracked sources."
        send_email(subject, html_body, plain_body)
        return

    cyber_raw = format_raw_items_for_prompt(cyber_sections)
    ai_raw = format_raw_items_for_prompt(ai_sections)

    client = genai.Client(api_key=gemini_api_key)
    print("Summarizing with Gemini 3.6 Flash...")

    try:
        data = summarize_with_gemini(client, cyber_raw, ai_raw)
        html_body = build_html_digest(data, issue_number, date_str)
        plain_body = build_plain_text_fallback(data, is_raw_fallback=False)
    except Exception as e:
        print(f"WARNING: Gemini summarization failed, falling back to raw digest: {e}", file=sys.stderr)
        combined_sections = {**cyber_sections, **ai_sections}
        raw_text = (
            "NOTE: AI summarization was unavailable this week (Gemini error), "
            "so this is the raw feed digest instead.\n\n"
            + format_digest_from_sections(combined_sections)
        )
        # Minimal plain HTML wrapper for the fallback case
        html_body = f"<html><body><pre style='font-family:monospace;white-space:pre-wrap;'>{esc(raw_text)}</pre></body></html>"
        plain_body = raw_text

    print("\n--- DIGEST PREVIEW (plain text) ---\n")
    print(plain_body)
    print("\n------------------------------------\n")

    print("Sending email...")
    send_email(subject, html_body, plain_body)


if __name__ == "__main__":
    main()
