#!/bin/sh
set -eu

python /app/docker/wait_for_db.py
python /app/db/init_db.py

exec gunicorn backend.app:app \
  --bind 0.0.0.0:${PORT:-5001} \
  --workers ${GUNICORN_WORKERS:-2}
