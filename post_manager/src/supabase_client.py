"""
Supabase Client for Video Manager
==================================

Provides Supabase connection for checking existing videos and upserting new ones.
"""

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from supabase import Client, create_client

from src.models import Post
from src.settings import ERROR_TABLE_NAME, SUPABASE_KEY, SUPABASE_URL, TABLE_NAME

# =============================================================================
# SUPABASE CLIENT
# =============================================================================

_supabase_client: Client | None = None


def _normalize_first_comments(raw_data: dict[str, Any]) -> dict[str, Any]:
    """Ensure first_comments is a Python list for Post model parsing."""
    value = raw_data.get("first_comments")
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                raw_data["first_comments"] = parsed
            else:
                raw_data["first_comments"] = []
        except Exception:
            raw_data["first_comments"] = []
    elif value is None:
        raw_data["first_comments"] = []
    return raw_data


def get_supabase_client() -> Client:
    """
    Get a Supabase client instance (singleton).

    Returns:
        Supabase Client

    Raises:
        ValueError: If credentials not found
    """
    global _supabase_client

    if _supabase_client is not None:
        return _supabase_client

    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError(
            "Supabase credentials not found. "
            "Set SUPABASE_URL and SUPABASE_KEY environment variables."
        )

    _supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase_client


# =============================================================================
# POST OPERATIONS
# =============================================================================


def get_existing_post_urls(post_urls: list[str]) -> set[str]:
    """
    Check which post URLs already exist in Supabase.

    Args:
        post_urls: List of post URLs to check

    Returns:
        Set of URLs that already exist in the database
    """
    if not post_urls:
        return set()

    client = get_supabase_client()

    # Query in batches if needed (Supabase has limits)
    existing_urls = set()
    batch_size = 100

    for i in range(0, len(post_urls), batch_size):
        batch = post_urls[i : i + batch_size]

        response = client.table(TABLE_NAME).select("post_url").in_("post_url", batch).execute()

        if response.data:
            for row in response.data:
                row_dict: dict[str, Any] = row  # type: ignore[assignment]
                existing_urls.add(row_dict["post_url"])

    return existing_urls


def get_urls_where_comment_not_found() -> set[str]:
    """
    Get post URLs where comments_exist is False and the row is older than 2 days.

    Returns:
        Set of post URLs with comments_exist = False and updated_at older than 2 days
    """
    client = get_supabase_client()
    cutoff = (datetime.now(UTC) - timedelta(days=2)).isoformat()

    response = (
        client.table(TABLE_NAME)
        .select("post_url")
        .eq("comment_exists", False)
        .not_.is_("updated_at", None)
        .lt("updated_at", cutoff)
        .execute()
    )

    urls = set()
    if response.data:
        for row in response.data:
            row_dict: dict[str, Any] = row  # type: ignore[assignment]
            urls.add(row_dict["post_url"])

    return urls


def last_comment_update_urls() -> set[str]:
    """
    Get post URLs updated during the current UTC day.

    These URLs are considered already processed today and should be skipped.

    Returns:
        Set of post URLs with updated_at in [today 00:00:00, tomorrow 00:00:00)
    """

    client = get_supabase_client()
    now_utc = datetime.now(UTC)
    today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + timedelta(days=1)

    # Column is timestamp without timezone in UTC. Use naive datetime strings.
    today_start_str = today_start.replace(tzinfo=None).isoformat()
    tomorrow_start_str = tomorrow_start.replace(tzinfo=None).isoformat()

    urls = set()
    batch_size = 1000
    offset = 0
    while True:
        response = (
            client.table(TABLE_NAME)
            .select("post_url")
            .not_.is_("updated_at", None)
            .gte("updated_at", today_start_str)
            .lt("updated_at", tomorrow_start_str)
            .range(offset, offset + batch_size - 1)
            .execute()
        )
        if response.data:
            for row in response.data:
                row_dict: dict[str, Any] = row  # type: ignore[assignment]
                urls.add(row_dict["post_url"])
            if len(response.data) < batch_size:
                break
            offset += batch_size
        else:
            break
    return urls


def get_post_by_url(post_url: str) -> Post | None:
    """
    Get a post by its URL.

    Args:
        post_url: Instagram post URL

    Returns:
        Post model or None if not found
    """
    client = get_supabase_client()

    response = client.table(TABLE_NAME).select("*").eq("post_url", post_url).limit(1).execute()

    if response.data:
        raw_data: dict[str, Any] = response.data[0]  # type: ignore[assignment]
        raw_data = _normalize_first_comments(raw_data)
        return Post(**raw_data)
    return None


def get_posts_by_urls(post_urls: list[str]) -> list[Post]:
    """
    Get multiple posts by their URLs.
    Get all posts where comment_exists is True and post_exists is True,
    and sort by comment_count ascending.

    Args:
        post_urls: List of post URLs

    Returns:
        List of Post models for existing posts
    """
    if not post_urls:
        return []

    client = get_supabase_client()
    posts = []
    batch_size = 100

    for i in range(0, len(post_urls), batch_size):
        batch = post_urls[i : i + batch_size]

        # And the comment exists is True, sort the posts by ascending order of comment_count
        response = (
            client.table(TABLE_NAME)
            .select("*")
            .in_("post_url", batch)
            .eq("comment_exists", True)
            .eq("post_exists", True)
            .order("comment_count", desc=False)
            .execute()
        )

        for row in response.data:
            try:
                row_data: dict[str, Any] = row  # type: ignore[assignment]
                row_data = _normalize_first_comments(row_data)
                posts.append(Post(**row_data))  # type: ignore[call-arg]
            except Exception as e:
                logging.error(f"Error parsing post data: {e} - Data: {row}")
                continue

    return posts


def upsert_post(post: Post) -> Post | None:
    """
    Insert a new post or update an existing one.

    Args:
        post: PostCreate model with post data

    Returns:
        Post model of the upserted record, or None on error
    """
    client = get_supabase_client()

    insert_data = {
        "post_url": post.post_url,
        "username": post.username,
        "media_id": post.media_id,
        "hmac_claim": post.hmac_claim,
        "comment_count": post.comment_count,
        "has_next_comments": post.has_next_comments,
        "first_comments": post.first_comments,
        "post_exists": post.post_exists,
    }

    # Upsert based on post_url
    response = client.table(TABLE_NAME).upsert(insert_data, on_conflict="post_url").execute()

    if response.data:
        raw_data: dict[str, Any] = response.data[0]  # type: ignore[assignment]
        raw_data = _normalize_first_comments(raw_data)
        return Post(**raw_data)  # type: ignore[call-arg]
    return None


def bulk_upsert_posts(posts: list[Post]) -> int:
    """
    Insert or update multiple posts.

    Args:
        posts: List of PostCreate models

    Returns:
        Number of posts processed
    """
    if not posts:
        return 0

    client = get_supabase_client()

    insert_data = [
        {
            "post_url": p.post_url,
            "username": p.username,
            "media_id": p.media_id,
            "hmac_claim": p.hmac_claim,
            "comment_count": p.comment_count,
            "has_next_comments": p.has_next_comments,
            "first_comments": p.first_comments,
            "post_exists": p.post_exists,
        }
        for p in posts
    ]

    # Batch upsert
    batch_size = 100
    processed = 0

    for i in range(0, len(insert_data), batch_size):
        batch = insert_data[i : i + batch_size]

        response = client.table(TABLE_NAME).upsert(batch, on_conflict="post_url").execute()

        processed += len(response.data)

    return processed


def push_error_post(post_url: str, error_message: str) -> None:
    """
    Insert a new post or update an existing one.

    Args:
        post_url: The URL of the post that failed
        error_message: The error message associated with the failure

    Returns:
        None
    """
    client = get_supabase_client()

    insert_data = {
        "post_url": post_url,
        "error": error_message,
    }

    # Upsert based on post_url
    client.table(ERROR_TABLE_NAME).upsert(insert_data, on_conflict="post_url").execute()

    logging.info(f"Logged error for post {post_url} with message: {error_message}")

    return None
