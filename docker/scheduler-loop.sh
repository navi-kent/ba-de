#!/bin/sh
set -eu

python /app/docker/wait_for_db.py
python /app/db/init_db.py

if [ "${RUN_SCRAPERS_ON_START:-1}" = "1" ]; then
  /app/docker/run_scrapers.sh
fi

INTERVAL="${SCRAPER_INTERVAL_SECONDS:-21600}"

while true; do
  echo "[scheduler] sleeping for ${INTERVAL} seconds"
  sleep "${INTERVAL}"

  if ! /app/docker/run_scrapers.sh; then
    echo "[scheduler] scraper run failed at $(date -Iseconds)" >&2
  fi
done
