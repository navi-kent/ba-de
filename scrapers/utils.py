import os
import pymysql
import pymysql.cursors
import yaml
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent.parent
SEARCH_CONFIG_PATH = BASE_DIR / "config" / "search_config.yaml"

load_dotenv(BASE_DIR / ".env")


def get_db_connection():
    """建立 MySQL 資料庫連線"""
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


def load_search_config():
    """讀取搜尋策略設定檔"""
    if not SEARCH_CONFIG_PATH.exists():
        return {}
    with open(SEARCH_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def log_run_start(conn, scraper_name: str) -> int:
    """記錄爬蟲開始執行，回傳 run_id"""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO scraper_runs (scraper_name, status) VALUES (%s, %s)",
            (scraper_name, "running"),
        )
        run_id = cur.lastrowid
    conn.commit()
    return run_id


def log_run_finish(conn, run_id: int, status: str, found: int, inserted: int, error=None):
    """更新爬蟲執行結果"""
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE scraper_runs
               SET finished_at = NOW(), status = %s,
                   items_found = %s, items_inserted = %s, error_message = %s
               WHERE id = %s""",
            (status, found, inserted, error, run_id),
        )
    conn.commit()
