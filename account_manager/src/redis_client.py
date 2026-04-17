"""
Redis Client — cookie-pool operations for the Account Manager.

Redis Keys:
    cookies:available    (LIST)  – Cookies ready for use by scraper workers
"""

import json
import logging

import redis

from src.settings import (
    KEY_COOKIES_AVAILABLE,
    MAX_COOKIES_POOL_SIZE,
    REDIS_DB,
    REDIS_HOST,
    REDIS_PASSWORD,
    REDIS_PORT,
)

logger = logging.getLogger(__name__)

_redis_client: redis.Redis | None = None


def get_redis_client() -> redis.Redis:
    """Return a singleton Redis client, reconnecting if needed."""
    global _redis_client

    if _redis_client is not None:
        try:
            _redis_client.ping()
            return _redis_client
        except redis.ConnectionError:
            _redis_client = None

    _redis_client = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD,
        db=REDIS_DB,
        decode_responses=True,
        socket_timeout=10,
        socket_connect_timeout=10,
        retry_on_timeout=True,
    )
    _redis_client.ping()
    logger.info("Redis connected at %s:%s", REDIS_HOST, REDIS_PORT)
    return _redis_client


def get_available_cookies_count() -> int:
    """Return current size of the cookies:available list."""
    client = get_redis_client()
    return client.llen(KEY_COOKIES_AVAILABLE)


def is_pool_full() -> bool:
    """True when the pool has >= MAX_COOKIES_POOL_SIZE entries."""
    return get_available_cookies_count() >= MAX_COOKIES_POOL_SIZE


def push_cookies(account_id: str, cookies: dict[str, str]) -> bool:
    """Push an account's cookies to the available pool in Redis.

    Payload format matches what the scraper's `get_next_account_with_cookies`
    expects:  ``{"account_id": "...", "cookies": {...}}``
    """
    payload = json.dumps({"account_id": account_id, "cookies": cookies})
    client = get_redis_client()
    client.rpush(KEY_COOKIES_AVAILABLE, payload)
    logger.info(
        "Pushed cookies for account=%s (pool size now %s)",
        account_id,
        client.llen(KEY_COOKIES_AVAILABLE),
    )
    return True
