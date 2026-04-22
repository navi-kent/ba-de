FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x /app/docker/web-entrypoint.sh \
    /app/docker/run_scrapers.sh \
    /app/docker/scheduler-loop.sh

EXPOSE 5001

CMD ["/app/docker/web-entrypoint.sh"]
