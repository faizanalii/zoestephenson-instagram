# Instagram Comment Scraper — Cookie-Free Pipeline

Finds comments by a target username on Instagram posts and reels, extracts
likes and reply counts, and pushes results to Supabase and Google Sheets.

**The entire pipeline is cookie-free.** No Instagram accounts, no sessions,
no login. Everything works off Instagram's public pages with rotating
residential proxies and TLS fingerprint impersonation.

---

## Flow

```
  ┌──────────────┐       ┌───────────────────┐       ┌──────────────┐
  │ Google Sheet  │       │     Redis 7        │       │   Supabase    │
  │ (input URLs)  │       │  (job queues)      │       │  (database)   │
  └──────┬───────┘       └────────┬──────────┘       └──────▲───────┘
         │                        │                         │
         ▼                        ▼                         │
  ┌──────────────┐       ┌──────────────┐                  │
  │ post_manager  │──RPUSH→│ instagram:40 │                  │
  │  (producer)   │       │ instagram:120│                  │
  │               │       │ instagram:240│                  │
  │ cookie-free   │       │ instagram:rest│                  │
  │ rnet + proxy  │       └──────┬───────┘                  │
  └──────────────┘              │ LPOP                       │
                                ▼                            │
                         ┌──────────────┐                   │
                         │   scraper     │──upsert───────────┘
                         │  (consumer)   │
                         │               │
                         │ cookie-free   │
                         │ curl_cffi +   │
                         │ proxy rotation│
                         └──────────────┘
```

### Step by step

1. **post_manager** reads a Google Sheet → deduplicates against Supabase
   and Redis processing queues → fetches each post page **without cookies**
   (rnet, Chrome 137 TLS, random proxy per post) → extracts `media_id`,
   `hmac_claim`, `comment_count`, `first_comments` from embedded JSON →
   upserts to the `instagram` Supabase table → RPUSHes `Post` jobs to the
   appropriate Redis priority queue based on comment count.

2. **scraper** LPOPs `Post` jobs from Redis → checks cached
   `first_comments` from Supabase → if not found, fetches the page +
   paginates through Instagram's public GraphQL API (**no cookies**,
   `curl_cffi` with new proxy per page) → when the target username's
   comment is found, makes a single child-comments API call to verify the
   reply count → upserts to `instagram_stats` table + Google Sheets output.

---

## Architecture

| Module | What It Does | Tech |
|--------|-------------|------|
| `redis_queuing` | Redis 7 server — holds job queues, processing state | Docker, RDB+AOF persistence |
| `post_manager` | Producer — reads sheet, fetches metadata, pushes jobs | rnet, BeautifulSoup, jsonparse |
| `scraper` | Consumer — finds comments, verifies replies, writes results | curl_cffi, rnet, tenacity |
| `account_manager` | **No longer used** — every module is cookie-free | — |

### Module Details

#### post_manager (producer)

```
Google Sheet → get_post() → Post object → Supabase upsert → Redis RPUSH

  get_post(post_url, username):
    1. random proxy from configured country pool
    2. rnet.get(post_url) — Chrome 137 TLS, HTTP/2, no cookies
    3. extract <script type="application/json"> blocks
    4. find_key() for media_id, hmac_claim, comment_count, first_comments
    5. return Post object
```

Each post in a batch gets its own random proxy via `asyncio.gather`.

#### scraper (consumer)

```
Redis LPOP → find_comment() → ScrapeResult → Supabase upsert

  find_comment(post, source_queue):
    1. search post.first_comments cache (from Supabase) — skip if found
    2. rnet.get(post_url) — fetch page, extract GraphQL tokens
    3. for each page of comments:
       a. new random proxy
       b. POST /graphql/query (PolarisPostCommentsPaginationQuery, 50/page)
       c. search edges for target username
    4. if found: GET /api/graphql (PolarisPostChildCommentsQuery) → reply count
    5. return ScrapeResult → main.py writes to Supabase + Sheets
```

---

## Setup

### Prerequisites

- Python 3.13+
- Docker (for Redis)
- A Supabase project with the tables below
- A residential rotating proxy service (URL pattern: `http://user__cr.{COUNTRY}:pass@host:port`)
- A Google Sheets service account JSON key

### 1. Start Redis

```bash
cd redis_queuing

# Copy the example env, set a strong password
cp .env.example .env
# Edit .env: REDIS_PASSWORD=...

# Update docker-compose.yml and redis.conf with the same password
# Replace YOUR_STRONG_PASSWORD_HERE in both files

# Start
docker compose up -d

# Verify
docker ps | grep redis
redis-cli -h localhost -p 6379 -a YOUR_PASSWORD ping
# → PONG
```

### 2. Configure and Run Post Manager

```bash
cd post_manager

cp .env.example .env
# Edit .env:
#   REDIS_HOST, REDIS_PORT, REDIS_PASSWORD, REDIS_DB
#   SUPABASE_URL, SUPABASE_KEY
#   PROXY (the rotating proxy template)
#   INPUT_SHEET_COMMENT_STATS (Google Sheet ID)

# Make sure zoecredentials.json exists (Google Sheets service account)

# Run once (processes the sheet, populates queues, exits)
python -m src.main
```

The post manager runs once per invocation — reads the sheet, processes
all rows in batches of `POST_FETCH_BATCH_SIZE` (default 5), pushes
everything to Redis, and exits.

### 3. Run Scraper

```bash
cd scraper

cp .env.example .env
# Edit .env:
#   REDIS_HOST, REDIS_PORT, REDIS_PASSWORD, REDIS_DB
#   SUPABASE_URL, SUPABASE_KEY
#   PROXY (same rotating proxy template)

# Run continuously
python -m src.main
```

The scraper loops forever:

```
while True:
    process instagram:40, instagram:120, instagram:240, instagram:rest in parallel
    sleep 100 seconds
```

---

## Redis Queues

| Queue | Condition | Priority |
|-------|-----------|----------|
| `instagram:40` | ≤ 40 comments | Highest — newest posts |
| `instagram:120` | ≤ 120 comments | High |
| `instagram:240` | ≤ 240 comments | Medium |
| `instagram:rest` | everything else | Low |
| `instagram:processing` | posts currently being scraped | (tracking) |

---

## Supabase Tables

### `instagram` — post metadata (populated by post_manager)

| Column | Type | Notes |
|--------|------|-------|
| `post_url` | text | primary key |
| `username` | text | target username to search for |
| `media_id` | text | Instagram media ID |
| `hmac_claim` | text | HMAC claim token |
| `comment_count` | int | total comments on the post |
| `has_next_comments` | bool | more comments beyond first batch |
| `first_comments` | jsonb | first batch of comment edges |
| `post_exists` | bool | false if page fetch failed |
| `comment_exists` | bool | set by scraper on NOT_FOUND |
| `updated_at` | timestamp | last update time |
| `retry_count` | int | scrape retry counter |

### `instagram_stats` — found comment data (populated by scraper)

| Column | Type | Notes |
|--------|------|-------|
| `post_url` | text | part of unique constraint |
| `username` | text | part of unique constraint |
| `text` | text | comment body |
| `likes` | int | comment like count |
| `reply_count` | int | verified via child-comments API |
| `date_of_comment` | text | YYYY-MM-DD of the comment |
| `created_at` | date | default today, part of unique constraint |

Unique constraint: `(post_url, username, created_at)` — idempotent per day.

### `instagram_error_videos` — dead-lettered posts

| Column | Type |
|--------|------|
| `post_url` | text |
| `error` | text |
| `created_at` | timestamp |

---

## Environment Variables

### Shared (both post_manager and scraper)

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_HOST` | `localhost` | Redis host |
| `REDIS_PORT` | `6379` | Redis port |
| `REDIS_PASSWORD` | — | Redis auth password |
| `REDIS_DB` | `0` | Redis DB number |
| `SUPABASE_URL` | (required) | Supabase project URL |
| `SUPABASE_KEY` | (required) | Supabase service-role key |
| `PROXY` | hardcoded fallback | Proxy URL with `{COUNTRY}` |
| `PROXY_COUNTRIES_LIST` | `de,be,fr,nl,us,gb,ca,au,at` | Countries to rotate |

### post_manager only

| Variable | Default | Description |
|----------|---------|-------------|
| `SHEETS_CREDENTIALS_FILE` | `zoecredentials.json` | Google service account JSON |
| `INPUT_SHEET_COMMENT_STATS` | hardcoded | Google Sheet ID (source) |
| `POST_FETCH_BATCH_SIZE` | `5` | Concurrent page fetches |

### scraper only

| Variable | Default | Description |
|----------|---------|-------------|
| `SHEETS_CREDENTIALS_FILE` | `zoecredentials.json` | Google service account JSON |
| `OUTPUT_SHEET_CREDS_FILE` | `tomsheetcreds.json` | Output sheet credentials |
| `SUPABASE_STATS_TABLE_NAME` | `instagram_stats` | Stats table name |
| `MAX_RETRIES` | `5` | Max re-queue attempts |
| `MAX_PAGINATION_DEPTH` | `300` | Max GraphQL pages per post |
| `MAX_RATE_LIMIT_RETRIES` | `3` | Max rate-limit cooldowns |

---

## Performance Notes

- **Proxy rotation**: each GraphQL page gets a new random proxy. No reuse.
- **Batch fetching**: post_manager fetches up to 5 posts in parallel.
- **Early exit**: scraper stops paginating the instant the target username
  is found — doesn't waste requests scanning all comments.
- **Reply counts**: one extra API call per **found** comment (not per page).
- **Page size**: 50 comments per GraphQL page (fewer requests).
- **Inter-page delay**: 0.3–0.8 seconds between pages.
- **Rate limit cooldown**: 30–60 seconds when Instagram pushes back.

## Testing

```bash
# Scraper — real-world test on a reel
cd scraper
python tests/test_realistic_reel.py

# Post manager — test extraction on a reel + a post
cd post_manager
python tests/test_cookie_free.py
```
