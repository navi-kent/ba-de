-- 原始貼文：爬蟲直接寫入，不做語意處理
CREATE TABLE IF NOT EXISTS raw_posts (
    id              SERIAL PRIMARY KEY,
    source          VARCHAR(20) NOT NULL,
    source_account  VARCHAR(255),
    post_id         TEXT NOT NULL,
    author          VARCHAR(255),
    title           TEXT,
    content         TEXT,
    url             TEXT,
    published_at    TIMESTAMPTZ,
    scraped_at      TIMESTAMPTZ DEFAULT NOW(),
    likes           INT DEFAULT 0,
    comments        INT DEFAULT 0,
    shares          INT DEFAULT 0,
    raw_json        JSONB,
    is_duplicate    BOOLEAN DEFAULT FALSE,
    duplicate_of    INT,
    UNIQUE (source, post_id)
);

CREATE INDEX IF NOT EXISTS idx_raw_posts_source_time ON raw_posts(source, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_raw_posts_scraped ON raw_posts(scraped_at DESC);


-- 處理後貼文：agent 分析的結果
CREATE TABLE IF NOT EXISTS processed_posts (
    id              SERIAL PRIMARY KEY,
    raw_post_id     INT NOT NULL REFERENCES raw_posts(id),
    processed_at    TIMESTAMPTZ DEFAULT NOW(),
    category        VARCHAR(50),
    sentiment       VARCHAR(20),
    topics          TEXT,
    relevance_score FLOAT,
    summary         TEXT,
    notes           TEXT
);

CREATE INDEX IF NOT EXISTS idx_processed_category ON processed_posts(category, processed_at DESC);


-- 爬蟲執行紀錄：監控健康狀態
CREATE TABLE IF NOT EXISTS scraper_runs (
    id              SERIAL PRIMARY KEY,
    scraper_name    VARCHAR(50) NOT NULL,
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    status          VARCHAR(20),
    items_found     INT DEFAULT 0,
    items_inserted  INT DEFAULT 0,
    error_message   TEXT
);


-- 許願池留言
CREATE TABLE IF NOT EXISTS wishes (
    id         SERIAL PRIMARY KEY,
    name       VARCHAR(50),
    contact    VARCHAR(100),
    content    TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    ip         VARCHAR(45)
);
