"""Facebook 公開貼文爬蟲 - mbasic 版本

Facebook 正式網站需要登入且有強力反爬機制（JavaScript 渲染、Bot 偵測）。
mbasic.facebook.com 是 Facebook 提供的輕量版，純 HTML 渲染，不需登入即可讀取
公開粉絲專頁的貼文，但僅顯示最近約 10 篇，且 Facebook 可能隨時調整結構。

注意：
- 此爬蟲穩定性較低，Facebook 結構易變，建議定期確認是否仍可正常抓取
- 尚未加入排程，需手動執行或加入 scraper plist

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

# 監控的粉絲專頁，id 為粉專的 URL slug（非數字 ID）
FB_PAGES = [
    {"name": "桃園市政府",  "id": "tycgov"},
    {"name": "八德區公所",  "id": "bade.district"},
]

CONFIG   = load_search_config()
LOCATION = CONFIG["location"]


def should_keep_post(title: str, content: str) -> bool:
    """標題或內文必須含桃園市、八德區或「八德」其中之一。"""
    keywords = [LOCATION["city"], LOCATION["district"], "八德"]
    text = f"{title} {content}".lower()
    return any(kw in text for kw in keywords)


def fetch_page_posts(page_id: str, page_name: str) -> list:
    """從 mbasic.facebook.com 抓取粉絲專頁最新貼文。

    mbasic 版本 HTML 結構：
    - 每篇貼文包在有 data-ft 屬性的 <div> 裡
    - 內文在 class 為空字串的 <div>（mbasic 特有，正式版不同）
    - 「全文」連結是通往完整貼文的連結，其 URL 的 query 參數 id 即為 post_id

    只抓前 10 篇（mbasic 首頁預設顯示數量）。

    Returns:
        list of dict，每個 dict 含 post_id / content / url / page_name
    """
    posts = []
    try:
        resp = requests.get(f"https://mbasic.facebook.com/{page_id}", headers=HEADERS, timeout=15)
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")

        # data-ft 是 Facebook 內部 tracking 屬性，每篇貼文都有，以此找到文章容器
        articles = soup.find_all("div", {"data-ft": True})[:10]

        for article in articles:
            try:
                # mbasic 貼文內文在 class="" 的 div（無 class 的 div）
                content_div = article.find("div", class_="")
                if not content_div:
                    continue
                content  = content_div.get_text(separator="\n", strip=True)

                # 「全文」連結含 post_id，沒有此連結代表貼文太短或結構不同
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
    """將單篇 Facebook 貼文寫入 raw_posts。

    FB 貼文沒有標題，published_at 也難以從 mbasic 取得，故這兩欄留空。

    Returns:
        True 代表實際新增，False 代表重複略過
    """
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO raw_posts
               (source, source_account, post_id, content, url, raw_json)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT (source, post_id) DO NOTHING""",
            (
                "fb",
                post["page_name"],  # source_account 記錄粉絲專頁名稱
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
                time.sleep(1)  # 每篇間隔，降低被 Facebook 封鎖的機率

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
