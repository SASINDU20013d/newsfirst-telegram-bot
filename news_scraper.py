import os
import sys
import json
import hashlib
import datetime as dt
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://english.newsfirst.lk"
RETENTION_DAYS = 7  # Keep track of articles sent in last 7 days
SENT_ARTICLES_FILE = Path(__file__).parent / "sent_articles.json"


def get_target_date(date_arg: str | None = None) -> dt.date:
    if date_arg:
        try:
            return dt.datetime.strptime(date_arg, "%Y-%m-%d").date()
        except ValueError as exc:
            raise SystemExit(f"Invalid date format: {date_arg!r}. Use YYYY-MM-DD.") from exc
    return dt.date.today()


def build_archive_url(target_date: dt.date) -> str:
    return f"{BASE_URL}/{target_date.year}/{target_date.month:02d}/{target_date.day:02d}"


def generate_content_hash(title: str, content: str) -> str:
    """Generate SHA-256 hash from article title + first 500 characters of content."""
    # Use title + first 500 characters of content for fingerprinting
    fingerprint = title + content[:500]
    return hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:16]


def load_sent_articles() -> dict:
    """Load tracking data from sent_articles.json."""
    if not SENT_ARTICLES_FILE.exists():
        return {"articles": {}, "last_updated": ""}
    
    try:
        with open(SENT_ARTICLES_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"articles": {}, "last_updated": ""}


def cleanup_old_articles(sent_data: dict) -> dict:
    """Remove articles older than RETENTION_DAYS."""
    cutoff_date = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=RETENTION_DAYS)
    
    cleaned_articles = {}
    for url, metadata in sent_data.get("articles", {}).items():
        try:
            sent_timestamp = dt.datetime.fromisoformat(metadata.get("sent_timestamp", ""))
            if sent_timestamp >= cutoff_date:
                cleaned_articles[url] = metadata
        except (ValueError, TypeError):
            # Keep articles with invalid timestamps to be safe
            cleaned_articles[url] = metadata
    
    return {
        "articles": cleaned_articles,
        "last_updated": sent_data.get("last_updated", "")
    }


def is_article_sent(url: str, content_hash: str, sent_data: dict) -> tuple[bool, str]:
    """
    Check if article was already sent using dual detection.
    Returns (is_sent, reason) tuple.
    """
    articles = sent_data.get("articles", {})
    
    # Check by URL (exact match)
    if url in articles:
        metadata = articles[url]
        sent_date = metadata.get("sent_date", "unknown")
        sent_time = metadata.get("sent_time", "unknown")
        return True, f"URL already sent on {sent_date} at {sent_time}"
    
    # Check by content hash (catches content duplicates with different URLs)
    for existing_url, metadata in articles.items():
        if metadata.get("content_hash") == content_hash:
            sent_date = metadata.get("sent_date", "unknown")
            sent_time = metadata.get("sent_time", "unknown")
            return True, f"Same content already sent on {sent_date} at {sent_time} (different URL: {existing_url})"
    
    return False, ""


def save_sent_article(url: str, title: str, content_hash: str, sent_data: dict) -> dict:
    """Track a newly sent article."""
    now = dt.datetime.now(dt.timezone.utc)
    
    sent_data["articles"][url] = {
        "title": title,
        "content_hash": content_hash,
        "sent_date": now.strftime("%Y-%m-%d"),
        "sent_time": now.strftime("%H:%M:%S"),
        "sent_timestamp": now.isoformat()
    }
    sent_data["last_updated"] = now.isoformat()
    
    # Write to file
    try:
        with open(SENT_ARTICLES_FILE, "w", encoding="utf-8") as f:
            json.dump(sent_data, f, indent=2, ensure_ascii=False)
    except IOError as e:
        print(f"⚠️  Warning: Failed to save sent_articles.json: {e}", file=sys.stderr)
    
    return sent_data


def fetch_html(url: str) -> str:
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    return resp.text


def extract_article_links(archive_url: str, target_date: dt.date) -> list[str]:
    html = fetch_html(archive_url)
    soup = BeautifulSoup(html, "html.parser")

    prefix = f"{BASE_URL}/{target_date.year}/{target_date.month:02d}/{target_date.day:02d}/"
    links: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        full_url = urljoin(archive_url, href)
        if full_url.startswith(prefix):
            links.add(full_url)

    return sorted(links)


def extract_article_content(article_url: str) -> tuple[str, str]:
    html = fetch_html(article_url)
    soup = BeautifulSoup(html, "html.parser")

    # Title
    title_tag = soup.find("h1") or soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else article_url

    # Try to locate main article area first
    article_node = soup.find("article") or soup.find("div", class_="post-content")
    if article_node is None:
        article_node = soup.body or soup

    paragraphs: list[str] = []
    for p in article_node.find_all("p"):
        text = p.get_text(" ", strip=True)
        if not text:
            continue
        # Skip very short / boilerplate lines
        if len(text) < 30:
            continue
        paragraphs.append(text)

    # Fallback to some generic text when we couldn't find good paragraphs
    if not paragraphs:
        paragraphs.append("Content not clearly detected from page.")

    body = "\n\n".join(paragraphs[:4])  # Limit number of paragraphs

    # Telegram hard limit is 4096 characters
    max_len = 3500
    if len(body) > max_len:
        body = body[:max_len].rstrip() + "..."

    return title, body


def build_message(title: str, body: str, url: str) -> str:
    return f"{title}\n\n{body}\n\nRead more: {url}"


def send_telegram_message(token: str, chat_id: str, text: str) -> None:
    api_url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    resp = requests.post(api_url, json=payload, timeout=15)
    try:
        resp.raise_for_status()
    except requests.HTTPError as exc:
        print(f"Failed to send message: {exc} - response: {resp.text[:500]}", file=sys.stderr)


def main(argv: list[str]) -> None:
    if len(argv) > 2:
        raise SystemExit("Usage: python news_scraper.py [YYYY-MM-DD]")

    date_arg = argv[1] if len(argv) == 2 else os.getenv("TARGET_DATE")
    target_date = get_target_date(date_arg)

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        raise SystemExit("Environment variables TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set.")

    # Load and cleanup sent articles
    sent_data = load_sent_articles()
    sent_data = cleanup_old_articles(sent_data)
    
    num_tracked = len(sent_data.get("articles", {}))
    print(f"📊 Currently tracking {num_tracked} articles from last {RETENTION_DAYS} days")

    archive_url = build_archive_url(target_date)
    print(f"🔍 Fetching archive page: {archive_url}")

    try:
        article_links = extract_article_links(archive_url, target_date)
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"Failed to fetch archive page: {exc}") from exc

    if not article_links:
        print(f"📰 No articles found for {target_date.isoformat()}")
        return

    print(f"📰 Found {len(article_links)} total articles for {target_date.isoformat()}")

    # Tracking counters
    sent_count = 0
    skipped_count = 0
    error_count = 0

    for idx, article_url in enumerate(article_links, start=1):
        try:
            title, body = extract_article_content(article_url)
            content_hash = generate_content_hash(title, body)
            
            # Check if already sent
            is_sent, reason = is_article_sent(article_url, content_hash, sent_data)
            
            if is_sent:
                # Truncate title for display
                display_title = title[:50] + "..." if len(title) > 50 else title
                print(f"⏭️  [{idx}/{len(article_links)}] SKIP: {display_title} ({reason})")
                skipped_count += 1
                continue
            
            # Send to Telegram
            message = build_message(title, body, article_url)
            send_telegram_message(bot_token, chat_id, message)
            
            # Track as sent
            sent_data = save_sent_article(article_url, title, content_hash, sent_data)
            
            # Truncate title for display
            display_title = title[:60] + "..." if len(title) > 60 else title
            print(f"✅ [{idx}/{len(article_links)}] SENT: {display_title}")
            sent_count += 1
            
        except Exception as exc:  # noqa: BLE001
            display_url = article_url[:80] + "..." if len(article_url) > 80 else article_url
            print(f"❌ [{idx}/{len(article_links)}] ERROR: {display_url} - {exc}", file=sys.stderr)
            error_count += 1

    # Print summary
    print(f"\n📤 Sent: {sent_count} | ⏭️  Skipped: {skipped_count} | ❌ Errors: {error_count}")
    
    if sent_count > 0:
        print(f"✅ Updated sent_articles.json with {sent_count} new articles")


if __name__ == "__main__":  # pragma: no cover
    main(sys.argv)
