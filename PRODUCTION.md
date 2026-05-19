# Production Deployment Guide

Two Docker services — post_manager (1 instance) and scraper (3 instances) —
that connect to an **external Redis server** and write results to
Supabase + Google Sheets. No Instagram accounts. Everything is cookie-free.

## What Runs

| Container        | Count | Schedule       | What It Does |
|-----------------|-------|----------------|--------------|
| `ig-post-manager` | 1   | every 8 hours  | Reads Google Sheet → fetches metadata → pushes Post jobs to Redis |
| `ig-scraper-1`    | 1   | every 3 hours  | Drains Redis queues → finds comments → writes Supabase + Google Sheets |
| `ig-scraper-2`    | 1   | every 3 hours  | Same — pulls from the same queues in parallel |
| `ig-scraper-3`    | 1   | every 3 hours  | Same — pulls from the same queues in parallel |

Three scraper instances run in parallel so posts are processed faster.
Each instance LPOPs jobs from the same Redis lists — Redis is single-threaded
so there are no race conditions.

Each post is scraped at most **once per day**. Later runs skip posts that
were already processed today, so running more frequently is safe.

## Architecture

```
Google Sheet                External Redis              Supabase + Sheets
┌────────────┐          ┌────────────────────┐       ┌──────────────────┐
│ post_url   │          │ instagram:40       │       │ instagram        │
│ username   │─8 hours─→│ instagram:120      │─3 hrs─→│  (post metadata) │
│            │          │ instagram:240      │       │                  │
└────────────┘          │ instagram:rest     │       │ instagram_stats  │
                        └───────┬────────────┘       │  (found comments)│
                                │ LPOP × 3           │                  │
                        ┌───────┼────────────┐       │ Google Sheet     │
                        │       │       │    │       │  (output rows)   │
                   scraper_1 scraper_2 scraper_3     └──────────────────┘
```

---

## Setup From Scratch

### 1. Provision a server

Any Linux server with at least **2 vCPU, 4 GB RAM** and **50 GB disk**.
Ubuntu 22.04+ recommended.

```bash
ssh root@YOUR_SERVER_IP
```

### 2. Install Docker & Docker Compose

```bash
# Docker
curl -fsSL https://get.docker.com | sh
usermod -aG docker $USER
newgrp docker

# Docker Compose (standalone plugin)
apt install -y docker-compose-plugin

# Verify
docker --version
docker compose version
```

### 3. Set up Redis (separate server)

Redis MUST run on a **separate machine** — do not run it on the app server.
The scraper and post_manager connect to it over the network.

See `redis_queuing/README.md` for the full Redis setup guide. Quick version:

```bash
# On the Redis server
cd redis_queuing/
cp .env.example .env    # set REDIS_PASSWORD
docker compose up -d

# Verify it's reachable from the app server
redis-cli -h REDIS_SERVER_IP -p 6379 -a YOUR_PASSWORD PING
# → PONG
```

### 4. Set up Supabase tables

Run these in the Supabase SQL Editor:

```sql
CREATE TABLE public.instagram (
  post_url TEXT PRIMARY KEY,
  username TEXT NOT NULL,
  media_id TEXT,
  hmac_claim TEXT,
  comment_count INTEGER,
  has_next_comments BOOLEAN DEFAULT TRUE,
  first_comments JSONB DEFAULT '[]',
  post_exists BOOLEAN DEFAULT TRUE,
  comment_exists BOOLEAN DEFAULT TRUE,
  updated_at TIMESTAMPTZ,
  retry_count INTEGER DEFAULT 0
);

CREATE TABLE public.instagram_stats (
  id BIGSERIAL,
  post_url TEXT NOT NULL,
  username TEXT NOT NULL,
  text TEXT,
  likes INTEGER DEFAULT 0,
  reply_count INTEGER DEFAULT 0,
  date_of_comment TEXT,
  created_at DATE DEFAULT CURRENT_DATE,
  UNIQUE (post_url, username, created_at)
);

CREATE TABLE public.instagram_error_videos (
  post_url TEXT PRIMARY KEY,
  error TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 5. Prepare Google Sheets credentials

You need **two** Google Cloud service accounts:

| File | Used By | Purpose |
|------|---------|---------|
| `zoecredentials.json` | post_manager + scraper | Read the input sheet |
| `tomsheetcreds.json` | scraper | Write to the output sheet |

Create the service accounts in Google Cloud Console:
1. Go to **IAM & Admin → Service Accounts** → Create
2. Assign **Viewer** role (or Editor for the output account)
3. Generate a JSON key → download
4. Share your Google Sheets with the service account email

### 6. Create the input Google Sheet

Create a sheet with these columns (case-insensitive):

| post_url | username |
|----------|----------|
| `https://www.instagram.com/reel/xxx/` | `targetuser` |
| `https://www.instagram.com/p/xxx/` | `otheruser` |

The sheet must be shared with the service account email from step 5.

### 7. Clone and configure

```bash
cd /opt
git clone https://github.com/your-org/zoestephenson-instagram.git
cd zoestephenson-instagram

cp .env.example .env
nano .env
```

Fill in **all** values:

```bash
# ── External Redis (step 3) ──────────────────────────────────────────────
REDIS_HOST=10.0.0.5
REDIS_PORT=6379
REDIS_PASSWORD=your-redis-password
REDIS_DB=0

# ── Supabase (step 4) ───────────────────────────────────────────────────
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_KEY=your-service-role-key

# ── Residential Rotating Proxy ──────────────────────────────────────────
# {COUNTRY} is replaced at runtime with a random country code
PROXY=http://user__cr.{COUNTRY}:password@proxy-host:port

# Valid proxy country codes (comma-separated, must match proxy provider)
PROXY_COUNTRIES=DE,UK,US,CA,AU,FR,IT,ES,JP

# ── Schedules (seconds) ─────────────────────────────────────────────────
POST_MANAGER_INTERVAL=28800    # 8 hours
SCRAPER_INTERVAL=10800         # 3 hours

# ── Google Sheets (step 5) ──────────────────────────────────────────────
INPUT_SHEET_COMMENT_STATS=your-source-sheet-id
OUTPUT_SHEET_COMMENT_STATS=your-output-sheet-id

# ── Scraping Limits ─────────────────────────────────────────────────────
POST_FETCH_BATCH_SIZE=20
MAX_PAGINATION_DEPTH=300
MAX_RETRIES=5
MAX_RATE_LIMIT_RETRIES=3
```

### 8. Place credentials

```bash
cp /path/to/zoecredentials.json  post_manager/
cp /path/to/zoecredentials.json  scraper/
cp /path/to/tomsheetcreds.json   scraper/
```

### 9. Build and start

```bash
docker compose up -d --build
```

Verify all 4 containers are running:

```bash
docker compose ps
```

You should see:

```
NAME             STATUS
ig-post-manager  Up
ig-scraper-1     Up
ig-scraper-2     Up
ig-scraper-3     Up
```

---

## Monitoring

```bash
# All scraper logs (merged)
docker compose logs -f scraper_1 scraper_2 scraper_3

# Single scraper
docker compose logs -f scraper_1

# Post manager
docker compose logs -f post_manager

# Container health
docker compose ps

# Queue lengths (from the app server — requires redis-cli)
redis-cli -h $REDIS_HOST -p $REDIS_PORT -a $REDIS_PASSWORD LLEN instagram:40
redis-cli -h $REDIS_HOST -p $REDIS_PORT -a $REDIS_PASSWORD LLEN instagram:rest

# Processing progress
redis-cli -h $REDIS_HOST -p $REDIS_PORT -a $REDIS_PASSWORD LLEN instagram:processing
```

---

## Scheduling

| Env Var | Default  | Service      | Meaning |
|---------|----------|--------------|---------|
| `POST_MANAGER_INTERVAL` | `28800` | post_manager | Time between Google Sheet re-reads |
| `SCRAPER_INTERVAL` | `10800` | scraper      | Time between queue drain cycles |

Set `POST_MANAGER_INTERVAL=0` to run once and exit.
Set `SCRAPER_INTERVAL=0` to run continuously (legacy mode).

### How "once per day" works

When the scraper processes a post:
1. It writes `updated_at=now()` to the `instagram` table
2. On the next cycle, it checks `is_post_processed_today()` — if `updated_at`
   is from today, the post is skipped
3. The next day, `updated_at` is no longer "today" → post gets processed again

This means you can run the scraper every hour and it won't waste time
re-scraping posts that were already done today.

### How 3 scraper instances avoid duplicates

All three scraper instances drain jobs from the same Redis lists using
`LPOP` (atomic pop from the left). Since Redis processes commands
sequentially, each job is popped by exactly one scraper — no duplicates,
no distributed locking needed.

---

## Operations

```bash
# Restart after code changes
docker compose up -d --build

# Run post_manager on demand (ignores schedule)
docker compose run --rm -e POST_MANAGER_INTERVAL=0 post_manager

# Add more scraper instances (temporary)
docker compose up -d --scale scraper_1=5
# Note: remove container_name from the scraper block for this to work

# View errors across all scrapers
docker compose logs scraper_1 scraper_2 scraper_3 | grep -i "dead-letter\|ERROR"

# Stop everything
docker compose down
```

---

## Google Sheet Format

Input sheet (read by post_manager):

| post_url | username |
|----------|----------|
| `https://www.instagram.com/reel/xxx/` | `targetuser` |
| `https://www.instagram.com/p/xxx/` | `otheruser` |

Output sheet (written by scraper):

| username | post_url | text | likes | reply_count | date_of_comment | date |
|----------|----------|------|-------|-------------|-----------------|------|

---

## Updating

```bash
cd /opt/zoestephenson-instagram
git pull
docker compose up -d --build
```

---

## Troubleshooting

```bash
# Redis connection refused
docker compose logs scraper_1 | grep -i "redis is not connected"
# → check REDIS_HOST, REDIS_PORT, REDIS_PASSWORD in .env
# → verify the Redis server is reachable from the app server

# Page fetch failing
docker compose logs scraper_1 | grep -i "fetch failed"
# → check PROXY in .env, verify proxy credentials are still valid
# → ensure PROXY_COUNTRIES matches your proxy provider

# Sheets push failing
docker compose logs scraper_1 | grep -i "Failed to append"
# → check credentials files exist in scraper/
# → verify the service account has write access to the sheet

# All posts skipped (already processed today)
# → normal behavior — wait until tomorrow or clear updated_at in Supabase:
#   UPDATE instagram SET updated_at = NULL;

# One scraper instance not starting
docker compose logs scraper_3
# → check the container logs, ensure .env has required values

# Rate limited by Instagram
# → built-in exponential backoff handles this (up to MAX_RATE_LIMIT_RETRIES)
# → if persistent, reduce concurrent instances temporarily
