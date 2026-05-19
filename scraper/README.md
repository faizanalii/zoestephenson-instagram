# Scraper — Cookie-Free Instagram Comment Finder

Consumes `Post` jobs from Redis queues, runs the cookie-free scraping pipeline
to find comments by a target username, and pushes results to Supabase.

**No Instagram accounts, no cookies, no sessions required.**

## How It Works

```
Redis Queue → find_comment() → ScrapeResult → Supabase + Google Sheets

  1. Check cached first_comments (from Supabase — skip if found)
  2. Fetch post page (rnet, Chrome 137 TLS, proxy, no cookies)
  3. Extract tokens: csrf_token, app_id, media_id, lsd, dtsg, hmac_claim
  4. GraphQL pagination loop:
     - POST /graphql/query (curl_cffi, Chrome 142 TLS, rotating proxies)
     - 50 comments per page, sorted by "popular"
     - Search each page for target username
     - Per-page proxy rotation avoids IP rate limits
  5. When found → child-comments API verifies reply count (edges length)
  6. Push CommentStats to Supabase (instagram_stats table)
```

## Queue Processing

Runs all four priority queues in parallel every 100 seconds:

```
instagram:40   → highest priority (≤ 40 comments)
instagram:120  → high priority   (≤ 120 comments)
instagram:240  → medium priority (≤ 240 comments)
instagram:rest → low priority    (everything else)
```

## Running

```bash
# With Docker
docker build -t scraper .
docker run --rm --env-file .env scraper

# Without Docker
cp .env.example .env
python -m src.main
```

## Environment Variables

See the project README for the full list. Key variables:

- `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`, `REDIS_DB`
- `SUPABASE_URL`, `SUPABASE_KEY`
- `PROXY` — proxy URL template with `{COUNTRY}` placeholder
- `PROXY_COUNTRIES_LIST` — comma-separated country codes
- `MAX_RETRIES` (default 5)
- `MAX_RATE_LIMIT_RETRIES` (default 3)

## Test

```bash
# Manual integration test (needs proxy)
python tests/test_comment.py

# End-to-end reel test
python tests/test_realistic_reel.py
```
