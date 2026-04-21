"""PTT 爬蟲

抓取 Taoyuan、ChungLi 兩個看板的最新文章，過濾出與八德區相關的內容。
PTT 網頁版（www.ptt.cc/bbs）不需登入，但需帶 Cookie: over18=1 跳過年齡確認。

使用方式：python scrapers/ptt_scraper.py
"""
import json
import time
import requests
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from utils import get_db_connection, load_search_config, log_run_start, log_run_finish

SCRAPER_NAME = "ptt"
PTT_BASE     = "https://www.ptt.cc"
BOARDS       = ["Taoyuan", "ChungLi"]  # 監控的看板清單

CONFIG   = load_search_config()
LOCATION = CONFIG["location"]


def get_session():
    """建立帶有 retry 機制與必要 header 的 requests Session。

    retry 設定：遇到 429/5xx 最多重試 3 次，指數退避（1s, 2s, 4s）。
    Cookie over18=1：PTT 所有看板都需要這個 cookie 跳過成人確認頁，否則會被導向確認頁而非文章列表。
    """
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
        "Cookie": "over18=1",  # 跳過年齡確認，不帶此 cookie 會被重導向
        "Referer": PTT_BASE,
    })
    return session


# 判斷文章是否與八德區相關的詞彙集合
BADE_TERMS = ["八德", "霄裡", "大湳", "八德擴大都市計畫"]


def should_keep_post(title: str, content: str) -> bool:
    """標題或內文必須含八德區相關詞彙。

    設計原因：Taoyuan / ChungLi 版涵蓋整個桃園市，「桃園市」條件太寬，
    直接用八德區地名過濾精準度更高。
    """
    text = f"{title} {content}"
    return any(term in text for term in BADE_TERMS)


def parse_post_list(session, board: str, pages: int = 2) -> list:
    """抓取看板文章列表，回傳最新 pages 頁的文章摘要清單。

    Args:
        board: 看板名稱（如 "Taoyuan"）
        pages: 要抓幾頁（每頁約 20 篇）

    Returns:
        list of dict，每個 dict 包含 title / url / author / date
    """
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
                        continue  # 已刪除的文章沒有 <a>，跳過
                    posts.append({
                        "title":  title_tag.text.strip(),
                        "url":    urljoin(PTT_BASE, title_tag["href"]),
                        "author": div.find("div", class_="author").text.strip(),
                        "date":   div.find("div", class_="date").text.strip(),
                    })
                except Exception:
                    continue

            # 找「上一頁」連結以翻頁
            prev_link = soup.find("a", string="‹ 上頁")
            if not prev_link:
                break
            url = urljoin(PTT_BASE, prev_link["href"])
            time.sleep(1.5)  # 翻頁間隔，避免觸發 PTT 限速

        except Exception as e:
            print(f"  ⚠️  抓取 {board} 第 {i+1} 頁失敗：{e}")
            break

    return posts


def parse_post_content(session, url: str) -> dict:
    """抓取單篇文章的完整內文與發文時間。

    PTT 文章頁 HTML 結構：
    - article-meta-value (第 4 個，index 3)：發文時間，格式 "Thu Apr 10 12:34:56 2026"
    - #main-content：完整文章，需移除推文（.push）和 meta 資訊後才是正文

    Returns:
        dict with keys: content (str), published_at (str "YYYY-MM-DD HH:MM:SS")
        失敗時回傳空 dict
    """
    try:
        resp = session.get(url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        main = soup.find("div", id="main-content")
        if not main:
            return {}

        # PTT 文章 meta 固定順序：作者、看板、標題、時間（index 3）
        meta_values = soup.find_all("span", class_="article-meta-value")
        published_at_raw = meta_values[3].text.strip() if len(meta_values) >= 4 else None

        published_at = None
        if published_at_raw:
            try:
                dt = datetime.strptime(published_at_raw, "%a %b %d %H:%M:%S %Y")
                published_at = dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                pass

        # 移除 meta 行和推文後，取純文字正文
        for tag in main.find_all(["div", "span"], class_=["article-metaline", "article-metaline-right", "push"]):
            tag.decompose()

        content = main.get_text(separator="\n", strip=True)
        return {"content": content, "published_at": published_at}

    except Exception as e:
        print(f"  ⚠️  抓取內文失敗 ({url}): {e}")
        return {}


def insert_post(conn, post: dict, board: str) -> bool:
    """將單篇 PTT 文章寫入 raw_posts。

    使用文章 URL 作為 post_id（PTT 文章 URL 永久唯一）。

    Returns:
        True 代表實際新增，False 代表重複略過
    """
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO raw_posts
               (source, source_account, post_id, author, title, content,
                url, published_at, raw_json)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (source, post_id) DO NOTHING""",
            (
                "ptt",
                board,        # source_account 記錄看板名稱
                post["url"],  # URL 當唯一 ID
                post.get("author"),
                post.get("title"),
                post.get("content", ""),
                post["url"],
                post.get("published_at"),
                json.dumps(post, ensure_ascii=False),
            ),
        )
    return cur.rowcount == 1


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
                # 第一道過濾：只看標題（尚未抓內文，節省請求數）
                if not should_keep_post(post["title"], ""):
                    continue

                # 抓完整內文（每篇額外一次 HTTP 請求）
                detail = parse_post_content(session, post["url"])
                if not detail:
                    continue

                post.update(detail)

                # 日期過濾：只保留 2026 年以後的文章
                published_at = post.get("published_at")
                if published_at:
                    try:
                        pub_dt = datetime.strptime(published_at, "%Y-%m-%d %H:%M:%S")
                        if pub_dt < datetime(2026, 1, 1):
                            continue
                    except Exception:
                        pass

                # 第二道過濾：標題 + 內文都看（標題可能無八德詞，但內文提到）
                if not should_keep_post(post["title"], post.get("content", "")):
                    continue

                if insert_post(conn, post, board):
                    total_inserted += 1
                    print(f"  ✅ {post['title'][:30]}...")

                total_found += 1
                time.sleep(0.5)  # 每篇間隔，避免對 PTT 造成過大負擔

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
