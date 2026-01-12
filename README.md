# Newsfirst English daily archive → Telegram

This project fetches the daily archive page from https://english.newsfirst.lk for a given date,
extracts all news articles for that day, and sends each article to a Telegram chat using a bot.

## Features

- **Duplicate Detection**: Prevents sending the same news articles repeatedly
- **Content-Based Fingerprinting**: Detects duplicates even if URL changes
- **Automatic Tracking**: Maintains history of sent articles for 7 days
- **Clear Logging**: Shows which articles were sent, skipped, or had errors

## How it works

- Builds the daily archive URL: `https://english.newsfirst.lk/YYYY/MM/DD`.
- Collects all article links that belong to that exact date.
- Checks if each article was already sent (by URL or content hash).
- For each new article:
  - Downloads the article page.
  - Extracts the title and main paragraph text.
  - Sends a formatted message to a Telegram chat.
  - Saves article metadata to `sent_articles.json`.
- A GitHub Actions workflow runs this script every hour.
- Old articles (>7 days) are automatically removed from tracking.

## Local setup

1. Create and activate a Python 3.11+ environment.
2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Export your Telegram bot token and chat ID as environment variables (do **not** commit them):

   ```bash
   set TELEGRAM_BOT_TOKEN=YOUR_TOKEN_HERE   # Windows CMD
   set TELEGRAM_CHAT_ID=YOUR_CHAT_ID_HERE
   # or in PowerShell:
   $env:TELEGRAM_BOT_TOKEN="YOUR_TOKEN_HERE"
   $env:TELEGRAM_CHAT_ID="YOUR_CHAT_ID_HERE"
   ```

4. Run the scraper for today (default):

   ```bash
   python news_scraper.py
   ```

5. Or run for a specific date:

   ```bash
   python news_scraper.py 2026-01-11
   ```

**Note**: The `sent_articles.json` tracking file is created automatically on the first run. You do not need to create it manually.

## GitHub Actions setup

1. Push this repository to GitHub.
2. In your GitHub repo settings, add two **Actions secrets**:

   - `TELEGRAM_BOT_TOKEN` → your bot token
   - `TELEGRAM_CHAT_ID` → your target chat ID

3. **Important**: The workflow requires write permissions to commit the tracking file. This should already be configured in the workflow file with `permissions: contents: write`.

4. The workflow in `.github/workflows/news_scraper.yml` will then:

   - Run every hour (`cron: "5 * * * *"`).
   - Install dependencies.
   - Run `python news_scraper.py`.
   - Automatically commit and push `sent_articles.json` if there are changes.

You can also trigger it manually from the **Actions** tab via the `workflow_dispatch` event.

## How Duplicate Detection Works

The bot tracks sent articles in `sent_articles.json` with:
- Article URL
- Title
- Content hash (SHA-256 of title + first 500 characters)
- Send timestamp

On each run:
1. Loads existing tracking data
2. Cleans up articles older than 7 days
3. For each article found:
   - Checks if URL was already sent
   - Checks if content hash matches any sent article
   - Skips if duplicate, sends if new
4. Updates tracking file with newly sent articles

**First run output**:
```
📊 Currently tracking 0 articles from last 7 days
🔍 Fetching archive page: https://english.newsfirst.lk/2026/01/12
📰 Found 10 total articles for 2026-01-12
✅ [1/10] SENT: Breaking News Article
✅ [2/10] SENT: Sports Update
...
📤 Sent: 10 | ⏭ Skipped: 0 | ❌ Errors: 0
```

**Subsequent run (duplicates detected)**:
```
📊 Currently tracking 10 articles from last 7 days
📰 Found 10 total articles for 2026-01-12
⏭ [1/10] SKIP: Breaking News Article... (URL already sent on 2026-01-12 at 08:15:23)
⏭ [2/10] SKIP: Sports Update... (URL already sent on 2026-01-12 at 08:16:45)
...
📤 Sent: 0 | ⏭ Skipped: 10 | ❌ Errors: 0
```
