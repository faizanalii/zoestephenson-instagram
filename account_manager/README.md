# Account Manager

Keeps Instagram sessions warm and continuously pushes fresh cookies to Redis.

It now leases accounts dynamically from Supabase instead of reading `accounts.txt` at runtime.

## Docker

Build image:

```bash
docker build -t account-manager:latest .
```

Run one isolated account container:

```bash
docker run --rm \
	--name account-manager-1 \
	--env-file .env \
	-e WORKER_ID=account-manager-1 \
	-v account-manager-cookies:/app/downloaded_files/account_cookies \
	account-manager:latest
```

## Multi-account strategy

For separation and parallelism, one container per account is the safest pattern:

- Each container has its own process/browser lifecycle.
- One account crashing or getting challenged does not block others.
- All containers push cookies independently to the same Redis pool.

Use the provided Compose file:

```bash
docker compose up -d --build --scale account-manager=4
```

Every replica runs the same image and follows the same flow:

- Check Redis cookie pool size.
- If the pool is already full, sleep for `COOKIE_POOL_IDLE_SLEEP_SECONDS`.
- If the pool needs cookies, claim exactly one account from Supabase.
- Mark `in_use=true` and set lease metadata so no other replica can take it.
- Try local cookie restore first; fall back to email/password login if needed.
- Keep the browser alive, push cookies to Redis, and heartbeat the lease.

## Supabase table requirements

The `instagram_accounts` table needs these columns:

- `id`
- `email`
- `password`
- `in_use` (`boolean`)
- `error` (`text`)
- `skip_account` (`boolean`, default `false`)
- `claimed_by` (`text`)
- `claimed_at` (`timestamp`)
- `last_heartbeat` (`timestamp`)

Selection rules used by the worker:

- claim only rows where `skip_account = false`
- prefer rows where `in_use = false`
- reclaim rows with stale `last_heartbeat`
- if login fails or Instagram shows a challenge/checkpoint, store the message in `error` and set `skip_account = true`

## Local cookie persistence

Each account stores a cookie jar under `COOKIE_STORAGE_DIR`.

Mount that path to a persistent volume so a restarted container can try cookies first before using the password again.

## Environment variables

- `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`, `REDIS_DB`
- `SUPABASE_URL`, `SUPABASE_KEY`
- `ACCOUNTS_TABLE_NAME` (default: `instagram_accounts`)
- `WORKER_ID` (defaults to container hostname)
- `ACCOUNT_POLL_INTERVAL_SECONDS` (default: `10`)
- `ACCOUNT_LEASE_TIMEOUT_SECONDS` (default: `180`)
- `ACCOUNT_HEARTBEAT_INTERVAL_SECONDS` (default: `30`)
- `COOKIE_POOL_IDLE_SLEEP_SECONDS` (default: `20`)
- `COOKIE_STORAGE_DIR` (default: `downloaded_files/account_cookies`)
- `COOKIE_REFRESH_INTERVAL`
- `MAX_COOKIES_POOL_SIZE`
