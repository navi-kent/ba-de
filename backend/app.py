"""八德夢想家 - Flask 後端 API

架構說明：
- Flask 同時提供 API（/api/*）和靜態頁面（/、/news 等）
- 靜態 HTML 放在 frontend/，Flask 直接 serve（不需要 Nginx 也能跑）
- 資料庫連線每次 request 建立、用完關閉（不使用 connection pool，流量小不需要）
- 後台路由統一用 @require_admin 裝飾器驗證 Token
"""
import os
import re
import io
import csv
import time
import uuid
import hmac
import zipfile
import threading
import warnings
import xml.etree.ElementTree as ET
import psycopg2
import psycopg2.extras
import requests
from datetime import datetime, date
from functools import wraps
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).parent.parent
load_dotenv(BASE_DIR / ".env")

ADMIN_USER  = os.environ.get("ADMIN_USER", "")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "changeme")

FRONTEND_DIR = BASE_DIR / "frontend"
UPLOAD_DIR   = FRONTEND_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)  # 首次啟動自動建立，不需手動 mkdir

ALLOWED_EXTS = {"png", "jpg", "jpeg", "gif", "webp"}

# static_folder 指向 frontend/，讓 Flask 直接 serve HTML / CSS / JS / 圖片
app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path="")
limiter = Limiter(get_remote_address, app=app, default_limits=[])


@app.after_request
def add_no_index_header(response):
    """在所有回應加上 X-Robots-Tag，禁止搜尋引擎索引。

    統一在 after_request 處理，確保新增任何頁面都自動套用，
    不需要每個 route 個別設定。配合 frontend/robots.txt 雙重封鎖。
    """
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response


# source 代碼對應的顯示名稱，用於 API 回應的 source_label 欄位
SOURCE_LABELS = {
    "news":  "Google 新聞",
    "ptt":   "PTT",
    "dcard": "Dcard",
    "fb":    "Facebook",
    "gov":   "政府公告",
}

# ── 輕量 TTL 快取（民生資訊用，不需要 Redis）─────────────────────
_http_cache: dict = {}
_http_cache_lock = threading.Lock()

def _cache_get(key: str, ttl: int):
    with _http_cache_lock:
        entry = _http_cache.get(key)
        if entry and time.time() - entry[1] < ttl:
            return entry[0]
    return None

def _cache_set(key: str, data):
    with _http_cache_lock:
        _http_cache[key] = (data, time.time())

TAOYUAN_KW = ["桃園市","八德區","中壢區","蘆竹區","龜山區","大溪區","楊梅區","龍潭區","平鎮區","大園區","觀音區","復興區","南崁"]


# ── 工具函式 ─────────────────────────────────────────────────

def get_conn():
    """建立 PostgreSQL 連線，cursor 回傳 RealDictCursor（可用欄位名稱存取）。"""
    return psycopg2.connect(
        host=os.environ.get("PG_HOST", "127.0.0.1"),
        port=int(os.environ.get("PG_PORT", 5432)),
        user=os.environ.get("PG_USER", "bade_user"),
        password=os.environ.get("PG_PASSWORD", ""),
        dbname=os.environ.get("PG_DATABASE", "bade"),
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


def require_admin(f):
    """裝飾器：驗證 X-Admin-User 和 X-Admin-Token，兩者皆符合才放行。"""
    @wraps(f)
    def decorated(*args, **kwargs):
        user  = request.headers.get("X-Admin-User", "")
        token = request.headers.get("X-Admin-Token", "")
        user_ok  = ADMIN_USER  and hmac.compare_digest(user,  ADMIN_USER)
        token_ok = hmac.compare_digest(token, ADMIN_TOKEN) if token else False
        if not (user_ok and token_ok):
            return jsonify({"ok": False, "error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


def allowed_file(filename):
    """檢查副檔名是否在允許清單內（png / jpg / jpeg / gif / webp）。"""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTS


def auto_slug(title: str) -> str:
    """從標題自動產生 URL slug，末尾加 timestamp 確保唯一性。

    處理步驟：
    1. 轉小寫
    2. 保留中文、英數、底線、連字號，其餘換成 "-"
    3. 合併連續 "-"，去頭尾 "-"
    4. 截到 60 字元後加 Unix timestamp
    """
    slug = re.sub(r"[^\w\u4e00-\u9fff-]", "-", title.lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:60] + f"-{int(time.time())}"



def _parse_dt(s):
    """將 ISO 8601 字串解析為 datetime，無效輸入回傳 None。

    支援 "Z" 結尾（JavaScript 慣用格式），替換為 "+00:00" 再解析。
    """
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


# ── 靜態資源 ──────────────────────────────────────────────────

@app.route("/robots.txt")
def robots_txt():
    """明確 serve robots.txt，確保搜尋引擎爬蟲能找到並遵守。"""
    return send_from_directory(FRONTEND_DIR, "robots.txt", mimetype="text/plain")


@app.route("/healthz")
def healthz():
    """容器健康檢查：確認應用程式與資料庫連線正常。"""
    try:
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        finally:
            conn.close()
        return jsonify({"ok": True}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 503


# ── 前端靜態頁面 ──────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")

@app.route("/wish")
def wish_page():
    return send_from_directory(FRONTEND_DIR, "wish.html")

@app.route("/news")
def news_page():
    return send_from_directory(FRONTEND_DIR, "news.html")

@app.route("/news/<slug>")
def news_detail_page(slug):
    # slug 參數由前端 JS 從 URL 讀取，Flask 只需回傳同一份 HTML
    return send_from_directory(FRONTEND_DIR, "news-detail.html")

@app.route("/news-feed")
def news_feed_page():
    return send_from_directory(FRONTEND_DIR, "news-feed.html")

@app.route("/admin")
def admin_page():
    return send_from_directory(FRONTEND_DIR, "admin.html")


# ── 公開 API：跑馬燈 ─────────────────────────────────────────

def _dedupe_titles(items, threshold=0.75):
    """去除相似標題，只保留每個故事的第一篇。

    使用 difflib.SequenceMatcher 比對標題相似度，
    超過 threshold 視為同一則新聞，後者捨棄。
    資料庫資料不受影響。
    """
    from difflib import SequenceMatcher
    kept = []
    for item in items:
        title = item["title"]
        is_dup = any(
            SequenceMatcher(None, title, k["title"]).ratio() >= threshold
            for k in kept
        )
        if not is_dup:
            kept.append(item)
    return kept


@app.route("/api/ticker")
def api_ticker():
    """回傳近 5 天的文章標題清單，供首頁跑馬燈使用（最多 20 筆，去除相似標題）。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT title, url, source FROM raw_posts
                   WHERE published_at >= NOW() - INTERVAL '5 days'
                     AND title IS NOT NULL
                   ORDER BY published_at DESC
                   LIMIT 80"""
            )
            rows = cur.fetchall()
        items = [{"title": r["title"], "url": r["url"], "source": r["source"]} for r in rows]
        return jsonify(_dedupe_titles(items)[:20])
    finally:
        conn.close()


# ── 公開 API：最新消息 ────────────────────────────────────────

@app.route("/api/announcements")
def api_announcements():
    """最新消息列表（手動管理），支援分類篩選與分頁。

    Query params:
        category: 分類名稱，"all" 表示不篩選（預設）
        page:     頁碼，從 1 開始（預設 1）
        limit:    每頁筆數，上限 50（預設 12）

    Response: { items, total, page, limit, total_pages, has_next, categories }
    """
    category = request.args.get("category", "all")
    page     = max(1, int(request.args.get("page", 1)))
    limit    = min(int(request.args.get("limit", 12)), 50)
    offset   = (page - 1) * limit

    conn = get_conn()
    try:
        where  = ["is_published = TRUE", "published_at <= NOW()"]
        params = []
        if category != "all":
            where.append("category = %s")
            params.append(category)
        where_sql = "WHERE " + " AND ".join(where)

        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) as cnt FROM announcements {where_sql}", params)
            total = cur.fetchone()["cnt"]

            cur.execute(
                f"""SELECT id, title, slug, category, summary, cover_image, published_at, updated_at
                    FROM announcements {where_sql}
                    ORDER BY published_at DESC LIMIT %s OFFSET %s""",
                params + [limit, offset],
            )
            rows = cur.fetchall()

            # 同時回傳所有已使用的分類，供前端 tab 篩選器使用
            cur.execute(
                """SELECT DISTINCT category FROM announcements
                   WHERE is_published = TRUE AND category IS NOT NULL
                   ORDER BY category"""
            )
            categories = [r["category"] for r in cur.fetchall()]

        return jsonify({
            "items": [
                {
                    "id":           r["id"],
                    "title":        r["title"],
                    "slug":         r["slug"],
                    "category":     r["category"],
                    "summary":      r["summary"],
                    "cover_image":  r["cover_image"],
                    "published_at": r["published_at"].isoformat() if r["published_at"] else None,
                    "updated_at":   r["updated_at"].isoformat() if r["updated_at"] else None,
                }
                for r in rows
            ],
            "total":       total,
            "page":        page,
            "limit":       limit,
            "total_pages": max(1, (total + limit - 1) // limit),
            "has_next":    offset + limit < total,
            "categories":  categories,
        })
    finally:
        conn.close()


@app.route("/api/announcements/<slug>")
def api_announcement_detail(slug):
    """取得單篇最新消息完整內容（含 Quill HTML content）。

    只回傳已發佈且發佈時間 <= 現在的文章（預排文章尚未到期不顯示）。
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, title, slug, category, summary, content,
                          meta_description, cover_image, published_at, updated_at
                   FROM announcements
                   WHERE slug = %s AND is_published = TRUE AND published_at <= NOW()""",
                (slug,),
            )
            row = cur.fetchone()
        if not row:
            return jsonify({"ok": False, "error": "Not found"}), 404
        return jsonify({
            "id":               row["id"],
            "title":            row["title"],
            "slug":             row["slug"],
            "category":         row["category"],
            "summary":          row["summary"],
            "content":          row["content"],
            "meta_description": row["meta_description"],
            "cover_image":      row["cover_image"],
            "published_at":     row["published_at"].isoformat() if row["published_at"] else None,
            "updated_at":       row["updated_at"].isoformat() if row["updated_at"] else None,
        })
    finally:
        conn.close()


# ── 公開 API：訪客計數 ───────────────────────────────────────

VISITOR_BASE = 10000  # 顯示數字 = COUNT(*) + VISITOR_BASE，基數 10000

@app.route("/api/visit", methods=["POST"])
def api_visit():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO visitors DEFAULT VALUES")
            conn.commit()
            cur.execute("SELECT COUNT(*) as cnt FROM visitors")
            total = cur.fetchone()["cnt"] + VISITOR_BASE
        return jsonify({"ok": True, "total": total})
    finally:
        conn.close()


# ── 公開 API：許願池 ─────────────────────────────────────────

@app.route("/api/wish", methods=["POST"])
@limiter.limit("5 per minute; 20 per hour")
def api_wish():
    """接收許願表單，寫入 DB 並嘗試發送 email 通知。

    Request body (JSON):
        name:    暱稱（選填，最多 50 字）
        contact: 聯絡方式（選填，最多 100 字）
        content: 許願內容（必填，最多 1000 字）

    Response: { ok, email_sent }
    email 發送失敗不影響 ok 狀態（DB 寫入成功即 ok=True）。
    """
    import re as _re
    data     = request.get_json(silent=True) or {}
    name     = (data.get("name")     or "").strip()[:50]
    email    = (data.get("email")    or "").strip()[:100]
    line_id  = (data.get("line_id")  or "").strip()[:100]
    phone    = (data.get("phone")    or "").strip()[:20]
    content  = (data.get("content")  or "").strip()[:1000]
    category = (data.get("category") or "合作提案").strip()[:30]

    valid_categories = {"合作提案", "平台功能許願"}
    if category not in valid_categories:
        category = "合作提案"

    if not email:
        return jsonify({"ok": False, "error": "請填寫 Email"}), 400
    if not _re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email):
        return jsonify({"ok": False, "error": "Email 格式不正確"}), 400
    if not content:
        return jsonify({"ok": False, "error": "請填寫內容"}), 400
    if phone and not _re.match(r'^\d{6,15}$', phone):
        return jsonify({"ok": False, "error": "電話格式不正確，請填入數字"}), 400

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO wishes (name, email, line_id, phone, category, content, ip) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (name or None, email, line_id or None, phone or None, category, content, request.remote_addr),
            )
        conn.commit()
    finally:
        conn.close()

    return jsonify({"ok": True})


# ── 公開 API：統計 + 新聞消息 ────────────────────────────────

@app.route("/api/stats")
def api_stats():
    """回傳統計資料，供首頁 Dashboard 顯示。

    Response:
        total:        raw_posts 總筆數
        today:        今日爬取筆數
        sources:      各來源筆數（source, label, cnt）
        topics:       Google 新聞熱門關鍵字 top 15（排除里長相關）
        last_updated: 最後一次爬蟲時間
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) as cnt FROM raw_posts")
            total = cur.fetchone()["cnt"]

            cur.execute("SELECT COUNT(*) as cnt FROM raw_posts WHERE scraped_at::date = CURRENT_DATE")
            today = cur.fetchone()["cnt"]

            cur.execute("SELECT source, COUNT(*) as cnt FROM raw_posts GROUP BY source ORDER BY cnt DESC")
            sources = cur.fetchall()

            # 熱門議題：Google 新聞的 source_account 就是搜尋關鍵字，統計次數即代表該議題文章數
            # 排除里長相關（已從爬蟲設定移除，DB 留有舊資料）
            cur.execute(
                """SELECT source_account, COUNT(*) as cnt
                   FROM raw_posts WHERE source = 'news'
                     AND source_account NOT LIKE '%里長%'
                   GROUP BY source_account ORDER BY cnt DESC LIMIT 15"""
            )
            topics = cur.fetchall()

            cur.execute("SELECT TO_CHAR(MAX(scraped_at), 'YYYY-MM-DD HH24:MI') as lu FROM raw_posts")
            last_updated = cur.fetchone()["lu"]

            cur.execute("SELECT COUNT(*) as cnt FROM wishes")
            wish_total = cur.fetchone()["cnt"]

        def clean_label(s):
            """移除搜尋關鍵字中的所有引號，回傳易讀標籤。"""
            return s.replace('"', '').strip() if s else s

        return jsonify({
            "total":        total,
            "today":        today,
            "sources":      [{"source": r["source"], "label": SOURCE_LABELS.get(r["source"], r["source"]), "cnt": r["cnt"]} for r in sources],
            "topics":       [{"keyword": r["source_account"], "label": clean_label(r["source_account"]), "cnt": r["cnt"]} for r in topics],
            "last_updated": last_updated,
            "wish_total":   wish_total,
        })
    finally:
        conn.close()


@app.route("/api/posts")
def api_posts():
    """新聞消息列表，支援多維度篩選與分頁。

    Query params:
        source: 來源代碼（news / ptt / dcard / fb / gov），"all" 不篩選
        q:      關鍵字搜尋（標題或內文 LIKE）
        topic:  source_account 精確匹配（對應 Google 新聞搜尋關鍵字）
        month:  年月篩選，格式 "YYYY-MM"，"all" 不篩選
        page:   頁碼，從 1 開始（預設 1）
        limit:  每頁筆數，上限 200（預設 20）

    Response: { posts, total, page, limit, total_pages, has_next }
    content 欄位截至 150 字（列表頁不需全文）。
    """
    source = request.args.get("source", "all")
    q      = request.args.get("q", "").strip()
    topic  = request.args.get("topic", "all")
    month  = request.args.get("month", "all")
    media  = request.args.get("media", "all")
    limit  = min(int(request.args.get("limit", 20)), 200)
    page   = max(1, int(request.args.get("page", 1)))
    offset = (page - 1) * limit

    conn = get_conn()
    try:
        # 動態組裝 WHERE 條件，只加有值的篩選項
        where_clauses, params = [], []

        if source != "all":
            where_clauses.append("source = %s")
            params.append(source)
        if q:
            where_clauses.append("(title LIKE %s OR content LIKE %s)")
            params.extend([f"%{q}%", f"%{q}%"])
        if month != "all":
            where_clauses.append("TO_CHAR(published_at, 'YYYY-MM') = %s")
            params.append(month)
        if topic != "all":
            where_clauses.append("source_account = %s")
            params.append(topic)
        if media != "all":
            where_clauses.append("author = %s")
            params.append(media)

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) as cnt FROM raw_posts {where_sql}", params)
            count = cur.fetchone()["cnt"]

            cur.execute(
                f"""SELECT id, source, source_account, author, title, content, url, published_at, scraped_at
                    FROM raw_posts {where_sql}
                    ORDER BY published_at DESC, scraped_at DESC
                    LIMIT %s OFFSET %s""",
                params + [limit, offset],
            )
            rows = cur.fetchall()

        total_pages = max(1, (count + limit - 1) // limit)
        return jsonify({
            "posts": [
                {
                    "id":             r["id"],
                    "source":         r["source"],
                    "source_label":   SOURCE_LABELS.get(r["source"], r["source"]),
                    "source_account": (r["source_account"] or "").replace('"', '').strip() or None,
                    "media":          r["author"] or None,
                    "title":          r["title"] or "（無標題）",
                    "content":        (r["content"] or "")[:150],
                    "url":            r["url"],
                    "published_at":   r["published_at"].isoformat() if r["published_at"] else None,
                    "scraped_at":     r["scraped_at"].isoformat() if r["scraped_at"] else None,
                }
                for r in rows
            ],
            "total":       count,
            "page":        page,
            "limit":       limit,
            "total_pages": total_pages,
            "has_next":    offset + limit < count,
        })
    finally:
        conn.close()


@app.route("/api/media-list")
def api_media_list():
    """新聞媒體平台清單，依文章數量排序。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT author AS name, COUNT(*) AS cnt
                FROM raw_posts
                WHERE source = 'news' AND author IS NOT NULL AND author != ''
                GROUP BY author
                ORDER BY cnt DESC
                LIMIT 30
            """)
            rows = cur.fetchall()
        return jsonify({"media": [{"name": r["name"], "count": r["cnt"]} for r in rows]})
    finally:
        conn.close()


@app.route("/api/gov-news")
def api_gov_news():
    """政府官網最新消息列表（gov_news 表）。

    Query params:
        source:   bade_district（公所）| bade_hro（戶政）| all
        category: 主分類篩選，"all" 不篩選
        q:        關鍵字搜尋（標題 LIKE）
        month:    年月篩選，格式 "YYYY-MM"，"all" 不篩選
        page:     頁碼，從 1 開始（預設 1）
        limit:    每頁筆數，上限 200（預設 20）
    """
    source   = request.args.get("source", "all")
    category = request.args.get("category", "all")
    q        = request.args.get("q", "").strip()
    month    = request.args.get("month", "all")
    limit    = min(int(request.args.get("limit", 20)), 200)
    page     = max(1, int(request.args.get("page", 1)))
    offset   = (page - 1) * limit

    conn = get_conn()
    try:
        where_clauses, params = [], []
        if source != "all":
            where_clauses.append("source_site = %s")
            params.append(source)
        if category != "all":
            where_clauses.append("category = %s")
            params.append(category)
        if q:
            where_clauses.append("title LIKE %s")
            params.append(f"%{q}%")
        if month != "all":
            where_clauses.append("TO_CHAR(published_date, 'YYYY-MM') = %s")
            params.append(month)

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) as cnt FROM gov_news {where_sql}", params)
            count = cur.fetchone()["cnt"]

            cur.execute(
                f"""SELECT id, source_site, source_name, title, url,
                           department, category, published_date, scraped_at
                    FROM gov_news {where_sql}
                    ORDER BY published_date DESC, scraped_at DESC
                    LIMIT %s OFFSET %s""",
                params + [limit, offset],
            )
            rows = cur.fetchall()

        SOURCE_SITE_LABELS = {
            "bade_district": "公所公告",
            "bade_hro":      "戶政公告",
        }
        total_pages = max(1, (count + limit - 1) // limit)
        return jsonify({
            "posts": [
                {
                    "id":           r["id"],
                    "source":       r["source_site"],
                    "source_label": SOURCE_SITE_LABELS.get(r["source_site"], r["source_name"]),
                    "media":        r["department"] or r["category"] or None,
                    "title":        r["title"] or "（無標題）",
                    "content":      "",
                    "url":          r["url"],
                    "published_at": r["published_date"].isoformat() if r["published_date"] else None,
                    "scraped_at":   r["scraped_at"].isoformat() if r["scraped_at"] else None,
                }
                for r in rows
            ],
            "total":       count,
            "page":        page,
            "limit":       limit,
            "total_pages": total_pages,
            "has_next":    offset + limit < count,
        })
    finally:
        conn.close()


# ── 民生資訊 API ──────────────────────────────────────────────

@app.route("/api/water-alerts")
def api_water_alerts():
    """桃園市停水通知：NCDR 民生示警，以 summary 過濾含桃園地名的項目。

    每 30 分鐘更新一次快取；回傳格式：{alerts: [...], fetched_at: float}
    """
    cached = _cache_get("water_alerts", 1800)
    if cached is not None:
        return jsonify(cached)

    try:
        resp = requests.get(
            "https://alerts.ncdr.nat.gov.tw/JSONAtomFeeds.ashx",
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0 (Ba-de)"},
        )
        entries = resp.json().get("entry", [])

        water_entries = [
            e for e in entries
            if e.get("category", {}).get("@term") == "停水"
        ]

        now = datetime.now()

        def _parse_expires(s: str):
            try:
                s = s.replace("上午", "AM").replace("下午", "PM")
                return datetime.strptime(s, "%Y/%m/%d %p %I:%M:%S")
            except Exception:
                return None

        results = []
        for e in water_entries:
            summary = e.get("summary", {}).get("#text", "")
            if not any(kw in summary for kw in TAOYUAN_KW):
                continue
            exp_dt = _parse_expires(e.get("expires", ""))
            if exp_dt and exp_dt < now:
                continue  # 已過期，略過
            results.append({
                "description": summary,
                "expires":     e.get("expires", ""),
                "updated":     e.get("updated", ""),
                "link":        e.get("link", {}).get("@href", ""),
            })

        payload = {"alerts": results, "fetched_at": time.time()}
        _cache_set("water_alerts", payload)
        return jsonify(payload)

    except Exception as ex:
        return jsonify({"alerts": [], "error": str(ex), "fetched_at": 0}), 200


@app.route("/api/power-outage")
def api_power_outage():
    """台電桃園計畫停電：下載每日 ZIP → 解析 103.csv（桃園區處）。

    優先顯示 八德區 範圍；若無則顯示全桃園當日起未來 7 天，上限 20 筆。
    每 4 小時更新一次快取（台電一天最多更新 2–3 次）。
    SSL 憑證缺少 Subject Key Identifier，使用 verify=False。
    """
    cached = _cache_get("power_outage", 14400)
    if cached is not None:
        return jsonify(cached)

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            resp = requests.get(
                "https://service.taipower.com.tw/data/opendata/apply/file/d077004/001.zip",
                timeout=30,
                headers={"User-Agent": "Mozilla/5.0 (Ba-de)"},
                verify=False,
            )

        today = date.today()
        cutoff = today.isoformat()

        def parse_start_date(time_str: str):
            try:
                return datetime.strptime(time_str.split(" ")[0], "%Y/%m/%d").date()
            except Exception:
                return None

        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            raw = zf.read("103.csv").decode("utf-8-sig", errors="replace")

        reader = csv.DictReader(io.StringIO(raw))
        all_rows = list(reader)

        upcoming = [
            r for r in all_rows
            if (d := parse_start_date(r.get("第一次停電時間", ""))) and d >= today
        ]

        bade = [r for r in upcoming if "八德" in r.get("停電範圍", "")]
        rows = bade if bade else upcoming

        results = [
            {
                "scope":       r.get("停電範圍", ""),
                "description": r.get("工作概述", ""),
                "time1":       r.get("第一次停電時間", ""),
                "time2":       r.get("第二次停電時間", ""),
                "phone":       "1911",
            }
            for r in rows[:20]
        ]

        payload = {"outages": results, "fetched_at": time.time(), "source": "bade" if bade else "taoyuan"}
        _cache_set("power_outage", payload)
        return jsonify(payload)

    except Exception as ex:
        return jsonify({"outages": [], "error": str(ex), "fetched_at": 0}), 200


@app.route("/api/garbage-spots")
def api_garbage_spots():
    """八德區垃圾定點收受點：爬取桃園市環境管理處頁面。

    此資料幾乎不變動，快取 24 小時。
    SSL 憑證同樣缺少 Subject Key Identifier，使用 verify=False。
    """
    cached = _cache_get("garbage_spots", 86400)
    if cached is not None:
        return jsonify(cached)

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            resp = requests.get(
                "https://tyoem.tycg.gov.tw/News_Content.aspx?n=21967&s=1594431",
                timeout=15,
                headers={"User-Agent": "Mozilla/5.0 (Ba-de)"},
                verify=False,
            )

        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table")
        spots = []

        if table:
            rows = table.find_all("tr")
            for row in rows[1:]:  # skip header
                cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
                if len(cells) >= 5:
                    spots.append({
                        "no":       cells[0],
                        "district": cells[1],
                        "name":     cells[2],
                        "address":  cells[3],
                        "hours":    cells[4],
                        "days":     cells[5] if len(cells) > 5 else "",
                    })

        payload = {"spots": spots, "fetched_at": time.time()}
        _cache_set("garbage_spots", payload)
        return jsonify(payload)

    except Exception as ex:
        return jsonify({"spots": [], "error": str(ex), "fetched_at": 0}), 200


@app.route("/api/power-realtime")
def api_power_realtime():
    """台電即時停電：爬取 outageweb SSR 頁面（data-value 屬性），篩選桃園市。

    頁面每 5 分鐘更新一次，快取設 5 分鐘。
    SSL 憑證問題同上，verify=False。
    """
    cached = _cache_get("power_realtime", 300)
    if cached is not None:
        return jsonify(cached)

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            resp = requests.get(
                "https://service.taipower.com.tw/psvs1/outageweb/",
                timeout=15,
                headers={"User-Agent": "Mozilla/5.0 (Ba-de)"},
                verify=False,
            )

        soup = BeautifulSoup(resp.text, "html.parser")
        outages = []

        for tr in soup.select("tbody tr"):
            row = {
                td["data-key"]: td.get("data-value", td.get_text(strip=True))
                for td in tr.find_all("td", attrs={"data-key": True})
            }
            if not row:
                continue
            area = row.get("OutageRange", "")
            if "桃園" not in area:
                continue
            outages.append({
                "area":          area,
                "reason":        row.get("Reason", ""),
                "occur_time":    row.get("OccurTime", ""),
                "restore_time":  row.get("PreBackTime", ""),
                "count":         row.get("NowCount", "0"),
            })

        payload = {"outages": outages, "fetched_at": time.time()}
        _cache_set("power_realtime", payload)
        return jsonify(payload)

    except Exception as ex:
        return jsonify({"outages": [], "error": str(ex), "fetched_at": 0}), 200


# ── 後台 API：最新消息 CRUD ───────────────────────────────────

@app.route("/api/admin/announcements", methods=["GET"])
@require_admin
def admin_list_announcements():
    """後台：取得所有消息列表（含草稿），每頁 20 筆。"""
    page   = max(1, int(request.args.get("page", 1)))
    limit  = 20
    offset = (page - 1) * limit

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) as cnt FROM announcements")
            total = cur.fetchone()["cnt"]

            cur.execute(
                """SELECT id, title, slug, category, is_published, published_at, updated_at, created_at
                   FROM announcements ORDER BY created_at DESC LIMIT %s OFFSET %s""",
                (limit, offset),
            )
            rows = cur.fetchall()

        return jsonify({
            "items": [
                {
                    "id":           r["id"],
                    "title":        r["title"],
                    "slug":         r["slug"],
                    "category":     r["category"],
                    "is_published": r["is_published"],
                    "published_at": r["published_at"].isoformat() if r["published_at"] else None,
                    "updated_at":   r["updated_at"].isoformat() if r["updated_at"] else None,
                    "created_at":   r["created_at"].isoformat() if r["created_at"] else None,
                }
                for r in rows
            ],
            "total":       total,
            "page":        page,
            "total_pages": max(1, (total + limit - 1) // limit),
        })
    finally:
        conn.close()


@app.route("/api/admin/announcements/<int:aid>", methods=["GET"])
@require_admin
def admin_get_announcement(aid):
    """後台：取得單篇消息完整資料（含 content HTML，供編輯器載入）。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM announcements WHERE id = %s", (aid,))
            row = cur.fetchone()
        if not row:
            return jsonify({"ok": False, "error": "Not found"}), 404
        # datetime 欄位序列化為 ISO 字串
        d = dict(row)
        for k in ("published_at", "updated_at", "created_at"):
            if d.get(k):
                d[k] = d[k].isoformat()
        return jsonify(d)
    finally:
        conn.close()


@app.route("/api/admin/announcements", methods=["POST"])
@require_admin
def admin_create_announcement():
    """後台：新增消息。slug 未填時從標題自動產生。

    Request body (JSON): title（必填）, slug, category, summary, content,
                         meta_description, cover_image, is_published, published_at
    """
    data        = request.get_json(silent=True) or {}
    title       = (data.get("title") or "").strip()
    if not title:
        return jsonify({"ok": False, "error": "標題為必填"}), 400

    slug        = (data.get("slug") or "").strip() or auto_slug(title)
    category    = (data.get("category") or "一般").strip()[:50]
    summary     = (data.get("summary") or "").strip()
    content     = data.get("content") or ""
    meta_desc   = (data.get("meta_description") or "").strip()
    cover_image = (data.get("cover_image") or "").strip()
    is_pub      = bool(data.get("is_published", False))
    published_at = _parse_dt(data.get("published_at")) or datetime.now()

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO announcements
                   (title, slug, category, summary, content, meta_description, cover_image, is_published, published_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (title, slug, category, summary, content, meta_desc, cover_image, is_pub, published_at),
            )
            new_id = cur.fetchone()["id"]
        conn.commit()
        return jsonify({"ok": True, "id": new_id, "slug": slug})
    except Exception as e:
        conn.rollback()
        if "unique" in str(e).lower():
            return jsonify({"ok": False, "error": "此網址已存在，請換一個"}), 409
        print(f"[admin] create announcement error: {e}")
        return jsonify({"ok": False, "error": "伺服器錯誤，請稍後再試"}), 500
    finally:
        conn.close()


@app.route("/api/admin/announcements/<int:aid>", methods=["PUT"])
@require_admin
def admin_update_announcement(aid):
    """後台：更新消息。published_at 未傳時保留原值（COALESCE）。"""
    data        = request.get_json(silent=True) or {}
    title       = (data.get("title") or "").strip()
    if not title:
        return jsonify({"ok": False, "error": "標題為必填"}), 400

    slug        = (data.get("slug") or "").strip()
    category    = (data.get("category") or "一般").strip()[:50]
    summary     = (data.get("summary") or "").strip()
    content     = data.get("content") or ""
    meta_desc   = (data.get("meta_description") or "").strip()
    cover_image = (data.get("cover_image") or "").strip()
    is_pub      = bool(data.get("is_published", False))
    published_at = _parse_dt(data.get("published_at"))

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE announcements SET
                   title=%s, slug=%s, category=%s, summary=%s, content=%s,
                   meta_description=%s, cover_image=%s, is_published=%s,
                   published_at=COALESCE(%s, published_at), updated_at=NOW()
                   WHERE id=%s""",
                (title, slug, category, summary, content, meta_desc, cover_image,
                 is_pub, published_at, aid),
            )
        conn.commit()
        return jsonify({"ok": True})
    except Exception as e:
        conn.rollback()
        if "unique" in str(e).lower():
            return jsonify({"ok": False, "error": "此網址已存在，請換一個"}), 409
        print(f"[admin] update announcement error: {e}")
        return jsonify({"ok": False, "error": "伺服器錯誤，請稍後再試"}), 500
    finally:
        conn.close()


@app.route("/api/admin/announcements/<int:aid>", methods=["DELETE"])
@require_admin
def admin_delete_announcement(aid):
    """後台：刪除消息（硬刪除，無法復原）。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM announcements WHERE id = %s", (aid,))
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


# ── 後台 API：許願池管理 ─────────────────────────────────────

@app.route("/api/admin/wishes", methods=["GET"])
@require_admin
def admin_list_wishes():
    """後台：取得許願池留言列表，每頁 20 筆，最新在前。"""
    page   = max(1, int(request.args.get("page", 1)))
    limit  = 20
    offset = (page - 1) * limit

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) as cnt FROM wishes")
            total = cur.fetchone()["cnt"]

            cur.execute(
                """SELECT id, name, email, line_id, phone, category, content, ip, created_at
                   FROM wishes ORDER BY created_at DESC LIMIT %s OFFSET %s""",
                (limit, offset),
            )
            rows = cur.fetchall()

        return jsonify({
            "items": [
                {
                    "id":         r["id"],
                    "name":       r["name"],
                    "email":      r["email"],
                    "line_id":    r["line_id"],
                    "phone":      r["phone"],
                    "category":   r["category"],
                    "content":    r["content"],
                    "ip":         r["ip"],
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                }
                for r in rows
            ],
            "total":       total,
            "page":        page,
            "total_pages": max(1, (total + limit - 1) // limit),
        })
    finally:
        conn.close()


@app.route("/api/admin/wishes/<int:wid>", methods=["DELETE"])
@require_admin
def admin_delete_wish(wid):
    """後台：刪除單筆許願池留言。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM wishes WHERE id = %s", (wid,))
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


# ── 後台 API：圖片上傳 ────────────────────────────────────────

@app.route("/api/admin/upload", methods=["POST"])
@require_admin
def admin_upload():
    """後台：上傳圖片到 frontend/uploads/，回傳可直接使用的 URL。

    檔名改為 UUID 避免衝突與目錄遍歷攻擊。
    """
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "No file"}), 400
    f = request.files["file"]
    if not f.filename or not allowed_file(f.filename):
        return jsonify({"ok": False, "error": "不支援的格式（支援：jpg, png, gif, webp）"}), 400
    ext      = f.filename.rsplit(".", 1)[1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"  # UUID 命名，避免原始檔名衝突或路徑注入
    f.save(UPLOAD_DIR / filename)
    return jsonify({"ok": True, "url": f"/uploads/{filename}"})


if __name__ == "__main__":
    print("🚀 八德夢想家啟動中... http://127.0.0.1:5001")
    app.run(debug=False, port=5001)
