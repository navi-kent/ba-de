-- 原始貼文：爬蟲直接寫入，不做語意處理
CREATE TABLE IF NOT EXISTS raw_posts (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    source          VARCHAR(20) NOT NULL,
    source_account  VARCHAR(255),
    post_id         TEXT NOT NULL,
    author          VARCHAR(255),
    title           TEXT,
    content         LONGTEXT,
    url             TEXT,
    published_at    DATETIME,
    scraped_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    likes           INT DEFAULT 0,
    comments        INT DEFAULT 0,
    shares          INT DEFAULT 0,
    raw_json        LONGTEXT,
    is_duplicate    TINYINT(1) DEFAULT 0,
    duplicate_of    INT,
    UNIQUE KEY uq_source_post (source, post_id(500))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_raw_posts_source_time ON raw_posts(source, published_at DESC);
CREATE INDEX idx_raw_posts_scraped ON raw_posts(scraped_at DESC);


-- 處理後貼文：agent 分析的結果
CREATE TABLE IF NOT EXISTS processed_posts (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    raw_post_id     INT NOT NULL,
    processed_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    category        VARCHAR(50),
    sentiment       VARCHAR(20),
    topics          TEXT,
    relevance_score FLOAT,
    summary         TEXT,
    notes           TEXT,
    FOREIGN KEY (raw_post_id) REFERENCES raw_posts(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_processed_category ON processed_posts(category, processed_at DESC);


-- 爬蟲執行紀錄：監控健康狀態
CREATE TABLE IF NOT EXISTS scraper_runs (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    scraper_name    VARCHAR(50) NOT NULL,
    started_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    finished_at     DATETIME,
    status          VARCHAR(20),
    items_found     INT DEFAULT 0,
    items_inserted  INT DEFAULT 0,
    error_message   TEXT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- 許願池留言
CREATE TABLE IF NOT EXISTS wishes (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    name       VARCHAR(50),
    contact    VARCHAR(100),
    content    TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    ip         VARCHAR(45)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
