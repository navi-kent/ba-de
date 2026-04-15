"""初始化 MySQL 資料庫。重複執行是安全的（CREATE TABLE IF NOT EXISTS）。"""
import os
import pymysql
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent.parent
load_dotenv(BASE_DIR / ".env")

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_conn():
    return pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "127.0.0.1"),
        port=int(os.environ.get("MYSQL_PORT", 3306)),
        user=os.environ.get("MYSQL_USER", "root"),
        password=os.environ.get("MYSQL_PASSWORD", ""),
        database=os.environ.get("MYSQL_DATABASE", "bade"),
        charset="utf8mb4",
        autocommit=True,
    )


def init_db():
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema = f.read()

    conn = get_conn()
    try:
        # 先移除所有註解行，再拆分語句
        schema_clean = "\n".join(
            line for line in schema.splitlines() if not line.strip().startswith("--")
        )
        statements = [s.strip() for s in schema_clean.split(";") if s.strip()]
        with conn.cursor() as cur:
            for stmt in statements:
                try:
                    cur.execute(stmt)
                except pymysql.err.OperationalError as e:
                    if e.args[0] == 1061:  # Duplicate key name（索引已存在）
                        print(f"ℹ️  索引已存在，略過")
                    else:
                        raise

        # 驗證：列出所有表
        with conn.cursor() as cur:
            cur.execute("SHOW TABLES")
            tables = [row[0] for row in cur.fetchall()]
        print(f"✅ 資料庫已初始化")
        print(f"📋 已建立的表：{', '.join(tables)}")
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
