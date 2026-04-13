"""
Output Sheet — Google Sheets integration with connection caching, batching,
and retry logic.

Previous implementation re-authenticated and re-opened the spreadsheet on every
single append, which caused Google API rate-limit (429) errors and silent data
loss.  This version:

* Caches the authenticated worksheet object (TTL = 5 min).
* Buffers rows and flushes them in a single ``append_rows`` call — dramatically
  reducing the number of API requests (1 call per batch instead of 1 per row).
* Wraps the append call with tenacity retry + exponential back-off with jitter,
  which is critical when 3 Docker containers share the same service-account
  quota (60 writes/min).
* Returns a boolean so the caller can decide whether to update Supabase.
"""

import logging
import threading
import time

import gspread
from google.oauth2.service_account import Credentials
from gspread.utils import ValueInputOption
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from src.models import CommentStats
from src.settings import (
    OUTPUT_SHEET_COMMENT_STATS,
    SHEETS_CREDENTIALS_FILE,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Connection caching
# ---------------------------------------------------------------------------
_cached_sheet = None
_cache_time: float = 0
_CACHE_TTL: int = 300  # seconds – re-authenticate every 5 minutes


def _get_sheet(sheet_id: str, worksheet_name: str = "MASTER"):
    """Return a cached worksheet, re-authenticating only when the TTL expires."""
    global _cached_sheet, _cache_time

    now = time.time()
    if _cached_sheet is not None and (now - _cache_time) < _CACHE_TTL:
        return _cached_sheet

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(SHEETS_CREDENTIALS_FILE, scopes=scopes)
    client = gspread.authorize(creds)  # type: ignore[assignment]
    sheet = client.open_by_key(sheet_id).worksheet(worksheet_name)

    _cached_sheet = sheet
    _cache_time = now
    logger.info("Google Sheets connection established / refreshed.")
    return sheet


def _invalidate_cache() -> None:
    """Force re-authentication on the next call."""
    global _cached_sheet, _cache_time
    _cached_sheet = None
    _cache_time = 0


# ---------------------------------------------------------------------------
# Row buffer — collects rows and flushes in batches
# ---------------------------------------------------------------------------
_row_buffer: list[list] = []
_buffer_lock = threading.Lock()
_BATCH_SIZE: int = 25  # flush every N rows (1 API call instead of N)


def _add_to_buffer(row: list) -> list[list] | None:
    """
    Add a row to the buffer. Returns a copy of accumulated rows and clears
    the buffer when BATCH_SIZE is reached, otherwise returns None.
    """
    with _buffer_lock:
        _row_buffer.append(row)
        if len(_row_buffer) >= _BATCH_SIZE:
            batch = list(_row_buffer)
            _row_buffer.clear()
            return batch
    return None


def flush_buffer() -> bool:
    """
    Force-flush whatever is in the buffer.  Call this at the end of a queue
    cycle so the last partial batch is not lost.

    Returns:
        True if flush succeeded (or buffer was empty), False on failure.
    """
    with _buffer_lock:
        if not _row_buffer:
            return True
        batch = list(_row_buffer)
        _row_buffer.clear()

    return _append_rows_to_sheet(batch)


# ---------------------------------------------------------------------------
# Retry-wrapped batch append
# ---------------------------------------------------------------------------
@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=2, max=60, jitter=5),
    retry=retry_if_exception_type(
        (gspread.exceptions.APIError, ConnectionError, TimeoutError, OSError)
    ),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _append_rows_with_retry(rows: list[list]) -> None:
    """Append multiple rows in one API call with retry + jitter."""
    try:
        sheet = _get_sheet(OUTPUT_SHEET_COMMENT_STATS)
        sheet.append_rows(rows, value_input_option=ValueInputOption.user_entered)
    except gspread.exceptions.APIError as e:
        # Auth / permission errors → force re-auth on the next retry
        if hasattr(e, "response") and e.response.status_code in (401, 403):
            logger.warning("Auth error from Sheets API — invalidating cache.")
            _invalidate_cache()
        raise


def _append_rows_to_sheet(rows: list[list]) -> bool:
    """
    Wrapper that catches final failures after all retries are exhausted.
    Returns True on success, False on permanent failure.
    """
    try:
        _append_rows_with_retry(rows)
        logger.info(f"Successfully appended {len(rows)} rows to Google Sheets.")
        return True
    except Exception as e:
        logger.error(f"Failed to append {len(rows)} rows to Google Sheets after all retries: {e}")
        _invalidate_cache()
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
async def push_comment_data(comment_stats: CommentStats) -> bool:
    """
    Buffer a comment row and flush to Google Sheets when the batch is full.

    Uses a cached connection, batching, and retries with exponential back-off
    + jitter to stay within Google API quotas even with multiple containers.

    Args:
        comment_stats: The comment data to push.

    Returns:
        True if the row was buffered (and flushed successfully if batch-full),
        False if the flush failed.
    """
    row = [
        comment_stats.username,
        comment_stats.post_url,
        comment_stats.text,
        comment_stats.likes,
        comment_stats.reply_count,
        comment_stats.date_of_comment,
        comment_stats.date,
    ]

    batch = _add_to_buffer(row)
    if batch is not None:
        # Batch is full — flush now
        return _append_rows_to_sheet(batch)

    # Row buffered, no flush needed yet
    return True
