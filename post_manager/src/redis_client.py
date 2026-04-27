"""
Redis Client - Connection helper for token and video queue management
======================================================================

Provides Redis connection for the scraper.

Redis Keys:
    cookies:available    (LIST)  - Cookies ready for use
    cookies:in_use       (SET)   - Cookies currently being used by workers
    cookies:dead         (SET)   - Expired/invalid cookies
    videos:processing   (LIST)  - Videos waiting to be processed
"""

import json

import redis

from src.models import AccountCookies, Post
from src.settings import (
    COOKIE_FETCH_REUSE_COUNT,
    KEY_COOKIES_AVAILABLE,
    PROCESSING_QUEUE,
    REDIS_DB,
    REDIS_HOST,
    REDIS_PASSWORD,
    REDIS_PORT,
)


def _safe_json_loads(raw: str) -> dict:
    """
    Parse Redis JSON payloads defensively.
    Args:
    raw: The raw JSON string from Redis
    Returns:
        dict: Parsed JSON or empty dict on failure
    """
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    return {}


def _normalize_account_cookie_payload(raw_item: str) -> AccountCookies | None:
    """
    Normalize cookie payloads into account_id/cookies shape.

    Args:
        raw_item: The raw JSON string from Redis

    Returns:
        AccountCookies | None: Normalized account cookies or None on failure
    """
    payload = _safe_json_loads(raw_item)
    if not payload:
        return None

    account_id = payload.get("account_id")
    cookies = payload.get("cookies")

    if isinstance(cookies, dict) and cookies:
        return AccountCookies(
            account_id=str(account_id or "unknown"),
            cookies={str(key): str(value) for key, value in cookies.items()},
        )

    if all(isinstance(key, str) for key in payload.keys()) and all(
        isinstance(value, str) for value in payload.values()
    ):
        return AccountCookies(
            account_id=str(account_id or "unknown"),
            cookies={str(key): str(value) for key, value in payload.items()},
        )

    return None


# =============================================================================
# CONNECTION
# =============================================================================

_redis_client: redis.Redis | None = None
_cached_cookie_payloads: list[AccountCookies] = []
_cookie_cache_use_count: int = 0


async def get_redis_client(
    host: str | None = None,
    port: int | None = None,
    password: str | None = None,
    db: int | None = None,
) -> redis.Redis:
    """
    Get a Redis client instance.

    Uses singleton pattern - returns existing connection if available.

    Args:
        host: Redis host (default: from REDIS_HOST env var)
        port: Redis port (default: from REDIS_PORT env var)
        password: Redis password (default: from REDIS_PASSWORD env var)
        db: Redis database number (default: from REDIS_DB env var)

    Returns:
        redis.Redis: Connected Redis client

    Raises:
        redis.ConnectionError: If connection fails
    """
    global _redis_client

    if _redis_client is not None:
        try:
            _redis_client.ping()
            return _redis_client
        except redis.ConnectionError:
            _redis_client = None

    _redis_client = redis.Redis(
        host=host or REDIS_HOST,
        port=port or REDIS_PORT,
        password=password or REDIS_PASSWORD,
        db=db or REDIS_DB,
        decode_responses=True,
        socket_timeout=10,
        socket_connect_timeout=10,
        retry_on_timeout=True,
    )

    # Test connection
    _redis_client.ping()

    return _redis_client


async def close_redis_connection() -> None:
    """
    Close the Redis connection.

    Call this when shutting down the token generator.
    """
    global _redis_client

    if _redis_client is not None:
        _redis_client.close()
        _redis_client = None


async def get_available_cookies_count() -> int:
    """
    Get the current number of available cookies in the pool.

    Returns:
        int: Number of cookies in cookies:available list
    """
    client = await get_redis_client()
    result: int = client.llen(KEY_COOKIES_AVAILABLE)  # type: ignore[assignment]
    return result


async def is_redis_connected() -> bool:
    """
    Check if Redis is connected and responsive.

    Returns:
        bool: True if connected
    """
    try:
        client = await get_redis_client()
        client.ping()
        return True
    except (redis.ConnectionError, redis.TimeoutError):
        return False


# =============================================================================
# TOKEN OPERATIONS
# =============================================================================


async def get_cookies() -> dict | None:
    """
    Get an available cookie from the pool.

    Returns:
        dict with cookie data or None if no cookies available
    """
    client = await get_redis_client()
    token_json: str = client.lpop(KEY_COOKIES_AVAILABLE)  # type: ignore[assignment]

    if token_json:
        return json.loads(token_json)
    return None


async def get_available_account_cookies(limit: int = 3) -> list[AccountCookies]:
    """
    Read available cookie payloads without consuming the Redis pool.

    Args:
        limit: Maximum number of account cookies to return

    Returns:
        List of AccountCookies objects
    """
    global _cached_cookie_payloads
    global _cookie_cache_use_count

    if _cached_cookie_payloads and _cookie_cache_use_count < max(1, COOKIE_FETCH_REUSE_COUNT):
        _cookie_cache_use_count += 1
        return _cached_cookie_payloads[:limit]

    client = await get_redis_client()
    cookie_payloads: list[AccountCookies] = []
    seen_accounts: set[str] = set()

    for raw_item in client.lrange(KEY_COOKIES_AVAILABLE, 0, -1):  # type: ignore[assignment]
        payload = _normalize_account_cookie_payload(raw_item)
        if payload is None or not payload.cookies:
            continue
        if payload.account_id in seen_accounts:
            continue

        cookie_payloads.append(payload)
        seen_accounts.add(payload.account_id)

        if len(cookie_payloads) >= limit:
            break

    if cookie_payloads:
        _cached_cookie_payloads = cookie_payloads
        _cookie_cache_use_count = 1
    else:
        _cached_cookie_payloads = []
        _cookie_cache_use_count = 0

    return cookie_payloads


# =============================================================================
# VIDEO QUEUE OPERATIONS (FIFO)
# =============================================================================


async def push_post_to_queue(post_job: Post, queue_key: str) -> int:
    """
    Push a post job to the end of the queue (FIFO).

    Args:
        post_job: Dict with post_url, username, post_id, odin_id, cursor

    Returns:
        New length of the queue
    """
    client = await get_redis_client()
    result: int = client.rpush(queue_key, post_job.model_dump_json())  # type: ignore[assignment]
    return result


async def push_posts_to_queue(post_jobs: list[Post], queue_key: str) -> int:
    """
    Push multiple post jobs to the queue in order.

    Args:
        post_jobs: List of post job dicts (will be added in order)

    Returns:
        New length of the queue
    """
    client = await get_redis_client()

    if not post_jobs:
        return 0

    # RPUSH adds to end, so first item in list will be first out
    json_jobs = [job.model_dump_json() for job in post_jobs]
    result: int = client.rpush(queue_key, *json_jobs)  # type: ignore[assignment]
    return result


async def pop_post_from_queue(queue_key: str) -> dict | None:
    """
    Pop the next post job from the front of the queue (FIFO).

    Returns:
        Post job dict or None if queue is empty
    """
    client = await get_redis_client()
    job_json: str = client.lpop(queue_key)  # type: ignore[assignment]

    if job_json:
        return json.loads(job_json)
    return None


async def get_video_queue_length(queue_key: str) -> int:
    """
    Get the current number of videos in the queue.

    Returns:
        Number of videos waiting to be processed
    """
    client = await get_redis_client()
    result: int = client.llen(queue_key)  # type: ignore[assignment]
    return result


async def is_video_queue_empty(queue_key: str) -> bool:
    """
    Check if the video queue is empty.

    Returns:
        True if no videos in queue
    """
    return await get_video_queue_length(queue_key) == 0


async def add_url_to_processing_queue(post_job: Post) -> int:
    """
    Add a post job to the processing queue.

    Args:
        post_job: Post object with post_url, username, post_id, odin_id, cursor

    Returns:
        New length of the processing queue
    """
    client = await get_redis_client()
    result: int = client.rpush(PROCESSING_QUEUE, post_job.model_dump_json())  # type: ignore[assignment]
    return result


async def remove_url_from_processing_queue(post_url: str) -> bool:
    """
    Remove a post job from the processing queue by post_url.

    Args:
        post_url: The URL of the TikTok post to remove
    Returns:
        True if a job was removed, False otherwise
    """
    client = await get_redis_client()
    for item in client.lrange(PROCESSING_QUEUE, 0, -1):  # type: ignore[assignment]
        try:
            job = json.loads(item)
            if job.get("post_url") == post_url:
                client.lrem(PROCESSING_QUEUE, 1, item)  # type: ignore[assignment]
                return True
        except json.JSONDecodeError:
            continue
    return False


async def get_all_post_urls_in_processing_queue() -> set[str]:
    """
    Get all post URLs currently in the processing queue.

    Returns:
        Set of post URLs in the processing queue
    """
    client = await get_redis_client()
    video_urls = set()

    for item in client.lrange(PROCESSING_QUEUE, 0, -1):  # type: ignore[assignment]
        try:
            job = json.loads(item)
            video_url = job.get("post_url")
            if video_url:
                video_urls.add(video_url)
        except Exception:
            continue

    return video_urls


async def is_video_url_in_queue(post_url: str, queue_key: str) -> bool:
    """
    Docstring for is_video_url_in_queue

    Args:
        post_url: The URL of the TikTok post to check
        queue_key: The Redis queue key to check

    Returns:
        True if the post URL is in the queue, False otherwise
    """

    client = await get_redis_client()

    for item in client.lrange(queue_key, 0, -1):  # type: ignore[assignment]
        try:
            job = json.loads(item)
            if job.get("post_url") == post_url:
                return True
        except Exception:
            continue
    return False
