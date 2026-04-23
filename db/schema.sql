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


-- 最新消息（手動管理）
CREATE TABLE IF NOT EXISTS announcements (
    id               SERIAL PRIMARY KEY,
    title            TEXT NOT NULL,
    slug             VARCHAR(255) UNIQUE NOT NULL,
    category         VARCHAR(50) DEFAULT '一般',
    summary          TEXT,
    content          TEXT,
    meta_description TEXT,
    cover_image      TEXT,
    is_published     BOOLEAN DEFAULT FALSE,
    published_at     TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW(),
    created_at       TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_announcements_slug ON announcements(slug);
CREATE INDEX IF NOT EXISTS idx_announcements_pub ON announcements(published_at DESC) WHERE is_published = TRUE;


-- 訪客計數器
CREATE TABLE IF NOT EXISTS visitors (
    id         SERIAL PRIMARY KEY,
    visited_at TIMESTAMPTZ DEFAULT NOW()
);


-- 政府官網最新消息（八德區公所 & 戶政事務所 HTML 爬蟲）
CREATE TABLE IF NOT EXISTS gov_news (
    id              SERIAL PRIMARY KEY,

    -- 來源識別
    source_site     VARCHAR(30)  NOT NULL,   -- 'bade_district' | 'bade_hro'
    source_name     TEXT         NOT NULL,   -- '八德區公所' | '八德區戶政事務所'

    -- 文章識別
    news_id         TEXT         NOT NULL,   -- URL s= 參數值（同站內唯一）
    url             TEXT         NOT NULL,

    -- 核心內容
    title           TEXT         NOT NULL,
    content         TEXT,                    -- 全文（可日後補爬）

    -- 發布資訊
    department      VARCHAR(100),            -- 發布單位（bade_district 有；bade_hro 無）
    published_date  DATE,                    -- 西元日期（從民國年轉換）
    published_raw   VARCHAR(20),             -- 原始民國年字串，e.g. "115-04-09"

    -- 分類（從 department / title 自動推導，可日後 AI 補充）
    category        VARCHAR(50),             -- 主分類，e.g. '民政', '社會福利', '戶籍管理'
    sub_category    VARCHAR(50),             -- 次分類，e.g. department 名稱或細分主題
    tags            TEXT[],                  -- 關鍵詞標籤陣列

    -- 管理
    scraped_at      TIMESTAMPTZ  DEFAULT NOW(),
    raw_json        JSONB,

    UNIQUE (source_site, news_id)
);

CREATE INDEX IF NOT EXISTS idx_gov_news_source_date ON gov_news(source_site, published_date DESC);
CREATE INDEX IF NOT EXISTS idx_gov_news_category    ON gov_news(category, published_date DESC);
CREATE INDEX IF NOT EXISTS idx_gov_news_department  ON gov_news(department) WHERE department IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_gov_news_scraped     ON gov_news(scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_gov_news_tags        ON gov_news USING GIN(tags);


-- 許願池留言
CREATE TABLE IF NOT EXISTS wishes (
    id         SERIAL PRIMARY KEY,
    name       VARCHAR(50),
    contact    VARCHAR(100),
    category   VARCHAR(30) NOT NULL DEFAULT '合作提案',
    email      VARCHAR(100),
    line_id    VARCHAR(100),
    phone      VARCHAR(20),
    content    TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    ip         VARCHAR(45)
);
