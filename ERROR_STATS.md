# ERROR_STATS

Generated: 2026-10-08 (UTC). Source tables: `instagram_error_videos` (errors) and `instagram` (posts).

## Key result

**278 videos** that were once pushed into `instagram_error_videos` with a
`post_page_fetch_failed` error have since been **successfully reprocessed** —
they now have `comment_exists = true` and `updated_at` within the last two days
(today/yesterday).

## Error table overview

| metric | count |
|---|---|
| Total rows in `instagram_error_videos` | 509 |
| Distinct `post_url` | 509 |

Breakdown by error type:

| error prefix | count |
|---|---|
| `post_page_fetch_failed` | 365 |
| `graphql_errors` | 136 |
| other | 8 |

## `post_page_fetch_failed` subset

| metric | count |
|---|---|
| Rows matching `post_page_fetch_failed%` | 365 |
| Distinct `post_url` | 365 |
| Oldest `created_at` | 2026-07-24 07:35:52 UTC |
| Newest `created_at` | 2026-07-24 07:47:03 UTC |

> All 365 were logged in a single ~11-minute burst on 2026-07-24 (a proxy /
> connectivity outage), not spread over time.

Reason breakdown:

| reason | count |
|---|---|
| `RetryError` (connection error) | 364 |
| `dtsg_token_missing` | 1 |

## Reprocessing outcome (cross-referenced with `instagram` table)

Every one of the 365 URLs still exists in the `instagram` table (0 missing).

| `comment_exists` | count | `updated_at` |
|---|---|---|
| `true` | **278** | 2026-10-07 or 2026-10-08 (today/yesterday) |
| `false` | 87 | 2026-10-07 or 2026-10-08 (today/yesterday) |
| `null` | 0 | — |

### Answer to the question

Videos with `comment_exists = true` **and** `updated_at` today/yesterday:
**278** (of 365).

In other words:

- **278 (76%)** — reprocessed successfully, comment found.
- **87 (24%)** — reprocessed but comment NOT found (`comment_exists = false`).
- **0** — still stuck / unresolved (no null or stale `updated_at`).

## Notes

- The `instagram_error_videos` table is write-only in the codebase; nothing
  reads it back. Reprocessing happens indirectly via the post_manager, which
  re-queues posts from Google Sheets on its next cycle (~every 8 hours) as long
  as they are not already marked found/not-found/processing-today.
- `updated_at` is only set on FOUND or NOT_FOUND outcomes, so every row above
  with a recent `updated_at` has genuinely been re-scraped after its error.
