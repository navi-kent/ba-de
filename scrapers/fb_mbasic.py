"""Facebook 公開貼文爬蟲 - mbasic 版本
使用方式：python scrapers/fb_mbasic.py
"""
import json
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, parse_qs, urlparse
from utils import get_db_connection, load_search_config, log_run_start, log_run_finish

SCRAPER_NAME = "fb_mbasic"
HEADERS      = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
FB_PAGES     = [
    {"name": "桃園市政府",  "id": "tycgov"},
    {"name": "八德區公所",  "id": "bade.district"},
]

CONFIG   = load_search_config()
LOCATION = CONFIG["location"]


def should_keep_post(title: str, content: str) -> bool:
    keywords = [LOCATION["city"], LOCATION["district"], "八德"]
    text = f"{title} {content}".lower()
    return any(kw in text for kw in keywords)


def fetch_page_posts(page_id: str, page_name: str) -> list:
    posts = []
    try:
        resp = requests.get(f"https://mbasic.facebook.com/{page_id}", headers=HEADERS, timeout=15)
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")
        articles = soup.find_all("div", {"data-ft": True})[:10]

        for article in articles:
            try:
                content_div = article.find("div", class_="")
                if not content_div:
                    continue
                content  = content_div.get_text(separator="\n", strip=True)
                link_tag = article.find("a", href=True, string="全文")
                if not link_tag:
                    continue
                post_url = urljoin("https://mbasic.facebook.com", link_tag["href"])
                post_id  = parse_qs(urlparse(post_url).query).get("id", [None])[0]
                if post_id and should_keep_post("", content):
                    posts.append({"post_id": post_id, "content": content, "url": post_url, "page_name": page_name})
            except Exception:
                continue
    except Exception as e:
        print(f"  ⚠️  抓取失敗：{e}")
    return posts


def insert_post(conn, post: dict) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO raw_posts
               (source, source_account, post_id, content, url, raw_json)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT (source, post_id) DO NOTHING""",
            (
                "fb",
                post["page_name"],
                post["post_id"],
                post.get("content", ""),
                post["url"],
                json.dumps(post, ensure_ascii=False),
            ),
        )
    return cur.rowcount == 1


def run():
    print(f"📍 搜尋範圍：{LOCATION['city']} {LOCATION['district']}")
    print(f"📘 監控粉專：{len(FB_PAGES)} 個\n")

    conn   = get_db_connection()
    run_id = log_run_start(conn, SCRAPER_NAME)
    total_found = total_inserted = 0

    try:
        for page in FB_PAGES:
            print(f"🔍 抓取：{page['name']}")
            posts = fetch_page_posts(page["id"], page["name"])
            print(f"  → 找到 {len(posts)} 則相關貼文")

            for post in posts:
                if insert_post(conn, post):
                    total_inserted += 1
                    print(f"  ✅ {post['content'][:30]}...")
                total_found += 1
                time.sleep(1)

            conn.commit()

        log_run_finish(conn, run_id, "success", total_found, total_inserted)
        print(f"\n✅ 完成：共找到 {total_found} 則相關貼文，新增 {total_inserted} 則")

    except Exception as e:
        log_run_finish(conn, run_id, "failed", total_found, total_inserted, str(e))
        print(f"\n❌ 失敗：{e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    run()
