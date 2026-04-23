# 八德資源網 (Ba-de)

桃園市八德區地方社區資訊平台。自動蒐集八德區相關新聞與生活資訊，並提供手動管理的最新消息系統，讓居民快速掌握區域動態。

---

## 目錄

- [系統架構](#系統架構)
- [快速開始](#快速開始)
- [專案結構](#專案結構)
- [設定檔說明](#設定檔說明)
- [資料庫結構](#資料庫結構)
- [頁面說明](#頁面說明)
- [API 端點](#api-端點)
- [爬蟲說明](#爬蟲說明)
- [後台管理](#後台管理)
- [自動化排程](#自動化排程)
- [日常維運指令](#日常維運指令)
- [部署到 Hetzner](#部署到-hetzner)
- [常見問題](#常見問題)

---

## 系統架構

```
爬蟲 (每天 4 次)          PostgreSQL                  後端 API              前端
┌──────────────┐          ┌──────────────────┐        ┌─────────────┐      ┌─────────────────┐
│ news_rss.py  │──寫入───▶│ raw_posts        │◀──讀───│ backend/    │◀────│ index.html      │
│ ptt_scraper  │          │ announcements    │        │ app.py:5001 │     │ news.html       │
└──────────────┘          │ visitors         │        │             │     │ news-detail.html│
                          │ wishes           │        │             │     │ news-feed.html  │
後台管理員                 │ scraper_runs     │        │             │     │ admin.html      │
     │ 手動編輯           └──────────────────┘        └─────────────┘     │ wish.html       │
     ▼                                                                    └─────────────────┘
 /admin
```

**資料流程：**
1. LaunchAgent 每天在 00:00 / 06:00 / 12:00 / 18:00 自動執行爬蟲
2. 爬蟲將文章過濾（須含八德相關詞彙）後寫入 `raw_posts`
3. 管理員可透過 `/admin` 後台手動新增/編輯 `announcements`（最新消息）
4. 前端透過 `/api/*` 取得資料並渲染頁面（來源標籤不對外顯示）
5. 開啟 `http://127.0.0.1:5001` 即可瀏覽

---

## 快速開始

### 環境需求

- macOS（LaunchAgent 僅支援 macOS；部署到 Linux 請改用 systemd）
- Python 3.11+
- PostgreSQL 17（`brew install postgresql@17`）

### Docker / Ubuntu 部署

若要部署到 Ubuntu，建議直接使用 Docker Compose，不需要另外安裝本機 PostgreSQL。

```bash
# 1. 準備環境變數
cp .env.example .env
# 編輯 .env，至少填入 PG_PASSWORD、ADMIN_TOKEN

# 2. 建置並啟動
docker compose up -d --build

# 3. 查看狀態
docker compose ps
docker compose logs -f web
```

啟動後：
- 前端 + API：`http://SERVER_IP:5001`
- PostgreSQL：由 `db` 容器提供，資料存在 `postgres_data` volume
- 後台上傳圖片：存在 `uploads_data` volume
- 爬蟲排程：由 `scheduler` 容器每 6 小時執行一次（可用 `SCRAPER_INTERVAL_SECONDS` 調整）

常用指令：

```bash
# 停止服務
docker compose down

# 更新程式後重新部署
docker compose up -d --build

# 手動補跑 schema 初始化
docker compose exec web python db/init_db.py

# 手動補跑爬蟲
docker compose exec scheduler /app/docker/run_scrapers.sh
```

### 首次安裝

```bash
cd /Users/kent/Ba-de

# 1. 安裝 PostgreSQL（若尚未安裝）
brew install postgresql@17
brew services start postgresql@17

# 2. 建立資料庫與使用者（替換 YOUR_PASSWORD）
psql postgres -c "CREATE USER bade_user WITH PASSWORD 'YOUR_PASSWORD';"
psql postgres -c "CREATE DATABASE bade OWNER bade_user;"
psql bade -c "GRANT ALL ON SCHEMA public TO bade_user;"

# 3. 設定環境變數
cp .env.example .env
# 編輯 .env，填入 PG_PASSWORD、ADMIN_TOKEN 等設定

# 4. 建立虛擬環境並安裝套件
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 5. 初始化資料表（可重複執行，安全）
python db/init_db.py
```

### 啟動服務

```bash
# 載入 LaunchAgents（重開機後會自動載入，通常只需做一次）
launchctl load ~/Library/LaunchAgents/com.kent.ba-de.dashboard.plist
launchctl load ~/Library/LaunchAgents/com.kent.ba-de.scraper.plist
```

載入後：
- Dashboard 立即啟動 → 開啟 `http://127.0.0.1:5001`
- 爬蟲依排程每天 4 次自動執行

### 手動補跑爬蟲

```bash
cd /Users/kent/Ba-de && source venv/bin/activate && cd scrapers
python news_rss.py
python ptt_scraper.py
```

---

## 專案結構

```
Ba-de/
├── .env                      # 資料庫 + Email + 後台 Token（含密碼，勿上傳 Git）
├── .env.example              # 設定範本
├── .gitignore
├── Procfile                  # Heroku 格式（未使用；Hetzner 改用 systemd，見下方部署章節）
├── requirements.txt          # Python 套件清單
│
├── .github/
│   └── workflows/
│       └── deploy.yml        # GitHub Actions 自動部署到 Hetzner
│
├── backend/
│   └── app.py                # Flask 後端（API + 靜態頁面路由）
│
├── frontend/
│   ├── index.html            # 首頁（跑馬燈、統計、最新消息 preview、訪客計數）
│   ├── news.html             # 最新消息列表（手動管理）
│   ├── news-detail.html      # 最新消息內頁（SEO meta、Quill 內容渲染）
│   ├── news-feed.html        # 新聞消息（爬蟲資料、分頁篩選）
│   ├── admin.html            # 後台管理（Token 登入、Quill 編輯器）
│   ├── wish.html             # 許願池
│   ├── robots.txt            # Disallow: / 禁止所有爬蟲索引（配合後端 X-Robots-Tag header）
│   └── uploads/              # 後台上傳的圖片（auto-created，不進 git）
│
├── config/
│   └── search_config.yaml    # 監控地區 + 搜尋關鍵字（最常修改）
│
├── db/
│   ├── init_db.py            # 初始化資料庫（重複執行安全）
│   └── schema.sql            # PostgreSQL 資料表定義
│
└── scrapers/
    ├── utils.py              # 共用工具（DB 連線、log、設定檔讀取）
    ├── news_rss.py           # Google News RSS（已啟用）
    ├── ptt_scraper.py        # PTT Taoyuan、ChungLi 版（已啟用）
    ├── dcard_scraper.py      # Dcard（已寫好，未加入排程）
    ├── gov_announce.py       # 政府公告 OpenData（已寫好，未加入排程）
    └── fb_mbasic.py          # Facebook mbasic（已寫好，效果不穩定）
```

**LaunchAgent plist（專案目錄外）：**

```
~/Library/LaunchAgents/
├── com.kent.ba-de.scraper.plist    # 爬蟲排程
└── com.kent.ba-de.dashboard.plist  # Dashboard 常駐服務
```

---

## 設定檔說明

### `.env`

```bash
# PostgreSQL 連線
PG_HOST=127.0.0.1
PG_PORT=5432
PG_USER=bade_user
PG_PASSWORD=your_password
PG_DATABASE=bade

# 後台管理帳號（帳號 + 密碼雙重驗證）
ADMIN_USER=admin@example.com
ADMIN_TOKEN=your_admin_password
```

### `config/search_config.yaml`

控制爬蟲搜尋哪個地區、搜尋哪些關鍵字。

```yaml
location:
  city: "桃園市"
  district: "八德區"

news_keywords:
  core:
    - '"{city}" "{district}"'         # "桃園市" "八德區"
  issues:
    - "交通"
    - "治安"
    - "環境"
    - "停車"
    - "路平"
    - "學區"
    - "公園"
    - "市場"
  local_topics:
    - '"八德擴大都市計畫"'
    - '"捷運綠線" "八德"'
    - '"霄裡地區"'
```

**爬蟲過濾條件（兩隻爬蟲共用）：**
- 發佈日期 `>= 2026-01-01`
- 標題或內文必須含「八德」「霄裡」「大湳」「八德擴大都市計畫」其中之一

---

## 資料庫結構

資料庫引擎：**PostgreSQL 17**，定義於 `db/schema.sql`。

### `raw_posts`（爬蟲寫入）

| 欄位 | 型別 | 說明 |
|------|------|------|
| `source` | VARCHAR(20) | 來源：`news` / `ptt` / `dcard` / `fb` / `gov` |
| `source_account` | VARCHAR(255) | Google News 為搜尋關鍵字；PTT 為看板名稱 |
| `post_id` | TEXT | 平台原生 ID，去重依據（`UNIQUE(source, post_id)`） |
| `author` | VARCHAR(255) | 作者（PTT / Dcard / FB 有值；Google News 為空） |
| `title` | TEXT | 標題 |
| `content` | TEXT | 內文或摘要 |
| `url` | TEXT | 原文連結 |
| `published_at` | TIMESTAMPTZ | 原文發布時間 |
| `scraped_at` | TIMESTAMPTZ | 爬取時間 |
| `likes` / `comments` / `shares` | INT | 互動數（PTT / Dcard / FB 有值；預設 0） |
| `raw_json` | JSONB | 完整原始資料（含平台特有欄位） |
| `is_duplicate` | BOOLEAN | 是否為重複文章（預設 FALSE，保留供未來去重用） |
| `duplicate_of` | INT | 重複文章指向的原始 `raw_posts.id` |

### `announcements`（最新消息，後台手動管理）

| 欄位 | 說明 |
|------|------|
| `title` | 標題（必填） |
| `slug` | 自設網址，用於 `/news/<slug>`（UNIQUE） |
| `category` | 分類（公告 / 活動 / 工程...） |
| `summary` | 摘要（顯示於列表 + SEO） |
| `content` | 內文 HTML（Quill 編輯器輸出） |
| `meta_description` | SEO meta description |
| `cover_image` | 封面圖片路徑或網址 |
| `is_published` | 是否發佈（草稿 / 已發佈） |
| `published_at` | 發佈時間 |
| `updated_at` | 最後更新時間 |

### `visitors`（訪客計數）

| 欄位 | 說明 |
|------|------|
| `visited_at` | 訪問時間 |

> 每次訪問首頁即插入一筆。顯示數字 = `COUNT(*) + 999`（從 1000 起算）。

### `wishes`（許願池留言）

| 欄位 | 說明 |
|------|------|
| `name` | 暱稱（選填） |
| `email` | Email（必填） |
| `line_id` | LINE ID（選填） |
| `phone` | 聯絡電話，數字 6-15 碼（選填） |
| `category` | 類別：合作提案 / 平台功能許願（預設合作提案） |
| `content` | 許願內容 |
| `created_at` | 送出時間 |
| `ip` | 來源 IP |

### `processed_posts`（AI 分析結果，目前未使用）

保留供未來 AI 代理分析 `raw_posts` 用，現階段前端不讀此表。

| 欄位 | 說明 |
|------|------|
| `raw_post_id` | 關聯 `raw_posts.id` |
| `category` | AI 分類標籤 |
| `sentiment` | 情緒分析（正面/負面/中性） |
| `topics` | 主題關鍵字 |
| `relevance_score` | 相關度分數 |
| `summary` | AI 摘要 |

### `scraper_runs`（爬蟲執行紀錄）

每次執行記錄開始/結束時間、狀態、新增筆數，方便排查異常。

---

## 頁面說明

| 路由 | 頁面 | 說明 |
|------|------|------|
| `/` | 首頁 | 跑馬燈（近 5 天標題，無標籤）、統計、最新消息 preview、訪客計數器 |
| `/news` | 最新消息列表 | 手動管理的公告，依分類篩選，分頁 |
| `/news/<slug>` | 最新消息內頁 | 完整文章，含 SEO meta、OG tags |
| `/news-feed` | 新聞消息 | 爬蟲資料，來源/月份/關鍵字篩選，數字分頁 |
| `/admin` | 後台管理 | 帳號＋密碼登入；管理最新消息（CRUD）與許願池留言 |
| `/wish` | 許願池 | 居民意見回饋表單 |
| 全頁面 | Navbar | 品牌名稱右上角顯示版號徽章（`v1.0`） |

---

## API 端點

### 公開 API

| 端點 | 方法 | 說明 |
|------|------|------|
| `/api/stats` | GET | 統計（總筆數、今日、來源分佈、熱門議題） |
| `/api/posts` | GET | 新聞消息列表（`source/month/topic/q/page/limit`） |
| `/api/ticker` | GET | 跑馬燈資料（近 5 天標題，去重後最多 20 筆） |
| `/api/announcements` | GET | 最新消息列表（`category/page/limit`） |
| `/api/announcements/<slug>` | GET | 最新消息內頁 |
| `/api/visit` | POST | 訪客計數（每次 +1，回傳當前總數） |
| `/api/wish` | POST | 送出許願（`name/email/line_id/phone/category/content`） |

### 後台 API（需 Headers：`X-Admin-User` + `X-Admin-Token`）

| 端點 | 方法 | 說明 |
|------|------|------|
| `/api/admin/announcements` | GET | 所有消息列表（含草稿） |
| `/api/admin/announcements` | POST | 新增消息 |
| `/api/admin/announcements/<id>` | GET | 取得單筆 |
| `/api/admin/announcements/<id>` | PUT | 更新 |
| `/api/admin/announcements/<id>` | DELETE | 刪除 |
| `/api/admin/wishes` | GET | 許願池留言列表 |
| `/api/admin/wishes/<id>` | DELETE | 刪除單筆許願留言 |
| `/api/admin/upload` | POST | 上傳圖片（回傳 `/uploads/<filename>`） |

---

## 爬蟲說明

### 已啟用（在排程中）

| 爬蟲 | 檔案 | 說明 |
|------|------|------|
| Google News | `news_rss.py` | 12 組關鍵字 RSS，標題/摘要須含八德詞彙 |
| PTT | `ptt_scraper.py` | Taoyuan、ChungLi 版最新 2 頁，標題/內文須含八德詞彙 |

### 已寫好但未啟用

| 爬蟲 | 說明 |
|------|------|
| `dcard_scraper.py` | Dcard 相關看板 |
| `gov_announce.py` | 桃園市政府 OpenData XML |
| `fb_mbasic.py` | Facebook mbasic（反爬蟲機制強，效果不穩） |

**啟用方式：** 編輯 scraper plist，在指令後加上 `&& python scrapers/xxx.py`，重新載入 plist。

---

## 後台管理

**網址：** `http://127.0.0.1:5001/admin`

**登入：** 帳號（`ADMIN_USER`）+ 密碼（`ADMIN_TOKEN`）雙欄驗證，後端同時以 `hmac.compare_digest()` 比對兩者。

**URL Hash 路由：** 切換 view 時 URL 會更新（`#list` / `#wishes` / `#edit` / `#edit/<id>`），refresh 會停留在同一頁。

**功能：**

| 功能 | 說明 |
|------|------|
| 最新消息列表 | 所有消息（含草稿），可編輯/刪除/預覽 |
| 新增/編輯消息 | 完整 Quill 富文字編輯器（含圖片插入） |
| 標題 & Slug | Slug 自動從標題生成，可手動修改 |
| 類別 | 自由輸入或點擊快速預設（公告/活動/工程/交通/民生） |
| 封面圖片 | 拖曳或點擊上傳，存至 `frontend/uploads/` |
| 摘要 | 顯示於列表頁及 SEO meta description |
| 發佈設定 | 草稿 / 發佈切換 + 自訂發佈時間 |
| 許願池留言 | 查看所有前台留言（分欄顯示 Email / LINE / 電話），點列進入詳情，可刪除 |

---


## 自動化排程

### 爬蟲（`com.kent.ba-de.scraper`）

- **執行時機：** 每天 00:00 / 06:00 / 12:00 / 18:00
- **機制：** `StartCalendarInterval`（電腦休眠後醒來會補跑）
- **Log：** `/tmp/ba-de-scraper.log`、`/tmp/ba-de-scraper.error.log`

### Dashboard（`com.kent.ba-de.dashboard`）

- **機制：** `RunAtLoad = true` + `KeepAlive = true`（崩潰自動重啟）
- **Log：** `/tmp/ba-de-dashboard.log`

---

## 日常維運指令

```bash
# 查看服務狀態
launchctl list | grep ba-de

# 重啟爬蟲排程
launchctl unload ~/Library/LaunchAgents/com.kent.ba-de.scraper.plist
launchctl load  ~/Library/LaunchAgents/com.kent.ba-de.scraper.plist

# 重啟 Dashboard
launchctl unload ~/Library/LaunchAgents/com.kent.ba-de.dashboard.plist
launchctl load  ~/Library/LaunchAgents/com.kent.ba-de.dashboard.plist

# 看 log
tail -f /tmp/ba-de-scraper.log
tail -f /tmp/ba-de-dashboard.log

# 各天資料筆數
psql bade -U bade_user -c "
SELECT scraped_at::date AS 日期, COUNT(*) AS 筆數
FROM raw_posts
GROUP BY scraped_at::date
ORDER BY 日期 DESC LIMIT 14;"

# 訪客人數
psql bade -U bade_user -c "SELECT COUNT(*) + 999 AS 顯示人數 FROM visitors;"

# 查看許願紀錄
psql bade -U bade_user -c "SELECT created_at, name, content FROM wishes ORDER BY created_at DESC;"

# 查看最新消息
psql bade -U bade_user -c "SELECT id, is_published, published_at::date, title FROM announcements ORDER BY created_at DESC;"
```

---

## 部署到 Hetzner

### 目標架構

```
Hetzner CX23（€3.99/月，Debian 12）
├── Nginx（反向代理，port 80/443）
├── gunicorn（Flask API，port 5001）
├── PostgreSQL 17
└── systemd（管理 gunicorn + 爬蟲排程）
```

### VPS 首次設定

```bash
apt update && apt upgrade -y
apt install -y python3 python3-venv python3-pip nginx postgresql postgresql-contrib

sudo -u postgres psql -c "CREATE USER bade_user WITH PASSWORD 'YOUR_PASSWORD';"
sudo -u postgres psql -c "CREATE DATABASE bade OWNER bade_user;"
sudo -u postgres psql bade -c "GRANT ALL ON SCHEMA public TO bade_user;"

adduser deploy && usermod -aG sudo deploy
# 將本機公鑰加入 /home/deploy/.ssh/authorized_keys

git clone https://github.com/YOUR_GITHUB/Ba-de.git /home/deploy/Ba-de
cd /home/deploy/Ba-de
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && nano .env   # 填入 PG_PASSWORD、ADMIN_TOKEN
python db/init_db.py
```

### GitHub Actions 自動部署

設定 GitHub Secrets（`Settings → Secrets and variables → Actions`）：

| Secret | 說明 |
|--------|------|
| `HETZNER_HOST` | VPS IP 位址 |
| `HETZNER_USER` | 登入帳號（`deploy`） |
| `HETZNER_SSH_KEY` | 本機私鑰（`cat ~/.ssh/id_ed25519`） |

Push 到 `main` 後自動 SSH 進 VPS 拉取並重啟服務。詳見 `.github/workflows/deploy.yml`。

### VPS systemd 服務

**`/etc/systemd/system/ba-de.service`**
```ini
[Unit]
Description=八德資源網 Dashboard
After=network.target postgresql.service

[Service]
User=deploy
WorkingDirectory=/home/deploy/Ba-de
EnvironmentFile=/home/deploy/Ba-de/.env
ExecStart=/home/deploy/Ba-de/venv/bin/gunicorn backend.app:app --bind 127.0.0.1:5001 --workers 2
Restart=always

[Install]
WantedBy=multi-user.target
```

**`/etc/systemd/system/ba-de-scraper.timer`**
```ini
[Unit]
Description=每 6 小時執行一次爬蟲

[Timer]
OnCalendar=*-*-* 00,06,12,18:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
systemctl enable --now ba-de.service
systemctl enable --now ba-de-scraper.timer
```

---

## 常見問題

**看板打不開**
```bash
launchctl unload ~/Library/LaunchAgents/com.kent.ba-de.dashboard.plist
launchctl load  ~/Library/LaunchAgents/com.kent.ba-de.dashboard.plist
cat /tmp/ba-de-dashboard.error.log
```

**資料庫連不上**
```bash
brew services list | grep postgresql
brew services restart postgresql@17
```

**換電腦重新安裝**
```bash
git clone <repo_url> Ba-de && cd Ba-de
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # 填入 PG_PASSWORD、ADMIN_TOKEN
python db/init_db.py
```

plist 不在 repo 裡，需手動建立（路徑請替換為實際安裝目錄）：

**`~/Library/LaunchAgents/com.kent.ba-de.dashboard.plist`**
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.kent.ba-de.dashboard</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/kent/Ba-de/venv/bin/python</string>
        <string>/Users/kent/Ba-de/backend/app.py</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>WorkingDirectory</key>
    <string>/Users/kent/Ba-de</string>
    <key>StandardOutPath</key>
    <string>/tmp/ba-de-dashboard.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/ba-de-dashboard.error.log</string>
</dict>
</plist>
```

**`~/Library/LaunchAgents/com.kent.ba-de.scraper.plist`**
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.kent.ba-de.scraper</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>-c</string>
        <string>cd /Users/kent/Ba-de &amp;&amp; source venv/bin/activate &amp;&amp; python scrapers/news_rss.py &amp;&amp; python scrapers/ptt_scraper.py</string>
    </array>
    <key>StartCalendarInterval</key>
    <array>
        <dict><key>Hour</key><integer>0</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Hour</key><integer>6</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Hour</key><integer>12</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Hour</key><integer>18</integer><key>Minute</key><integer>0</integer></dict>
    </array>
    <key>StandardOutPath</key>
    <string>/tmp/ba-de-scraper.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/ba-de-scraper.error.log</string>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.kent.ba-de.dashboard.plist
launchctl load ~/Library/LaunchAgents/com.kent.ba-de.scraper.plist
```
