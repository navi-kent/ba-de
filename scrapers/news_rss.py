"""Google News RSS scraper
使用方式：python scrapers/news_rss.py
"""
import json
import yaml
import feedparser
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from dateutil import parser as date_parser
from utils import get_db_connection, load_search_config, log_run_start, log_run_finish

SCRAPER_NAME = "news_rss"

CONFIG   = load_search_config()
LOCATION = CONFIG["location"]


def generate_keywords():
    """根據 config 動態生成搜尋關鍵字清單"""
    keywords = []
    for template in CONFIG["news_keywords"]["core"]:
        keywords.append(template.format(**LOCATION))
    for issue in CONFIG["news_keywords"]["issues"]:
        keywords.append(f'"{LOCATION["city"]}" "{LOCATION["district"]}" "{issue}"')
    keywords.extend(CONFIG["news_keywords"]["local_topics"])
    return keywords


def build_rss_url(keyword: str) -> str:
    return (
        f"https://news.google.com/rss/search?"
        f"q={quote(keyword)}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    )


def insert_post(conn, entry, keyword) -> bool:
    """回傳 True 代表實際插入，False 代表重複略過。"""
    post_id = entry.get("id") or entry.get("link")
    if not post_id:
        return False

    try:
        published_dt = date_parser.parse(entry.get("published", "")) if entry.get("published") else None

        if published_dt and published_dt.replace(tzinfo=None) < datetime(2026, 3, 1):
            return False

        published = published_dt.strftime("%Y-%m-%d %H:%M:%S") if published_dt else None
    except Exception:
        published = None

    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO raw_posts
               (source, source_account, post_id, author, title, content,
                url, published_at, raw_json)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (source, post_id) DO NOTHING""",
            (
                "news",
                keyword,
                post_id,
                entry.get("source", {}).get("title") if isinstance(entry.get("source"), dict) else None,
                entry.get("title"),
                entry.get("summary", ""),
                entry.get("link"),
                published,
                json.dumps(dict(entry), default=str, ensure_ascii=False),
            ),
        )
    return cur.rowcount == 1


def run():
    keywords = generate_keywords()
    print(f"📍 搜尋範圍：{LOCATION['city']} {LOCATION['district']}")
    print(f"🔑 關鍵字數量：{len(keywords)}\n")

    conn = get_db_connection()
    run_id = log_run_start(conn, SCRAPER_NAME)
    total_found = 0
    total_inserted = 0

    try:
        for keyword in keywords:
            print(f"🔍 抓取：{keyword}")
            feed = feedparser.parse(build_rss_url(keyword))

            if feed.bozo:
                print(f"  ⚠️  RSS parse warning: {feed.bozo_exception}")

            found    = len(feed.entries)
            inserted = sum(1 for e in feed.entries if insert_post(conn, e, keyword))
            conn.commit()

            total_found    += found
            total_inserted += inserted
            print(f"  → 找到 {found} 則，新增 {inserted} 則")

        log_run_finish(conn, run_id, "success", total_found, total_inserted)
        print(f"\n✅ 完成：共找到 {total_found} 則，去重後新增 {total_inserted} 則")

    except Exception as e:
        log_run_finish(conn, run_id, "failed", total_found, total_inserted, str(e))
        print(f"\n❌ 失敗：{e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    run()
