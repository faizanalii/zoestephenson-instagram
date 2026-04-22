"""
Post Sorting Utilities for the Instagram Post Manager application.
"""

import logging

from src.models import AccountCookies, Post
from src.post_sorting.scraper import get_post_page
from src.post_sorting.utils import (
    filter_scripts_with_jsons,
    first_comments_have_reply_metadata,
    get_comment_count,
    get_first_comments,
    get_hmac_claim,
    get_media_id,
    get_page_scripts,
    get_random_proxy,
    has_next_comments,
)
from src.redis_client import get_available_account_cookies
from src.settings import POST_PAGE_COOKIE_RETRY_ATTEMPTS


def _is_reel_url(post_url: str) -> bool:
    """
    Is the given post URL a reel URL?
    Args:
        post_url: The URL of the Instagram post.
    Returns:
        bool: True if the URL is a reel URL, False otherwise.
    """
    normalized = post_url.lower()
    return "/reel/" in normalized or "/reels/" in normalized


async def get_post(post_url: str, username: str) -> Post:
    """
    Get the post data from the given URL.

    Args:
        post_url: The URL of the Instagram post.
        username: The username of the post owner.
    Returns:
        A Post object containing the post data.
    """

    logging.info("Fetching post data for URL: %s", post_url)

    # If the URL is a reel URL, we can skip using account cookies as the first comments
    # are not available for reels regardless of authentication
    if _is_reel_url(post_url):
        logging.info("URL %s identified as a reel. Using anonymous fetch.", post_url)
        page_content = await get_post_page(post_url)
        scripts: list = await get_page_scripts(page_content)
        json_scripts: list[dict] = await filter_scripts_with_jsons(scripts)
        return await _build_post_from_json_scripts(post_url, username, json_scripts)

    cookie_candidates = await get_available_account_cookies(limit=POST_PAGE_COOKIE_RETRY_ATTEMPTS)

    if not cookie_candidates:
        logging.warning(
            "No Redis cookies available for %s. Falling back to anonymous fetch.",
            post_url,
        )
        cookie_candidates = [AccountCookies(account_id="anonymous", cookies={})]

    fallback_post: Post | None = None

    for attempt_number, cookie_payload in enumerate(cookie_candidates, start=1):
        post = await _fetch_post_with_cookie_candidate(
            post_url=post_url,
            username=username,
            cookie_payload=cookie_payload,
            attempt_number=attempt_number,
        )
        post.retry_count = attempt_number - 1

        if _post_has_required_data(post):
            return post

        fallback_post = post
        logging.warning(
            "Post %s is still missing required comment metadata after attempt %s using account %s.",
            post_url,
            attempt_number,
            cookie_payload.account_id,
        )

    return fallback_post or Post(post_url=post_url, username=username, post_exists=False)


async def _fetch_post_with_cookie_candidate(
    post_url: str,
    username: str,
    cookie_payload: AccountCookies,
    attempt_number: int,
) -> Post:
    """
    Attempt to fetch post data using a specific cookie payload.
    Args:
        post_url: The URL of the Instagram post.
        username: The username of the post owner.
        cookie_payload: The AccountCookies payload to use for this attempt.
        attempt_number: The current attempt number for logging purposes.
    Returns:
        A Post object containing the post data, which may be missing comment metadata if the fetch was unsuccessful.
    """
    proxy = await get_random_proxy()
    page_content = await get_post_page(
        post_url,
        proxy=proxy,
        cookies=cookie_payload.cookies or None,
    )

    scripts: list = await get_page_scripts(page_content)
    logging.info(
        "Extracted %s script tags from %s on attempt %s with account %s",
        len(scripts),
        post_url,
        attempt_number,
        cookie_payload.account_id,
    )

    json_scripts: list[dict] = await filter_scripts_with_jsons(scripts)
    return await _build_post_from_json_scripts(post_url, username, json_scripts)


async def _build_post_from_json_scripts(
    post_url: str,
    username: str,
    json_scripts: list[dict],
) -> Post:
    """
    Build a Post object by extracting data from the provided JSON scripts.
    Args:
        post_url: The URL of the Instagram post.
        username: The username of the post owner.
        json_scripts: A list of JSON data extracted from the post page's script tags.
    Returns:
        A Post object containing the extracted data, which may be missing comment metadata if the required fields
    """
    comment_count: int = await get_comment_count(json_scripts)
    media_id: str | None = await get_media_id(json_scripts)
    hmac_claim: str | None = await get_hmac_claim(json_scripts)
    first_comments: list | None = await get_first_comments(json_scripts)
    next_comments: bool | None = await has_next_comments(json_scripts)

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
            has_next_comments=bool(next_comments),
            post_exists=False,
        )

    logging.info(
        "Successfully extracted data for %s: media_id=%s, hmac_claim=%s",
        post_url,
        media_id,
        hmac_claim,
    )

    return Post(
        post_url=post_url,
        username=username,
        comment_count=comment_count,
        media_id=media_id,
        hmac_claim=hmac_claim,
        first_comments=first_comments or [],
        has_next_comments=bool(next_comments),
        post_exists=True,
    )


def _post_has_required_data(post: Post) -> bool:
    """
    Check if the post has the required comment metadata to be processed.
    Args:
        post: The Post object to check.
    Returns:
        True if the post has the required media_id, hmac_claim, and comment metadata,
    """
    if not post.media_id or not post.hmac_claim:
        return False

    if (post.comment_count or 0) <= 0:
        return True

    if not post.first_comments:
        return False

    return first_comments_have_reply_metadata(post.first_comments)
