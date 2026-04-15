"""PTT 爬蟲
使用方式：python scrapers/ptt_scraper.py
"""
import json
import time
import requests
import pymysql
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from utils import get_db_connection, load_search_config, log_run_start, log_run_finish

SCRAPER_NAME = "ptt"
PTT_BASE     = "https://www.ptt.cc"
BOARDS       = ["Taoyuan", "ChungLi"]

CONFIG   = load_search_config()
LOCATION = CONFIG["location"]


def get_session():
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cookie": "over18=1",
        "Referer": PTT_BASE,
    })
    return session


def should_keep_post(title: str, content: str) -> bool:
    keywords = [LOCATION["city"], LOCATION["district"], "八德"]
    text = f"{title} {content}".lower()
    return any(kw in text for kw in keywords)


def parse_post_list(session, board: str, pages: int = 2) -> list:
    posts = []
    url = f"{PTT_BASE}/bbs/{board}/index.html"

    for i in range(pages):
        try:
            resp = session.get(url, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            for div in soup.find_all("div", class_="r-ent"):
                try:
                    title_tag = div.find("div", class_="title").find("a")
                    if not title_tag:
                        continue
                    posts.append({
                        "title":  title_tag.text.strip(),
                        "url":    urljoin(PTT_BASE, title_tag["href"]),
                        "author": div.find("div", class_="author").text.strip(),
                        "date":   div.find("div", class_="date").text.strip(),
                    })
                except Exception:
                    continue

            prev_link = soup.find("a", string="‹ 上頁")
            if not prev_link:
                break
            url = urljoin(PTT_BASE, prev_link["href"])
            time.sleep(1.5)

        except Exception as e:
            print(f"  ⚠️  抓取 {board} 第 {i+1} 頁失敗：{e}")
            break

    return posts


def parse_post_content(session, url: str) -> dict:
    try:
        resp = session.get(url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        main = soup.find("div", id="main-content")
        if not main:
            return {}

        meta_values = soup.find_all("span", class_="article-meta-value")
        published_at_raw = meta_values[3].text.strip() if len(meta_values) >= 4 else None

        published_at = None
        if published_at_raw:
            try:
                dt = datetime.strptime(published_at_raw, "%a %b %d %H:%M:%S %Y")
                published_at = dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                pass

        for tag in main.find_all(["div", "span"], class_=["article-metaline", "article-metaline-right", "push"]):
            tag.decompose()

        content = main.get_text(separator="\n", strip=True)
        return {"content": content, "published_at": published_at}

    except Exception as e:
        print(f"  ⚠️  抓取內文失敗 ({url}): {e}")
        return {}


def insert_post(conn, post: dict, board: str) -> bool:
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO raw_posts
                   (source, source_account, post_id, author, title, content,
                    url, published_at, raw_json)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    "ptt",
                    board,
                    post["url"],
                    post.get("author"),
                    post.get("title"),
                    post.get("content", ""),
                    post["url"],
                    post.get("published_at"),
                    json.dumps(post, ensure_ascii=False),
                ),
            )
        return True
    except pymysql.IntegrityError:
        return False


def run():
    print(f"📍 搜尋範圍：{LOCATION['city']} {LOCATION['district']}")
    print(f"📋 監控看板：{', '.join(BOARDS)}\n")

    session = get_session()
    conn    = get_db_connection()
    run_id  = log_run_start(conn, SCRAPER_NAME)
    total_found    = 0
    total_inserted = 0

    try:
        for board in BOARDS:
            print(f"🔍 抓取看板：{board}")
            posts = parse_post_list(session, board, pages=2)
            print(f"  → 找到 {len(posts)} 篇文章")

            for post in posts:
                if not should_keep_post(post["title"], ""):
                    continue

                detail = parse_post_content(session, post["url"])
                if not detail:
                    continue

                post.update(detail)

                published_at = post.get("published_at")
                if published_at:
                    try:
                        pub_dt = datetime.strptime(published_at, "%Y-%m-%d %H:%M:%S")
                        if pub_dt < datetime(2026, 3, 1):
                            continue
                    except Exception:
                        pass

                if not should_keep_post(post["title"], post.get("content", "")):
                    continue

                if insert_post(conn, post, board):
                    total_inserted += 1
                    print(f"  ✅ {post['title'][:30]}...")

                total_found += 1
                time.sleep(0.5)

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
