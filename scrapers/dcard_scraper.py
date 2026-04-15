"""Dcard 爬蟲
使用方式：python scrapers/dcard_scraper.py
"""
import json
import time
import requests
import pymysql
from pathlib import Path
from utils import get_db_connection, load_search_config, log_run_start, log_run_finish

SCRAPER_NAME = "dcard"
DCARD_API    = "https://www.dcard.tw/service/api/v2"
HEADERS      = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
FORUMS       = ["mood", "trending", "relationship"]

CONFIG   = load_search_config()
LOCATION = CONFIG["location"]


def should_keep_post(title: str, content: str) -> bool:
    keywords = [LOCATION["city"], LOCATION["district"], "八德"]
    text = f"{title} {content}".lower()
    return any(kw in text for kw in keywords)


def fetch_forum_posts(forum: str, limit: int = 30) -> list:
    try:
        resp = requests.get(
            f"{DCARD_API}/forums/{forum}/posts",
            headers=HEADERS,
            params={"limit": limit, "popular": "false"},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"  ⚠️  抓取失敗：{e}")
        return []


def fetch_post_detail(post_id: int) -> dict:
    try:
        resp = requests.get(f"{DCARD_API}/posts/{post_id}", headers=HEADERS, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"  ⚠️  抓取內文失敗：{e}")
        return {}


def insert_post(conn, post: dict, forum: str) -> bool:
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO raw_posts
                   (source, source_account, post_id, author, title, content,
                    url, published_at, likes, comments, raw_json)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    "dcard",
                    forum,
                    str(post["id"]),
                    post.get("school"),
                    post.get("title"),
                    post.get("content", ""),
                    f"https://www.dcard.tw/f/{forum}/p/{post['id']}",
                    post.get("createdAt"),
                    post.get("likeCount", 0),
                    post.get("commentCount", 0),
                    json.dumps(post, ensure_ascii=False),
                ),
            )
        return True
    except pymysql.IntegrityError:
        return False


def run():
    print(f"📍 搜尋範圍：{LOCATION['city']} {LOCATION['district']}")
    print(f"📋 監控看板：{', '.join(FORUMS)}\n")

    conn   = get_db_connection()
    run_id = log_run_start(conn, SCRAPER_NAME)
    total_found = total_inserted = 0

    try:
        for forum in FORUMS:
            print(f"🔍 抓取看板：{forum}")
            posts = fetch_forum_posts(forum, limit=30)
            print(f"  → 找到 {len(posts)} 篇文章")

            for post in posts:
                if not should_keep_post(post.get("title", ""), post.get("excerpt", "")):
                    continue
                detail = fetch_post_detail(post["id"])
                if not detail:
                    continue
                if not should_keep_post(detail.get("title", ""), detail.get("content", "")):
                    continue
                if insert_post(conn, detail, forum):
                    total_inserted += 1
                    print(f"  ✅ {detail['title'][:30]}...")
                total_found += 1
                time.sleep(0.3)

            conn.commit()

        log_run_finish(conn, run_id, "success", total_found, total_inserted)
        print(f"\n✅ 完成：共找到 {total_found} 則相關文章，新增 {total_inserted} 則")

    except Exception as e:
        log_run_finish(conn, run_id, "failed", total_found, total_inserted, str(e))
        print(f"\n❌ 失敗：{e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    run()
