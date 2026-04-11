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

from src.models import Post
from src.settings import (
    KEY_COOKIES_AVAILABLE,
    PROCESSING_QUEUE,
    REDIS_DB,
    REDIS_HOST,
    REDIS_PASSWORD,
    REDIS_PORT,
)

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
    token_json: str = client.lpop(KEY_COOKIES_AVAILABLE)  # type: ignore[assignment]

    if token_json:
        return json.loads(token_json)
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
    Docstring for get_all_video_urls_in_queue

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
