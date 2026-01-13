import datetime as dt
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://english.newsfirst.lk"
SENT_ARTICLES_PATH = Path("sent_articles.json")
RETENTION_DAYS = 7


def get_target_date(date_arg: str | None = None) -> dt.date:
    if date_arg:
        try:
            return dt.datetime.strptime(date_arg, "%Y-%m-%d").date()
        except ValueError as exc:
            raise SystemExit(f"Invalid date format: {date_arg!r}. Use YYYY-MM-DD.") from exc
    return dt.date.today()


def build_archive_url(target_date: dt.date) -> str:
    return f"{BASE_URL}/{target_date.year}/{target_date.month:02d}/{target_date.day:02d}"


def fetch_html(url: str) -> str:
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    return resp.text


def extract_article_links(archive_url: str, target_date: dt.date) -> List[str]:
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


def extract_article_content(article_url: str) -> Tuple[str, str]:
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


def build_message(title: str, body: str, url: str, sent_at_display: str | None = None) -> str:
    """Build the Telegram message text.

    If ``sent_at_display`` is provided, it is included as a human-readable
    timestamp under the title (for example "2026-01-13 10:15 UTC").
    """

    if sent_at_display:
        header = f"{title}\n🕒 {sent_at_display}"
    else:
        header = title

    return f"{header}\n\n{body}\n\nRead more: {url}"


def generate_content_hash(title: str, body: str) -> str:
    """Generate a stable SHA-256 hash for an article's content.

    We combine title and body to detect duplicates even if the URL changes.
    """

    normalized = (title or "").strip() + "\n\n" + (body or "").strip()
    return hashlib.sha256(normalized.encode("utf-8", errors="ignore")).hexdigest()


def _empty_store() -> Dict[str, List[Dict[str, Any]]]:
    return {"articles": []}


def load_sent_articles(path: Path = SENT_ARTICLES_PATH) -> Dict[str, List[Dict[str, Any]]]:
    """Load tracking data from JSON file, returning an empty structure on errors.

    The file is auto-created later when we first persist data.
    """

    if not path.exists():
        return _empty_store()

    try:
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return _empty_store()
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"❌ Failed to load {path.name}: {exc}. Starting with an empty store.", file=sys.stderr)
        return _empty_store()

    if isinstance(data, dict) and "articles" in data and isinstance(data["articles"], list):
        return data  # type: ignore[return-value]

    # Backwards compatibility / unexpected format
    print(f"❌ Unexpected format in {path.name}. Resetting tracking store.", file=sys.stderr)
    return _empty_store()


def cleanup_old_articles(
    store: Dict[str, List[Dict[str, Any]]],
    retention_days: int = RETENTION_DAYS,
) -> Dict[str, List[Dict[str, Any]]]:
    """Remove articles older than the retention period.

    Any malformed timestamps are skipped but do not cause the script to fail.
    """

    cutoff = dt.datetime.utcnow() - dt.timedelta(days=retention_days)
    cleaned: List[Dict[str, Any]] = []

    for article in store.get("articles", []):
        sent_at_str = article.get("sent_at")
        if not isinstance(sent_at_str, str):
            # Keep entries with missing/invalid timestamp rather than crash
            cleaned.append(article)
            continue
        try:
            # Support values with or without trailing "Z"
            ts = sent_at_str.rstrip("Z")
            sent_at = dt.datetime.fromisoformat(ts)
        except ValueError:
            print(
                f"❌ Invalid sent_at timestamp '{sent_at_str}' in tracking store; keeping entry but it won't be pruned.",
                file=sys.stderr,
            )
            cleaned.append(article)
            continue

        if sent_at >= cutoff:
            cleaned.append(article)

    pruned_count = len(store.get("articles", [])) - len(cleaned)
    if pruned_count > 0:
        print(f"🧹 Cleaned up {pruned_count} old tracked article(s) older than {retention_days} days.")

    return {"articles": cleaned}


def is_article_sent(
    url: str,
    content_hash: str,
    store: Dict[str, List[Dict[str, Any]]],
) -> Tuple[bool, str | None]:
    """Check if an article was already sent, by URL or content hash.

    Returns (True, reason) if duplicate, else (False, None).
    """

    for article in store.get("articles", []):
        stored_url = article.get("url")
        stored_hash = article.get("content_hash")
        sent_at = article.get("sent_at")

        if stored_url == url:
            reason = (
                f"URL already sent on {sent_at}" if sent_at else "URL already sent previously"
            )
            return True, reason
        if stored_hash == content_hash:
            reason = (
                f"Content already sent on {sent_at}" if sent_at else "Content already sent previously"
            )
            return True, reason

    return False, None


def save_sent_article(
    url: str,
    content_hash: str,
    title: str,
    store: Dict[str, List[Dict[str, Any]]],
    *,
    sent_at: str | None = None,
) -> None:
    """Append a newly sent article to the in-memory store.

    ``sent_at`` should be an ISO-8601 timestamp string in UTC with a trailing
    ``"Z"`` (for example ``"2026-01-13T05:29:46Z"``). If not provided, the
    current UTC time is used.
    """

    if sent_at is None:
        sent_at = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    store.setdefault("articles", []).append(
        {
            "url": url,
            "content_hash": content_hash,
            "title": title,
            "sent_at": sent_at,
        }
    )


def save_sent_articles_to_file(
    store: Dict[str, List[Dict[str, Any]]],
    path: Path = SENT_ARTICLES_PATH,
) -> None:
    """Persist tracking data to disk as pretty-printed JSON."""

    try:
        path.write_text(json.dumps(store, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"❌ Failed to write {path.name}: {exc}", file=sys.stderr)


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
        print(f"❌ Failed to send message: {exc} - response: {resp.text[:500]}", file=sys.stderr)


def main(argv: list[str]) -> None:
    if len(argv) > 2:
        raise SystemExit("Usage: python news_scraper.py [YYYY-MM-DD]")

    date_arg = argv[1] if len(argv) == 2 else os.getenv("TARGET_DATE")
    target_date = get_target_date(date_arg)

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        raise SystemExit("Environment variables TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set.")

    archive_url = build_archive_url(target_date)

    # Load and clean existing tracking data
    sent_store = load_sent_articles()
    sent_store = cleanup_old_articles(sent_store, RETENTION_DAYS)
    tracked_count = len(sent_store.get("articles", []))

    print(f"📊 Currently tracking {tracked_count} articles from last {RETENTION_DAYS} days")
    print(f"🔍 Fetching archive page: {archive_url}")

    try:
        article_links = extract_article_links(archive_url, target_date)
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"Failed to fetch archive page: {exc}") from exc

    if not article_links:
        print("No articles found for date", target_date.isoformat())
        return
    total = len(article_links)
    print(f"📰 Found {total} total articles for {target_date.isoformat()}")

    sent_count = 0
    skipped_count = 0
    error_count = 0

    for idx, article_url in enumerate(article_links, start=1):
        try:
            title, body = extract_article_content(article_url)
            content_hash = generate_content_hash(title, body)

            # Single source of truth for the send time: use this both for the
            # human-readable time in the Telegram message and for the ISO
            # timestamp stored in sent_articles.json.
            sent_at_dt = dt.datetime.utcnow().replace(microsecond=0)
            sent_at_iso = sent_at_dt.isoformat() + "Z"
            sent_at_display = sent_at_dt.strftime("%Y-%m-%d %H:%M UTC")

            is_sent, reason = is_article_sent(article_url, content_hash, sent_store)
            if is_sent:
                skipped_count += 1
                extra = f" ({reason})" if reason else ""
                print(f"⏭ [{idx}/{total}] SKIP: {title}{extra}")
                continue

            message = build_message(title, body, article_url, sent_at_display)
            send_telegram_message(bot_token, chat_id, message)

            save_sent_article(article_url, content_hash, title, sent_store, sent_at=sent_at_iso)
            save_sent_articles_to_file(sent_store)

            sent_count += 1
            print(f"✅ [{idx}/{total}] SENT: {title}")
        except Exception as exc:  # noqa: BLE001
            error_count += 1
            print(f"❌ [{idx}/{total}] ERROR processing {article_url}: {exc}", file=sys.stderr)

    # Final save (in case cleanup pruned anything earlier in the run)
    sent_store = cleanup_old_articles(sent_store, RETENTION_DAYS)
    save_sent_articles_to_file(sent_store)

    print(f"📤 Sent: {sent_count} | ⏭ Skipped: {skipped_count} | ❌ Errors: {error_count}")


if __name__ == "__main__":  # pragma: no cover
    main(sys.argv)
