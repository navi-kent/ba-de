"""Google News RSS 爬蟲

Google News 提供 RSS feed，以關鍵字組合搜尋，不需登入、不需 API key。
關鍵字清單由 config/search_config.yaml 動態產生（core × issues + local_topics）。

使用方式：python scrapers/news_rss.py
"""
import json
import yaml
import feedparser
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote
from dateutil import parser as date_parser
from utils import get_db_connection, load_search_config, log_run_start, log_run_finish

SCRAPER_NAME = "news_rss"

CONFIG   = load_search_config()
LOCATION = CONFIG["location"]


def generate_keywords():
    """根據 config/search_config.yaml 動態產生搜尋關鍵字清單。

    產生規則：
    - core：地區模板（如 "桃園市" "八德區"）
    - issues：地區 × 議題（如 "桃園市" "八德區" "交通"）
    - local_topics：在地特殊關鍵字（如 "捷運綠線" "八德"）
    """
    keywords = []
    for template in CONFIG["news_keywords"]["core"]:
        keywords.append(template.format(**LOCATION))
    for issue in CONFIG["news_keywords"]["issues"]:
        keywords.append(f'"{LOCATION["city"]}" "{LOCATION["district"]}" "{issue}"')
    keywords.extend(CONFIG["news_keywords"]["local_topics"])
    return keywords


def build_rss_url(keyword: str, lookback_days: int = 30) -> str:
    """將關鍵字編碼成 Google News RSS URL（繁體中文 / 台灣版）。

    加上 after: 日期過濾，避免熱門舊文章佔滿 100 篇上限而擠掉最新新聞。
    """
    cutoff = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    q = quote(f"{keyword} after:{cutoff}")
    return f"https://news.google.com/rss/search?q={q}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"


# 判斷文章是否與八德區相關的詞彙集合
BADE_TERMS = ["八德", "霄裡", "大湳", "八德擴大都市計畫"]


def is_relevant(title: str, summary: str) -> bool:
    """文章標題或摘要必須含八德區相關詞彙才算相關。

    設計原因：Google News 以關鍵字搜尋，回傳結果可能包含整個桃園市甚至全台新聞，
    需要二次過濾確保內容確實與八德區有關。
    """
    text = (title or "") + (summary or "")
    return any(term in text for term in BADE_TERMS)


def insert_post(conn, entry, keyword) -> bool:
    """將單篇 RSS 文章寫入 raw_posts。

    Args:
        entry:   feedparser 解析出的單篇文章 dict
        keyword: 產生此篇文章的搜尋關鍵字（存為 source_account，方便統計熱門議題）

    Returns:
        True 代表實際新增，False 代表重複略過（ON CONFLICT DO NOTHING）
    """
    # Google News 用 link 作為文章唯一 ID
    post_id = entry.get("id") or entry.get("link")
    if not post_id:
        return False

    title   = entry.get("title", "")
    summary = entry.get("summary", "")

    # 第一道過濾：相關性（標題或摘要必須含八德區關鍵詞）
    if not is_relevant(title, summary):
        return False

    # 媒體名稱（存 author 欄位）
    media = entry.get("source", {}).get("title") if isinstance(entry.get("source"), dict) else None

    # Google News RSS 標題格式為「文章標題 - 媒體名稱」，拆掉後綴還原乾淨標題
    if media and title.endswith(f" - {media}"):
        title = title[: -len(f" - {media}")].rstrip(" -").strip()

    try:
        published_dt = date_parser.parse(entry.get("published", "")) if entry.get("published") else None

        # 第二道過濾：只保留 2026 年以後的文章
        if published_dt and published_dt.replace(tzinfo=None) < datetime(2026, 1, 1):
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
                keyword,       # source_account 記錄搜尋關鍵字，用於首頁「熱門議題」統計
                post_id,
                media,
                title,
                summary,
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

            # bozo=True 代表 RSS 格式有問題，但通常仍可解析，只列警告不中斷
            if feed.bozo:
                print(f"  ⚠️  RSS parse warning: {feed.bozo_exception}")

            found    = len(feed.entries)
            inserted = sum(1 for e in feed.entries if insert_post(conn, e, keyword))
            conn.commit()  # 每個關鍵字處理完後 commit，避免一個失敗回滾全部

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
