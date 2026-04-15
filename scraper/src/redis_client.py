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
import logging
from datetime import datetime

import redis

from src.models import AccountCookies, Post
from src.settings import (
    KEY_COOKIES_AVAILABLE,
    PROCESSING_QUEUE,
    REDIS_DB,
    REDIS_HOST,
    REDIS_PASSWORD,
    REDIS_PORT,
    TASK_STATE_PREFIX,
)


def _task_state_key(post_url: str, username: str) -> str:
    """
    Build a stable Redis key for a post/username task state.
    Args:
        post_url: The URL of the TikTok post
        username: The username of the user
    Returns:
        A string key in the format "instagram:task_state:{post_url}:{username}
    """

    return f"{TASK_STATE_PREFIX}:{post_url}:{username}"


def _safe_json_loads(raw: str) -> dict:
    """
    Parse JSON strings from Redis and fallback to empty dict on malformed values.
    Args:
        raw: The raw string from Redis
    Returns:
        Parsed dict or empty dict if parsing fails"""

    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    return {}


def _normalize_account_cookie_payload(raw_item: str) -> AccountCookies | None:
    """
    Normalize cookie payloads from Redis into account_id/cookies shape.
    Args:
        raw_item: The raw string item from Redis
    Returns:
        Dict with normalized account_id and cookies or None if invalid
    """

    payload = _safe_json_loads(raw_item)
    if not payload:
        return None

    account_id = payload.get("account_id")
    cookies = payload.get("cookies")

    if isinstance(cookies, dict) and cookies:
        if account_id:
            return AccountCookies(**{"account_id": str(account_id), "cookies": cookies})
        return AccountCookies(**{"account_id": "unknown", "cookies": cookies})

    # Some producers store only the cookie mapping itself.
    if all(isinstance(k, str) for k in payload.keys()) and all(
        isinstance(v, str) for v in payload.values()
    ):
        return AccountCookies(**{"account_id": str(account_id or "unknown"), "cookies": payload})

    return None


def _serialize_payload(payload: dict) -> dict:
    """
    Convert datetime objects to ISO strings for JSON serialization.
    Args:
        payload: Dict that may contain datetime objects
    Returns:
        Dict with all datetime objects converted to ISO strings
    """
    serialized = {}
    for key, value in payload.items():
        if isinstance(value, datetime):
            serialized[key] = value.isoformat()
        else:
            serialized[key] = value
    return serialized


async def get_processing_task(post_url: str, username: str) -> dict | None:
    """
    Fetch persisted task state for a post/username pair.
    Args:
        post_url: The URL of the TikTok post
        username: The username of the user
    Returns:
        Dict with task state or None if no state found
    """

    client = await get_redis_client()

    key = _task_state_key(post_url, username)

    raw_payload: str | None = client.get(key)  # type: ignore[assignment]

    if not raw_payload:
        return None

    payload = _safe_json_loads(raw_payload)

    return payload or None


async def set_processing_task_state(payload: dict) -> bool:
    """
    Persist task state payload for delayed retry/resume behavior.
    Args:
        payload: Dict containing at least post_url and username, along with any retry state info
    Returns:
        True if state was persisted successfully, False otherwise
    """

    post_url = str(payload.get("post_url", "")).strip()
    username = str(payload.get("username", "")).strip()

    if not post_url or not username:
        return False

    client = await get_redis_client()
    key = _task_state_key(post_url, username)

    serializable_payload = _serialize_payload(payload)
    client.set(key, json.dumps(serializable_payload))

    return True


async def delete_processing_task(post_url: str, username: str) -> bool:
    """
    Delete persisted task state for a completed post/username pair.
    Args:
        post_url: The URL of the TikTok post
        username: The username of the user
    Returns:
        True if a task state was deleted, False otherwise
    """

    client = await get_redis_client()
    key = _task_state_key(post_url, username)
    deleted: int = client.delete(key)  # type: ignore[assignment]
    return deleted > 0


async def get_cookies_for_account(account_id: str) -> dict | None:
    """
    Return cookies for a specific account from the available cookie pool.
    Args:
        account_id: The ID of the account to fetch cookies for
    Returns:
        Dict with cookies for the account or None if not found
    """

    client = await get_redis_client()

    for raw_item in client.lrange(KEY_COOKIES_AVAILABLE, 0, -1):  # type: ignore[assignment]
        payload = _normalize_account_cookie_payload(raw_item)

        if not payload:
            continue

        if payload.account_id == str(account_id):
            cookies = payload.cookies
            if isinstance(cookies, dict) and cookies:
                return cookies
    return None


async def get_next_account_with_cookies() -> AccountCookies | None:
    """
    Pop the next account cookie payload from the available cookie queue.
    Returns:
        AccountCookies object or None if no cookies available
    """

    client = await get_redis_client()

    raw_item: str | None = client.lpop(KEY_COOKIES_AVAILABLE)  # type: ignore[assignment]

    logging.info(f"Popped raw cookie item from Redis: {raw_item}")

    if not raw_item:
        return None

    return _normalize_account_cookie_payload(raw_item)


async def push_processing_task(payload: dict) -> bool:
    """
    Compatibility alias used by queue manager to persist retry state.
    Args:
        payload: Dict containing at least post_url and username, along with any retry state info
    Returns:
        True if state was persisted successfully, False otherwise
    """

    return await set_processing_task_state(payload)


async def enqueue_processing_task(payload: dict) -> bool:
    """
    Compatibility alias used by queue manager to persist retry state.
    Args:
        payload: Dict containing at least post_url and username, along with any retry state info
    Returns:
        True if state was persisted successfully, False otherwise
    """

    return await set_processing_task_state(payload)


async def requeue_processing_task(payload: dict) -> bool:
    """
    Compatibility alias used by queue manager to persist retry state.
    Args:
        payload: Dict containing at least post_url and username, along with any retry state info
    Returns:
        True if state was persisted successfully, False otherwise
    """

    return await set_processing_task_state(payload)


async def put_processing_task(payload: dict) -> bool:
    """
    Compatibility alias used by queue manager to persist retry state.
    Args:
        payload: Dict containing at least post_url and username, along with any retry state info
    Returns:
        True if state was persisted successfully, False otherwise
    """

    return await set_processing_task_state(payload)


# =============================================================================
# CONNECTION
# =============================================================================

_redis_client: redis.Redis | None = None


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
    account_cookies: dict[str, dict] = client.lpop(KEY_COOKIES_AVAILABLE)  # type: ignore[assignment]

    if account_cookies:
        return account_cookies
    return None


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


async def pop_post_from_queue(queue_key: str) -> Post | None:
    """
    Pop the next post job from the front of the queue (FIFO).

    Returns:
        Post job object or None if queue is empty
    """
    client = await get_redis_client()
    job_json: str = client.lpop(queue_key)  # type: ignore[assignment]

    if job_json:
        return Post(**json.loads(job_json))
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
    result: int = client.rpush(PROCESSING_QUEUE, post_job.post_url)  # type: ignore[assignment]
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
    Docstring for get_all_post_urls_in_processing_queue

    :param queue_key: Description
    :type queue_key: str
    :return: Description
    :rtype: set[str]
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

    :param post_url: Description
    :type post_url: str
    :param queue_key: Description
    :type queue_key: str
    :return: Description
    :rtype: bool
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


async def pop_video_from_queue(queue_key: str) -> dict | None:
    """
    Pop the next video job from the front of the queue (FIFO).

    Returns:
        Video job dict or None if queue is empty
    """
    client = await get_redis_client()
    job_json: str = client.lpop(queue_key)  # type: ignore[assignment]

    if job_json:
        return json.loads(job_json)
    return None
