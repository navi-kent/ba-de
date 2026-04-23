"""八德區公所 & 八德區戶政事務所 最新消息爬蟲

抓取兩個官方網站的 HTML 新聞列表，寫入 gov_news 表。
  - 八德區公所：https://www.bade.tycg.gov.tw/News.aspx?n=5601&sms=10726
  - 八德區戶政事務所：https://www.bade-hro.tycg.gov.tw/News.aspx?n=12804&sms=15365

增量更新：連續一整頁都是舊資料時停止翻頁（初次執行照樣跑完所有頁面）。
"""
import json
import re
import requests
import urllib3
from datetime import date
from urllib.parse import parse_qs, urlparse, urljoin

from bs4 import BeautifulSoup

from utils import get_db_connection, log_run_start, log_run_finish

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SCRAPER_NAME = "gov_news"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
PAGE_SIZE = 20

SOURCES = [
    {
        "site":     "bade_district",
        "name":     "八德區公所",
        "list_url": "https://www.bade.tycg.gov.tw/News.aspx?n=5601&sms=10726",
        "base_url": "https://www.bade.tycg.gov.tw",
        "has_dept": True,
    },
    {
        "site":     "bade_hro",
        "name":     "八德區戶政事務所",
        "list_url": "https://www.bade-hro.tycg.gov.tw/News.aspx?n=12804&sms=15365",
        "base_url": "https://www.bade-hro.tycg.gov.tw",
        "has_dept": False,
    },
]

# ─── 分類規則 ─────────────────────────────────────────────────────────────────

DISTRICT_DEPT_CATEGORY = {
    "民政課":    "民政",
    "社會課":    "社會福利",
    "農業經濟課": "農業經濟",
    "農經課":    "農業經濟",   # 網站實際用名
    "文化課":    "文化活動",
    "人文課":    "文化活動",   # 網站實際用名
    "人事室":    "人事公告",
    "工務課":    "工程建設",
    "秘書室":    "行政公告",
    "政風室":    "行政公告",
    "財政課":    "財政稅務",
    "會計室":    "財政稅務",
    "地政課":    "地政",
    "公所":      "行政公告",
}

HRO_CATEGORY_RULES = [
    (["身分證", "戶籍", "戶口", "謄本", "遷入", "遷出", "遷徙", "門牌", "地址變更"],  "戶籍管理"),
    (["結婚", "離婚", "出生", "死亡", "收養", "認領", "監護", "生命事件"],           "生命事件"),
    (["假期", "休息", "服務時間", "暫停服務", "開放", "連假", "勞動節"],             "服務公告"),
    (["招募", "職缺", "面試", "甄選", "徵才", "招考", "約僱"],                      "人事公告"),
    (["原住民", "原民", "原名"],                                                    "原住民事務"),
    (["行政區域", "轄里", "轄鄰", "換發", "調整"],                                  "行政區域調整"),
    (["線上申請", "電子", "APP", "網路", "QR"],                                     "數位服務"),
]

TAG_PATTERNS = [
    "補助", "招募", "選舉", "投票", "學區", "公園", "停車", "交通",
    "捷運", "道路", "市場", "環境", "清潔", "衛生", "健康", "長照",
    "社福", "弱勢", "低收", "農業", "農民", "里長", "換發",
    "身分證", "戶籍", "戶口", "公告", "活動", "比賽", "表演", "展覽",
    "連假", "節日", "假期", "招考", "徵才", "職缺", "線上申請",
]

# ─── 輔助函式 ─────────────────────────────────────────────────────────────────

def roc_to_ad(roc_str: str):
    """民國年字串轉西元 date，'115-04-09' → date(2026, 4, 9)，失敗回 None。"""
    m = re.match(r"(\d{2,3})-(\d{2})-(\d{2})", (roc_str or "").strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def infer_category(title: str, department, source_site: str):
    """回傳 (category, sub_category)。"""
    if source_site == "bade_district":
        dept = department or ""
        for key, cat in DISTRICT_DEPT_CATEGORY.items():
            if key in dept:
                return cat, dept or None
        return "一般公告", dept or None

    for keywords, cat in HRO_CATEGORY_RULES:
        if any(kw in title for kw in keywords):
            return cat, None
    return "一般公告", None


def extract_tags(title: str):
    return [tag for tag in TAG_PATTERNS if tag in title] or None


def extract_news_id(href: str):
    """從 href 取出 s= 參數，找不到就用整個 path 末尾段。"""
    qs = parse_qs(urlparse(href).query)
    if "s" in qs:
        return qs["s"][0]
    # fallback：用 path 最後一段（部分站點 URL 不同）
    return urlparse(href).path.rstrip("/").split("/")[-1] or None

# ─── 爬蟲核心 ────────────────────────────────────────────────────────────────

def fetch_page(source: dict, page: int):
    """抓一頁列表，回傳 list of dict；失敗回空 list。"""
    url = f"{source['list_url']}&page={page}&PageSize={PAGE_SIZE}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20, verify=False)
        resp.encoding = "utf-8"
    except Exception as e:
        print(f"  ⚠️  頁 {page} 請求失敗：{e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    items = []

    # 桃園市政府 CMS：新聞列表在 <table>，每列 3 欄（日期、標題、發布單位）
    table = soup.find("table")
    if not table:
        return items

    rows = table.find_all("tr")
    for row in rows[1:]:           # 第 0 列是 thead
        cols = row.find_all("td")
        if len(cols) < 2:
            continue

        link_tag = row.find("a", href=True)
        if not link_tag:
            continue

        href     = link_tag["href"]
        news_id  = extract_news_id(href)
        if not news_id:
            continue

        title        = link_tag.get_text(strip=True)
        full_url     = urljoin(source["base_url"], href)
        date_raw     = cols[0].get_text(strip=True)
        department   = cols[-1].get_text(strip=True) if source["has_dept"] and len(cols) >= 3 else None

        items.append({
            "news_id":    news_id,
            "url":        full_url,
            "title":      title,
            "date_raw":   date_raw,
            "department": department or None,
        })

    return items


def get_total_pages(source: dict) -> int:
    """讀第 1 頁，解析分頁控制項取得總頁數；失敗回 1。"""
    url = f"{source['list_url']}&page=1&PageSize={PAGE_SIZE}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20, verify=False)
        resp.encoding = "utf-8"
    except Exception:
        return 1

    soup = BeautifulSoup(resp.text, "html.parser")

    # 找「第 1 / N 頁」或「共 N 頁」字樣
    for text in soup.stripped_strings:
        m = re.search(r"/\s*(\d+)\s*頁", text)
        if m:
            return int(m.group(1))

    # 備案：找分頁連結中最大的 page= 值
    max_page = 1
    for a in soup.find_all("a", href=True):
        m = re.search(r"[?&]page=(\d+)", a["href"])
        if m:
            max_page = max(max_page, int(m.group(1)))
    return max_page


def upsert_news(conn, item: dict, source: dict) -> bool:
    """寫入 gov_news；回傳 True=新增，False=重複略過。"""
    category, sub_category = infer_category(item["title"], item["department"], source["site"])
    tags          = extract_tags(item["title"])
    published_date = roc_to_ad(item["date_raw"])

    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO gov_news
               (source_site, source_name, news_id, url, title,
                department, published_date, published_raw,
                category, sub_category, tags, raw_json)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (source_site, news_id) DO NOTHING""",
            (
                source["site"],
                source["name"],
                item["news_id"],
                item["url"],
                item["title"],
                item["department"],
                published_date,
                item["date_raw"],
                category,
                sub_category,
                tags,
                json.dumps(item, ensure_ascii=False),
            ),
        )
    return cur.rowcount == 1

# ─── 主流程 ──────────────────────────────────────────────────────────────────

def run():
    conn   = get_db_connection()
    run_id = log_run_start(conn, SCRAPER_NAME)
    total_found = total_inserted = 0

    try:
        for source in SOURCES:
            print(f"\n🔍 {source['name']}")
            total_pages = get_total_pages(source)
            print(f"  → 偵測到 {total_pages} 頁")

            for page in range(1, total_pages + 1):
                items = fetch_page(source, page)
                if not items:
                    print(f"  頁 {page}：無資料，停止")
                    break

                page_inserted = 0
                for item in items:
                    total_found += 1
                    if upsert_news(conn, item, source):
                        total_inserted += 1
                        page_inserted += 1

                conn.commit()
                print(f"  頁 {page:>3}/{total_pages}：新增 {page_inserted:>3} 筆")

                # 增量更新：整頁都是舊資料 → 不需再往後翻
                if page > 1 and page_inserted == 0:
                    print(f"  → 已是最新，停止翻頁")
                    break

        log_run_finish(conn, run_id, "success", total_found, total_inserted)
        print(f"\n✅ 完成：掃描 {total_found} 筆，新增 {total_inserted} 筆")

    except Exception as e:
        log_run_finish(conn, run_id, "failed", total_found, total_inserted, str(e))
        print(f"\n❌ 失敗：{e}")
        raise

    finally:
        conn.close()


if __name__ == "__main__":
    run()
