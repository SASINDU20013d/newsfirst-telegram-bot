# Newsfirst English daily archive → Telegram

This project fetches the daily archive page from https://english.newsfirst.lk for a given date,
extracts all news articles for that day, and sends each article to a Telegram chat using a bot.

## How it works

- Builds the daily archive URL: `https://english.newsfirst.lk/YYYY/MM/DD`.
- Collects all article links that belong to that exact date.
- For each article:
  - Downloads the article page.
  - Extracts the title and main paragraph text.
  - Sends a formatted message to a Telegram chat.
- A GitHub Actions workflow runs this script every hour.

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

## GitHub Actions setup

1. Push this repository to GitHub.
2. In your GitHub repo settings, add two **Actions secrets**:

   - `TELEGRAM_BOT_TOKEN` → your bot token
   - `TELEGRAM_CHAT_ID` → your target chat ID

3. The workflow in `.github/workflows/news_scraper.yml` will then:

   - Run every hour (`cron: "5 * * * *"`).
   - Install dependencies.
   - Run `python news_scraper.py`.

You can also trigger it manually from the **Actions** tab via the `workflow_dispatch` event.
