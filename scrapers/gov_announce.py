"""地方政府公告爬蟲 - OpenData XML 版本
使用方式：python scrapers/gov_announce.py
"""
import json
import requests
import urllib3
import xml.etree.ElementTree as ET
from urllib.parse import urljoin
from utils import get_db_connection, load_search_config, log_run_start, log_run_finish

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SCRAPER_NAME = "gov_announce"
HEADERS      = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
GOV_SOURCES  = [
    {"name": "桃園市政府", "url": "https://www.tycg.gov.tw/OpenData.aspx?SN=50C7BB8497F3C8C2"},
    {"name": "八德區公所", "url": "https://www.bade.tycg.gov.tw/OpenData.aspx?SN=26647240B7BF2853"},
]

CONFIG   = load_search_config()
LOCATION = CONFIG["location"]


def should_keep_post(title: str, content: str) -> bool:
    keywords = [LOCATION["district"], "八德", "全市", "交通", "建設", "都市計畫"]
    text = f"{title} {content}".lower()
    return any(kw in text for kw in keywords)


def parse_opendata_xml(xml_content: str, base_url: str) -> list:
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
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO raw_posts
               (source, source_account, post_id, title, content,
                url, published_at, raw_json)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (source, post_id) DO NOTHING""",
            (
                "gov",
                source_name,
                post["url"],
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
            resp = requests.get(source["url"], headers=HEADERS, timeout=20, verify=False)
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
