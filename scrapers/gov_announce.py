"""地方政府公告爬蟲 - OpenData XML 版本

桃園市政府與八德區公所提供 OpenData XML 格式的公告資料，免登入、免 API key。
XML 編碼有時是 UTF-16（預設），有時是 UTF-8，需動態偵測。

注意：此爬蟲已寫好但尚未加入排程，需手動執行或加入 scraper plist。

使用方式：python scrapers/gov_announce.py
"""
import json
import requests
import urllib3
import xml.etree.ElementTree as ET
from urllib.parse import urljoin
from utils import get_db_connection, load_search_config, log_run_start, log_run_finish

# 政府網站 SSL 憑證有時過期或不完整，disable 警告避免 log 被污染
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SCRAPER_NAME = "gov_announce"
HEADERS      = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

# OpenData XML 來源，SN 參數是各單位的資料集識別碼
GOV_SOURCES  = [
    {"name": "桃園市政府", "url": "https://www.tycg.gov.tw/OpenData.aspx?SN=50C7BB8497F3C8C2"},
    {"name": "八德區公所", "url": "https://www.bade.tycg.gov.tw/OpenData.aspx?SN=26647240B7BF2853"},
]

CONFIG   = load_search_config()
LOCATION = CONFIG["location"]


def should_keep_post(title: str, content: str) -> bool:
    """標題或內文必須含以下關鍵詞之一才保留。

    政府公告範圍較廣（全市），加入「全市」「交通」「建設」「都市計畫」
    是為了保留影響八德居民的市府政策公告。
    """
    keywords = [LOCATION["district"], "八德", "全市", "交通", "建設", "都市計畫"]
    text = f"{title} {content}".lower()
    return any(kw in text for kw in keywords)


def parse_opendata_xml(xml_content: str, base_url: str) -> list:
    """解析桃園市政府 OpenData XML，回傳公告清單。

    XML 結構：<Articles><Article><PSTTitle>...<PSTLink>...<PSTDate>...<PSTSummary>...

    Args:
        xml_content: 原始 XML 字串
        base_url:    用於補全相對路徑的 base URL

    Returns:
        list of dict，每個 dict 含 title / url / published_at / content
    """
    posts = []
    try:
        root = ET.fromstring(xml_content)
        for article in root.findall(".//Article"):
            try:
                title   = article.findtext("PSTTitle", "").strip()
                link    = article.findtext("PSTLink",  "").strip()
                date    = article.findtext("PSTDate",  "").strip()
                summary = article.findtext("PSTSummary", "").strip()
                if not title or not link:
                    continue
                posts.append({
                    "title":        title,
                    "url":          urljoin(base_url, link),
                    "published_at": date,
                    "content":      summary,
                })
            except Exception:
                continue
    except Exception as e:
        print(f"  ⚠️  XML 解析失敗: {e}")
    return posts


def insert_post(conn, post: dict, source_name: str) -> bool:
    """將單篇政府公告寫入 raw_posts。

    使用公告 URL 作為 post_id（政府公告 URL 穩定唯一）。

    Returns:
        True 代表實際新增，False 代表重複略過
    """
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO raw_posts
               (source, source_account, post_id, title, content,
                url, published_at, raw_json)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (source, post_id) DO NOTHING""",
            (
                "gov",
                source_name,  # source_account 記錄機關名稱（桃園市政府 / 八德區公所）
                post["url"],  # URL 當唯一 ID
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
    print(f"🏛️  監控來源：{len(GOV_SOURCES)} 個政府 OpenData 頻道\n")

    conn   = get_db_connection()
    run_id = log_run_start(conn, SCRAPER_NAME)
    total_found = total_inserted = 0

    try:
        for source in GOV_SOURCES:
            print(f"🔍 抓取：{source['name']}")
            # verify=False：部分政府網站 SSL 憑證過期，關閉驗證確保可以抓到資料
            resp = requests.get(source["url"], headers=HEADERS, timeout=20, verify=False)

            # 桃園市政府 OpenData 預設 UTF-16，但部分端點實際為 UTF-8
            # 先嘗試 UTF-16，若解碼後不是 XML 開頭則改用 UTF-8
            resp.encoding = "utf-16"
            if not resp.text.strip().startswith("<?xml"):
                resp.encoding = "utf-8"

            posts = parse_opendata_xml(resp.text, source["url"])
            print(f"  → 找到 {len(posts)} 則公告")

            for post in posts:
                if not should_keep_post(post["title"], post["content"]):
                    continue
                if insert_post(conn, post, source["name"]):
                    total_inserted += 1
                    print(f"  ✅ {post['title'][:40]}...")
                total_found += 1

            conn.commit()

        log_run_finish(conn, run_id, "success", total_found, total_inserted)
        print(f"\n✅ 完成：共找到 {total_found} 則相關公告，新增 {total_inserted} 則")

    except Exception as e:
        log_run_finish(conn, run_id, "failed", total_found, total_inserted, str(e))
        print(f"\n❌ 失敗：{e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    run()
