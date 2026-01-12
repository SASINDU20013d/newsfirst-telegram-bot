import os
import sys
import datetime as dt
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://english.newsfirst.lk"


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

    archive_url = build_archive_url(target_date)
    print(f"Fetching archive page: {archive_url}")

    try:
        article_links = extract_article_links(archive_url, target_date)
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"Failed to fetch archive page: {exc}") from exc

    if not article_links:
        print("No articles found for date", target_date.isoformat())
        return

    print(f"Found {len(article_links)} articles. Sending to Telegram...")

    for idx, article_url in enumerate(article_links, start=1):
        try:
            title, body = extract_article_content(article_url)
            message = build_message(title, body, article_url)
            send_telegram_message(bot_token, chat_id, message)
            print(f"[{idx}/{len(article_links)}] Sent: {title}")
        except Exception as exc:  # noqa: BLE001
            print(f"Error processing {article_url}: {exc}", file=sys.stderr)


if __name__ == "__main__":  # pragma: no cover
    main(sys.argv)
