# 八德夢想家 (Ba-de)

桃園市八德區地方社區資訊平台。自動從 Google News、PTT 等來源蒐集八德區相關新聞與生活資訊，集中顯示在本地網頁，讓居民快速掌握區域動態。

---

## 目錄

- [系統架構](#系統架構)
- [快速開始](#快速開始)
- [專案結構](#專案結構)
- [設定檔說明](#設定檔說明)
- [資料庫結構](#資料庫結構)
- [爬蟲說明](#爬蟲說明)
- [看板功能](#看板功能)
- [許願池](#許願池)
- [Email 通知設定](#email-通知設定)
- [自動化排程](#自動化排程)
- [日常維運指令](#日常維運指令)
- [下一步計畫](#下一步計畫)
- [常見問題](#常見問題)

---

## 系統架構

```
爬蟲 (每天 4 次)          MySQL                   後端 API              前端
┌──────────────┐          ┌────────────────┐      ┌─────────────┐      ┌──────────────┐
│ news_rss.py  │──寫入───▶│ raw_posts      │◀─讀─│ backend/    │◀────│ frontend/    │
│ ptt_scraper  │          │ processed_posts│      │ app.py:5001 │     │ index.html   │
│ dcard        │          │ scraper_runs   │      │ /api/stats  │     │ wish.html    │
│ gov_announce │          │ wishes         │      │ /api/posts  │     └──────────────┘
│ fb_mbasic    │          └────────────────┘      │ /api/wish   │
└──────────────┘                                  └─────────────┘
```

**資料流程：**
1. LaunchAgent 每天在 00:00 / 06:00 / 12:00 / 18:00 自動執行爬蟲
2. 爬蟲將文章去重後寫入 MySQL `raw_posts`
3. 前端透過 `/api/*` 取得資料並渲染頁面
4. 開啟 `http://127.0.0.1:5001` 即可瀏覽

---

## 快速開始

### 環境需求

- macOS（LaunchAgent 僅支援 macOS）
- Python 3.14+
- MySQL 8.0+（`brew install mysql`）

### 首次安裝

```bash
cd /Users/kent/Ba-de

# 1. 安裝 MySQL（若尚未安裝）
brew install mysql
brew services start mysql

# 2. 建立資料庫與使用者（替換 YOUR_PASSWORD）
mysql -u root -p -e "
CREATE DATABASE IF NOT EXISTS bade CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'bade_user'@'localhost' IDENTIFIED BY 'YOUR_PASSWORD';
GRANT ALL PRIVILEGES ON bade.* TO 'bade_user'@'localhost';
FLUSH PRIVILEGES;
"

# 3. 設定環境變數
cp .env.example .env
# 編輯 .env，填入 MYSQL_PASSWORD 及其他設定

# 4. 建立虛擬環境並安裝套件
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 5. 初始化資料表
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
cd /Users/kent/Ba-de && source venv/bin/activate
cd scrapers
python news_rss.py
python ptt_scraper.py
```

---

## 專案結構

```
Ba-de/
├── .env                     # 資料庫 + Email 設定（含密碼，勿上傳 Git）
├── .env.example             # 設定範本
├── .gitignore
├── Procfile                 # 部署用（gunicorn）
├── requirements.txt         # Python 套件清單
│
├── backend/
│   └── app.py               # Flask 後端（純 API + 提供靜態前端）
│
├── frontend/
│   ├── index.html           # 首頁看板（純靜態 HTML）
│   └── wish.html            # 許願池頁面（純靜態 HTML）
│
├── config/
│   └── search_config.yaml   # 監控地區 + 搜尋關鍵字（最常修改）
│
├── db/
│   ├── init_db.py           # 初始化資料庫（重複執行安全）
│   └── schema.sql           # MySQL 資料表定義
│
└── scrapers/
    ├── utils.py             # 共用工具（MySQL 連線、log 函式、設定檔讀取）
    ├── news_rss.py          # Google News RSS（已啟用）
    ├── ptt_scraper.py       # PTT 桃園版、中壢版（已啟用）
    ├── dcard_scraper.py     # Dcard（已寫好，未加入排程）
    ├── gov_announce.py      # 政府公告 OpenData（已寫好，未加入排程）
    └── fb_mbasic.py         # Facebook mbasic（已寫好，效果有限）
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
# MySQL 連線
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=bade_user
MYSQL_PASSWORD=your_password
MYSQL_DATABASE=bade

# 許願池 Email 通知（選填）
WISH_RECIPIENT_EMAIL=
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
```

### `config/search_config.yaml`

控制爬蟲搜尋哪個地區、搜尋哪些關鍵字。

```yaml
location:
  city: "桃園市"
  district: "八德區"

news_keywords:
  core:              # 每次必搜
    - '"{city}" "{district}"'
    - '"{district}" "里長"'
  issues:            # 自動與地區組合搜尋
    - "交通"
    - "治安"
    - "環境"
    # 可自行新增，如 "道路"、"停電"
  local_topics:      # 八德特定議題
    - '"八德擴大都市計畫"'
    - '"捷運綠線" "八德"'
    - '"霄裡地區"'
```

新增關鍵字只需在 `issues` 加一行，下次爬蟲執行自動生效，不需改程式。

---

## 資料庫結構

資料庫引擎：**MySQL 8.0**，共四張表，定義於 `db/schema.sql`。

### `raw_posts`（爬蟲寫入）

| 欄位 | 型別 | 說明 |
|------|------|------|
| `source` | VARCHAR(20) | 來源類型：`news` / `ptt` / `dcard` / `fb` / `gov` |
| `source_account` | VARCHAR(255) | Google News 為搜尋關鍵字；PTT 為看板名稱 |
| `post_id` | TEXT | 平台原生 ID，作為去重依據（UNIQUE 前 500 字元） |
| `title` | TEXT | 標題 |
| `content` | LONGTEXT | 內文或摘要 |
| `url` | TEXT | 原文連結 |
| `published_at` | DATETIME | 原文發布時間 |
| `scraped_at` | DATETIME | 爬取時間 |
| `raw_json` | LONGTEXT | 完整原始資料，方便日後補欄位 |

### `processed_posts`（AI 分析結果，尚未使用）

| 欄位 | 說明 |
|------|------|
| `raw_post_id` | 對應 `raw_posts.id` |
| `category` | 議題分類（交通 / 治安 / 環境 / 民生...） |
| `sentiment` | 情感：`positive` / `neutral` / `negative` |
| `summary` | 30 字以內摘要 |
| `relevance_score` | 0.0 ~ 1.0，與在地生活的相關程度 |

### `scraper_runs`（爬蟲執行紀錄）

每次執行都會記錄開始/結束時間、狀態、新增筆數，方便排查異常。

### `wishes`（許願池留言）

| 欄位 | 說明 |
|------|------|
| `name` | 暱稱（選填） |
| `contact` | 聯絡方式（選填） |
| `content` | 許願內容 |
| `created_at` | 送出時間 |
| `ip` | 來源 IP（僅供管理員參考） |

**查看許願紀錄：**
```bash
mysql -u bade_user -p bade -e "SELECT created_at, name, content FROM wishes ORDER BY created_at DESC;"
```

---

## 爬蟲說明

### 已啟用（在排程中）

| 爬蟲 | 檔案 | 說明 |
|------|------|------|
| Google News | `news_rss.py` | 依關鍵字查詢 RSS，每關鍵字最多 100 則，過濾 2026/03/01 以前的舊資料 |
| PTT | `ptt_scraper.py` | 抓 Taoyuan、ChungLi 版最新 2 頁，標題或內文含「八德」才保留 |

### 已寫好但未啟用

| 爬蟲 | 檔案 | 說明 |
|------|------|------|
| Dcard | `dcard_scraper.py` | 監控 mood、trending 看板，篩選相關貼文 |
| 政府公告 | `gov_announce.py` | 桃園市政府、八德區公所 OpenData XML |
| Facebook | `fb_mbasic.py` | mbasic 介面，FB 反爬蟲機制強，效果不穩定 |

**啟用方式：** 編輯 scraper plist，在指令後方加上 `&& python scrapers/xxx.py`，再重新載入 plist。

---

## 看板功能

**網址：** `http://127.0.0.1:5001`

| 功能 | 說明 |
|------|------|
| 統計列 | 顯示資料總筆數、今日新增、來源分佈 |
| 月份篩選 | 點選月份只看該月資料 |
| 來源篩選 | 依平台篩選（Google News / PTT...） |
| 關鍵字搜尋 | 搜尋標題與內文 |
| 熱門議題 | 右側顯示議題標籤，點擊快速篩選 |
| 無限捲動 | 往下滑自動載入更多文章 |
| 加入最愛 | Navbar 按鈕，引導加入瀏覽器書籤 |

### API 端點

| 端點 | 方法 | 說明 |
|------|------|------|
| `/api/stats` | GET | 統計資料（總筆數、今日、來源分佈、熱門議題） |
| `/api/posts` | GET | 文章列表（支援 source / month / topic / q / page / limit） |
| `/api/wish` | POST | 送出許願（JSON body：name / contact / content） |

---

## 許願池

**網址：** `http://127.0.0.1:5001/wish`

居民可提交對平台的功能建議或意見。填寫欄位：
- **暱稱**（選填）
- **聯絡方式**（選填，Email 或 LINE ID）
- **許願內容**（必填，上限 1000 字）

內容**只有管理員可見**，不會顯示給其他使用者。資料存入 `wishes` 資料表，並同時寄送 Email 通知（需先設定 `.env`）。

---

## Email 通知設定

許願送出後可自動寄 Email 通知，設定方式：

**1. 編輯 `.env` 檔，填入 Email 相關欄位**

**2. Gmail 應用程式密碼取得方式：**
1. Google 帳號 → 安全性 → 兩步驟驗證（需先開啟）
2. 兩步驟驗證頁面底部 → 應用程式密碼 → 建立
3. 複製 16 碼密碼填入 `SMTP_PASSWORD`

**3. 重啟 Dashboard 生效：**

```bash
launchctl unload ~/Library/LaunchAgents/com.kent.ba-de.dashboard.plist
launchctl load  ~/Library/LaunchAgents/com.kent.ba-de.dashboard.plist
```

> Email 未設定時，許願仍會正常存入資料庫，只是不寄通知信。

---

## 自動化排程

### 爬蟲（`com.kent.ba-de.scraper`）

- **執行時機：** 每天 00:00 / 06:00 / 12:00 / 18:00
- **機制：** `StartCalendarInterval`（電腦休眠後醒來會補跑錯過的時間點）
- **Log：** `/tmp/ba-de-scraper.log`（stdout）、`/tmp/ba-de-scraper.error.log`（stderr）

### Dashboard（`com.kent.ba-de.dashboard`）

- **機制：** `RunAtLoad = true`（載入即啟動）+ `KeepAlive = true`（崩潰自動重啟）
- **Log：** `/tmp/ba-de-dashboard.log`

---

## 日常維運指令

```bash
# 查看服務狀態（PID 非 - 代表運作中）
launchctl list | grep ba-de

# 重啟爬蟲排程
launchctl unload ~/Library/LaunchAgents/com.kent.ba-de.scraper.plist
launchctl load  ~/Library/LaunchAgents/com.kent.ba-de.scraper.plist

# 重啟 Dashboard
launchctl unload ~/Library/LaunchAgents/com.kent.ba-de.dashboard.plist
launchctl load  ~/Library/LaunchAgents/com.kent.ba-de.dashboard.plist

# 看爬蟲 log（最後 100 行）
tail -100 /tmp/ba-de-scraper.log

# 看爬蟲錯誤
cat /tmp/ba-de-scraper.error.log

# 各天資料筆數
mysql -u bade_user -p bade -e "
SELECT DATE(scraped_at) AS 日期, COUNT(*) AS 筆數
FROM raw_posts
GROUP BY DATE(scraped_at)
ORDER BY 日期 DESC
LIMIT 10;"

# 查看許願紀錄
mysql -u bade_user -p bade -e "SELECT created_at, name, content FROM wishes ORDER BY created_at DESC;"
```

---

## 下一步計畫

### 部署上線（Hetzner VPS）

目標架構：
```
Hetzner CX23（€3.99/月）
├── Nginx（反向代理 + 靜態前端）
├── gunicorn（Flask API）
└── MySQL 8.0
```

CI/CD：GitHub push → GitHub Actions SSH → 自動部署

### AI 語意分析（`scrapers/agent_analysis.py`，尚未實作）

對 `raw_posts` 未處理的文章使用 Claude API 進行：

1. **議題分類**：交通 / 治安 / 環境 / 民生 / 活動
2. **情感分析**：`positive` / `neutral` / `negative`
3. **智能摘要**：30 字重點
4. **相關性評分**：0.0 ~ 1.0

結果寫入 `processed_posts`，Dashboard 可顯示議題趨勢與情感走向。

```sql
-- 找出尚未分析的文章
SELECT r.* FROM raw_posts r
LEFT JOIN processed_posts p ON r.id = p.raw_post_id
WHERE p.id IS NULL;
```

---

## 常見問題

**看板打不開**
```bash
launchctl unload ~/Library/LaunchAgents/com.kent.ba-de.dashboard.plist
launchctl load  ~/Library/LaunchAgents/com.kent.ba-de.dashboard.plist
# 查看錯誤
cat /tmp/ba-de-dashboard.error.log
```

**資料庫連不上**
```bash
# 確認 MySQL 運行中
brew services list | grep mysql
# 重啟 MySQL
brew services restart mysql
```

**今天資料很少**
1. 排程在 00:00 / 06:00 / 12:00 / 18:00，確認是否到了下一個排程時間
2. 該時段確實沒有符合關鍵字的新文章（正常現象）
3. 手動補跑：`cd scrapers && python news_rss.py && python ptt_scraper.py`

**想換成其他鄉鎮區**
只需改 `config/search_config.yaml` 的 `location` 欄位與關鍵字，程式不需動。

**換電腦重新安裝**
```bash
# 1. 安裝 MySQL 並建立 DB（參考快速開始）

# 2. Clone repo
git clone <repo_url> Ba-de && cd Ba-de

# 3. 建立 venv 並安裝套件
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 4. 設定 .env，初始化資料表
cp .env.example .env   # 填入 MySQL 密碼
python db/init_db.py

# 5. 複製 plist 並載入
cp <備份路徑>/*.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.kent.ba-de.dashboard.plist
launchctl load ~/Library/LaunchAgents/com.kent.ba-de.scraper.plist
```
