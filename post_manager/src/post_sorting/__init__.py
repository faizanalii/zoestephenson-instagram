"""
Post Sorting Utilities for the Instagram Post Manager application.
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
    has_next_comments,
)


async def get_post(post_url: str, username: str) -> Post:
    """
    Get the post data from the given URL.

    Args:
        post_url: The URL of the Instagram post
        username: The username of the post owner
    Returns:
        A Post object containing the post data
    """

    logging.info(f"Fetching post data for URL: {post_url}")

    page_content: str = await get_post_page(post_url)

    scripts: list = await get_page_scripts(page_content)

    logging.info(f"Extracted {len(scripts)} script tags from the {post_url} page")

    json_scripts: list[dict] = await filter_scripts_with_jsons(scripts)

    comment_count: int = await get_comment_count(json_scripts)
    media_id: str | None = await get_media_id(json_scripts)
    hmac_claim: str | None = await get_hmac_claim(json_scripts)
    first_comments: list | None = await get_first_comments(json_scripts)
    next_comments: bool | None = await has_next_comments(json_scripts)

    if not media_id or not hmac_claim:
        logging.warning(f"Media ID or HMAC claim not found for {post_url}. Returning partial data.")
        return Post(
            post_url=post_url,
            username=username,
            comment_count=comment_count,
            media_id=None,
            hmac_claim=None,
            first_comments=first_comments or [],
            has_next_comments=next_comments,
            post_exists=False,
        )

    logging.info(
        f"Successfully extracted data for {post_url}: media_id={media_id}, hmac_claim={hmac_claim}"
    )

    return Post(
        post_url=post_url,
        username=username,
        comment_count=comment_count,
        media_id=media_id,
        hmac_claim=hmac_claim,
        first_comments=first_comments or [],
        has_next_comments=next_comments,
        post_exists=True,
    )
