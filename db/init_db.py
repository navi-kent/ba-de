"""初始化 PostgreSQL 資料庫。重複執行是安全的（CREATE TABLE/INDEX IF NOT EXISTS）。"""
import os
import psycopg2
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent.parent
load_dotenv(BASE_DIR / ".env")

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_conn():
    return psycopg2.connect(
        host=os.environ.get("PG_HOST", "127.0.0.1"),
        port=int(os.environ.get("PG_PORT", 5432)),
        user=os.environ.get("PG_USER", "bade_user"),
        password=os.environ.get("PG_PASSWORD", ""),
        dbname=os.environ.get("PG_DATABASE", "bade"),
    )


def init_db():
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema = f.read()

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(schema)
        conn.commit()

        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public' ORDER BY table_name
            """)
            tables = [row[0] for row in cur.fetchall()]
        print("✅ 資料庫已初始化")
        print(f"📋 已建立的表：{', '.join(tables)}")
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
