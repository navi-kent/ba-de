#!/bin/sh
set -eu

echo "[scheduler] starting scraper run at $(date -Iseconds)"
python /app/db/init_db.py
python /app/scrapers/news_rss.py
python /app/scrapers/ptt_scraper.py
echo "[scheduler] scraper run finished at $(date -Iseconds)"
