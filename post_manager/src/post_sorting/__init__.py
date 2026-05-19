"""
Post Sorting — cookie-free Instagram post metadata extraction.

Fetches a post page (no cookies), extracts media_id, hmac_claim,
comment_count, and first_comments from the embedded JSON, then
builds a Post object ready for Supabase upsert and Redis queuing.

Each post gets its own random proxy from the configured pool.
"""

import logging

from src.models import Post
from src.post_sorting.scraper import get_post_page
from src.post_sorting.utils import (
    filter_scripts_with_jsons,
    get_comment_count,
    get_first_comments,
    get_hmac_claim,
    get_media_id,
    get_page_scripts,
    get_random_proxy,
    has_next_comments,
)


def _is_reel_url(post_url: str) -> bool:
    normalized = post_url.lower()
    return "/reel/" in normalized or "/reels/" in normalized


async def get_post(post_url: str, username: str) -> Post:
    """
    Fetch a single post's metadata — cookie-free, with a random proxy.

    Args:
        post_url: Instagram post or reel URL.
        username: Target username for this post.
    Returns:
        Post object with extracted metadata (or post_exists=False on failure).
    """
    logging.info("Fetching post data (cookie-free) for URL: %s", post_url)

    try:
        proxy = await get_random_proxy()
        page_content = await get_post_page(post_url=post_url, proxy=proxy)
    except Exception as exc:
        logging.error(
            "Page fetch failed for %s: %s. Returning post_exists=False.",
            post_url,
            exc,
        )
        return Post(post_url=post_url, username=username, post_exists=False)

    scripts = await get_page_scripts(page_content)
    logging.info("Extracted %s script tags from %s", len(scripts), post_url)

    json_scripts: list[dict] = await filter_scripts_with_jsons(scripts)
    return await _build_post_from_json_scripts(post_url, username, json_scripts)


async def _build_post_from_json_scripts(
    post_url: str,
    username: str,
    json_scripts: list[dict],
) -> Post:
    comment_count: int = await get_comment_count(json_scripts)
    media_id: str | None = await get_media_id(json_scripts)
    hmac_claim: str | None = await get_hmac_claim(json_scripts)
    first_comments: list | None = await get_first_comments(json_scripts)
    next_comments: bool | None = await has_next_comments(json_scripts)
    is_reel: bool = _is_reel_url(post_url)

    if not media_id or not hmac_claim:
        logging.warning(
            "Media ID or HMAC claim not found for %s. Returning partial data.",
            post_url,
        )
        return Post(
            post_url=post_url,
            username=username,
            comment_count=comment_count,
            media_id=None,
            hmac_claim=None,
            first_comments=first_comments or [],
            has_next_comments=True if is_reel else bool(next_comments),
            post_exists=False,
        )

    logging.info(
        "Successfully extracted data for %s: media_id=%s, comment_count=%s, is_reel=%s",
        post_url,
        media_id,
        comment_count,
        is_reel,
    )

    return Post(
        post_url=post_url,
        username=username,
        comment_count=comment_count,
        media_id=media_id,
        hmac_claim=hmac_claim,
        first_comments=first_comments or [],
        has_next_comments=True if is_reel else bool(next_comments),
        post_exists=True,
    )


def _post_has_required_data(post: Post) -> bool:
    """
    Check that a post has the minimum fields needed for the scraper.

    With cookie-free extraction, first_comments never carry
    child_comment_count, so we only require media_id + hmac_claim.
    The scraper handles full pagination independently.
    """
    if not post.media_id or not post.hmac_claim:
        return False
    return True
