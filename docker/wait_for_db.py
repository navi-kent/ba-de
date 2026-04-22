import os
import time

import psycopg2


MAX_ATTEMPTS = int(os.environ.get("DB_WAIT_MAX_ATTEMPTS", "30"))
SLEEP_SECONDS = float(os.environ.get("DB_WAIT_SECONDS", "2"))


def main():
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            conn = psycopg2.connect(
                host=os.environ.get("PG_HOST", "127.0.0.1"),
                port=int(os.environ.get("PG_PORT", 5432)),
                user=os.environ.get("PG_USER", "bade_user"),
                password=os.environ.get("PG_PASSWORD", ""),
                dbname=os.environ.get("PG_DATABASE", "bade"),
            )
            conn.close()
            print("Database is ready.")
            return
        except psycopg2.OperationalError as exc:
            print(f"Waiting for database ({attempt}/{MAX_ATTEMPTS}): {exc}")
            if attempt == MAX_ATTEMPTS:
                raise
            time.sleep(SLEEP_SECONDS)


if __name__ == "__main__":
    main()
