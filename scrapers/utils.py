"""爬蟲共用工具模組

所有爬蟲都 import 這個模組取得：
- 資料庫連線 (get_db_connection)
- 設定檔讀取 (load_search_config)
- 執行紀錄寫入 (log_run_start / log_run_finish)
"""
import os
import psycopg2
import psycopg2.extras
import yaml
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent.parent
SEARCH_CONFIG_PATH = BASE_DIR / "config" / "search_config.yaml"

load_dotenv(BASE_DIR / ".env")


def get_db_connection():
    """建立 PostgreSQL 資料庫連線，cursor 回傳 RealDictCursor（欄位名稱存取）。"""
    return psycopg2.connect(
        host=os.environ.get("PG_HOST", "127.0.0.1"),
        port=int(os.environ.get("PG_PORT", 5432)),
        user=os.environ.get("PG_USER", "bade_user"),
        password=os.environ.get("PG_PASSWORD", ""),
        dbname=os.environ.get("PG_DATABASE", "bade"),
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


def load_search_config():
    """讀取 config/search_config.yaml，回傳 dict；檔案不存在時回傳空 dict。"""
    if not SEARCH_CONFIG_PATH.exists():
        return {}
    with open(SEARCH_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def log_run_start(conn, scraper_name: str) -> int:
    """在 scraper_runs 寫入一筆「執行中」記錄，回傳 run_id 供後續更新用。"""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO scraper_runs (scraper_name, status) VALUES (%s, %s) RETURNING id",
            (scraper_name, "running"),
        )
        run_id = cur.fetchone()["id"]
    conn.commit()
    return run_id


def log_run_finish(conn, run_id: int, status: str, found: int, inserted: int, error=None):
    """更新 scraper_runs 執行結果（completed_at、status、筆數、錯誤訊息）。

    Args:
        status:   "success" 或 "failed"
        found:    符合過濾條件的文章數（不含略過的）
        inserted: 實際寫入 DB 的新增筆數（重複者不計）
        error:    失敗時的錯誤訊息字串
    """
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE scraper_runs
               SET finished_at = NOW(), status = %s,
                   items_found = %s, items_inserted = %s, error_message = %s
               WHERE id = %s""",
            (status, found, inserted, error, run_id),
        )
    conn.commit()
