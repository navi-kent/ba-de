"""八德夢想家 - Flask 後端 API
使用方式：python backend/app.py
"""
import os
import pymysql
import pymysql.cursors
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent.parent
load_dotenv(BASE_DIR / ".env")

WISH_RECIPIENT = os.environ.get("WISH_RECIPIENT_EMAIL", "")
SMTP_HOST      = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT      = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER      = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD  = os.environ.get("SMTP_PASSWORD", "")

FRONTEND_DIR = BASE_DIR / "frontend"

app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path="")

SOURCE_LABELS = {
    "news":  "Google 新聞",
    "ptt":   "PTT",
    "dcard": "Dcard",
    "fb":    "Facebook",
    "gov":   "政府公告",
}


def get_conn():
    return pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "127.0.0.1"),
        port=int(os.environ.get("MYSQL_PORT", 3306)),
        user=os.environ.get("MYSQL_USER", "root"),
        password=os.environ.get("MYSQL_PASSWORD", ""),
        database=os.environ.get("MYSQL_DATABASE", "bade"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


def send_wish_email(name: str, contact: str, content: str):
    if not (WISH_RECIPIENT and SMTP_USER and SMTP_PASSWORD):
        return False
    msg = MIMEMultipart()
    msg["From"]    = SMTP_USER
    msg["To"]      = WISH_RECIPIENT
    msg["Subject"] = "【八德夢想家】新許願"
    body = (
        f"來自用戶的許願\n\n"
        f"暱稱：{name or '（未填寫）'}\n"
        f"聯絡方式：{contact or '（未填寫）'}\n\n"
        f"許願內容：\n{content}\n\n"
        f"---\n此信件由八德夢想家自動發送"
    )
    msg.attach(MIMEText(body, "plain", "utf-8"))
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)
    return True


# ── 前端靜態頁面 ────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")

@app.route("/wish")
def wish_page():
    return send_from_directory(FRONTEND_DIR, "wish.html")


# ── API ─────────────────────────────────────────────────────

@app.route("/api/wish", methods=["POST"])
def api_wish():
    data    = request.get_json(silent=True) or {}
    name    = (data.get("name")    or "").strip()[:50]
    contact = (data.get("contact") or "").strip()[:100]
    content = (data.get("content") or "").strip()[:1000]

    if not content:
        return jsonify({"ok": False, "error": "請填寫許願內容"}), 400

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO wishes (name, contact, content, ip) VALUES (%s, %s, %s, %s)",
                (name or None, contact or None, content, request.remote_addr),
            )
        conn.commit()
    finally:
        conn.close()

    email_sent = False
    try:
        email_sent = send_wish_email(name, contact, content)
    except Exception as e:
        print(f"[wish] email 發送失敗: {e}")

    return jsonify({"ok": True, "email_sent": email_sent})


@app.route("/api/stats")
def api_stats():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) as cnt FROM raw_posts")
            total = cur.fetchone()["cnt"]

            cur.execute("SELECT COUNT(*) as cnt FROM raw_posts WHERE DATE(scraped_at) = CURDATE()")
            today = cur.fetchone()["cnt"]

            cur.execute(
                "SELECT source, COUNT(*) as cnt FROM raw_posts GROUP BY source ORDER BY cnt DESC"
            )
            sources = cur.fetchall()

            cur.execute(
                """SELECT source_account, COUNT(*) as cnt
                   FROM raw_posts WHERE source = 'news'
                     AND source_account NOT LIKE '%里長%'
                   GROUP BY source_account ORDER BY cnt DESC LIMIT 15"""
            )
            topics = cur.fetchall()

            cur.execute(
                "SELECT DATE_FORMAT(MAX(scraped_at), '%Y-%m-%d %H:%i') as last_updated FROM raw_posts"
            )
            last_updated = cur.fetchone()["last_updated"]

        return jsonify({
            "total": total,
            "today": today,
            "sources": [
                {"source": r["source"], "label": SOURCE_LABELS.get(r["source"], r["source"]), "cnt": r["cnt"]}
                for r in sources
            ],
            "topics": [{"keyword": r["source_account"], "cnt": r["cnt"]} for r in topics],
            "last_updated": last_updated,
        })
    finally:
        conn.close()


@app.route("/api/posts")
def api_posts():
    source = request.args.get("source", "all")
    q      = request.args.get("q", "").strip()
    topic  = request.args.get("topic", "all")
    month  = request.args.get("month", "all")
    limit  = min(int(request.args.get("limit", 50)), 200)
    page   = int(request.args.get("page", 1))
    offset = (page - 1) * limit

    conn = get_conn()
    try:
        where_clauses = []
        params = []

        if source != "all":
            where_clauses.append("source = %s")
            params.append(source)

        if q:
            where_clauses.append("(title LIKE %s OR content LIKE %s)")
            params.extend([f"%{q}%", f"%{q}%"])

        if month != "all":
            where_clauses.append("DATE_FORMAT(published_at, '%%Y-%%m') = %s")
            params.append(month)

        if topic != "all":
            where_clauses.append("source_account = %s")
            params.append(topic)

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) as cnt FROM raw_posts {where_sql}", params)
            count = cur.fetchone()["cnt"]

            cur.execute(
                f"""SELECT id, source, source_account, title, content, url, published_at, scraped_at
                    FROM raw_posts {where_sql}
                    ORDER BY published_at DESC, scraped_at DESC
                    LIMIT %s OFFSET %s""",
                params + [limit, offset],
            )
            rows = cur.fetchall()

        posts = [
            {
                "id":             r["id"],
                "source":         r["source"],
                "source_label":   SOURCE_LABELS.get(r["source"], r["source"]),
                "source_account": r["source_account"],
                "title":          r["title"] or "（無標題）",
                "content":        (r["content"] or "")[:150],
                "url":            r["url"],
                "published_at":   r["published_at"].isoformat() if r["published_at"] else None,
                "scraped_at":     r["scraped_at"].isoformat() if r["scraped_at"] else None,
            }
            for r in rows
        ]

        return jsonify({
            "posts":    posts,
            "total":    count,
            "page":     page,
            "limit":    limit,
            "has_next": offset + limit < count,
        })
    finally:
        conn.close()


if __name__ == "__main__":
    print("🚀 八德夢想家啟動中... http://127.0.0.1:5001")
    app.run(debug=False, port=5001)
