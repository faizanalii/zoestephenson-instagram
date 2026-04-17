"""
Entry point for the comment scraper. This file is responsible for starting
the scraper and orchestrating the different components.
"""

import asyncio
import logging
import random
from typing import Any

from curl_cffi import requests

from src.models import (
    AccountCookies,
    CommentStats,
    DataRequirements,
    HeaderRequirements,
    Post,
    ScrapeResult,
    ScrapeStatus,
)
from src.redis_client import (
    get_next_account_with_cookies,
    push_post_to_queue,
    remove_url_from_processing_queue,
)
from src.settings import MAX_RATE_LIMIT_RETRIES, MAX_RETRIES
from src.supabase_client import push_error_post

from .ig_query_client import run_graphql_query
from .post_page import get_post_page
from .utils import (
    PostPageParser,
    classify_response,
    extract_rate_limit_error,
    get_comments,
    get_post_id,
    get_random_proxy,
    parse_page_info,
    search_comment,
)


def _should_dead_letter(post: Post) -> bool:
    """Return True when the post has exhausted its retry budget."""
    return post.retry_count >= MAX_RETRIES


async def _dead_letter(post: Post, reason: str) -> ScrapeResult:
    """Send post to the error table and mark it as a terminal failure."""
    logging.error(
        "Post %s reached max retries (%s). Dead-lettering. Reason: %s",
        post.post_url,
        MAX_RETRIES,
        reason,
    )
    await push_error_post(post_url=post.post_url, error_message=reason)
    await remove_url_from_processing_queue(post_url=post.post_url)
    return ScrapeResult(
        status=ScrapeStatus.ERROR,
        post_url=post.post_url,
        username=post.username,
        retry_count=post.retry_count,
        error=reason,
    )


async def _requeue(post: Post, source_queue: str, reason: str) -> ScrapeResult:
    """
    Increment retry counter, push back to source queue, remove from processing queue.
    Args:
        post: The Post object being processed
        source_queue: The Redis queue key to push the post back onto for retry
        reason: A string describing the reason for the retry, used for logging and error tracking
    Returns:
        A ScrapeResult object indicating that the post has been re-queued for retry.
    """

    incremented = post.model_copy(update={"retry_count": post.retry_count + 1})

    await remove_url_from_processing_queue(post_url=post.post_url)

    await push_post_to_queue(post_job=incremented, queue_key=source_queue)

    logging.warning(
        "Re-queued post=%s retry=%s/%s reason=%s",
        post.post_url,
        incremented.retry_count,
        MAX_RETRIES,
        reason,
    )
    return ScrapeResult(
        status=ScrapeStatus.RETRY,
        post_url=post.post_url,
        username=post.username,
        retry_count=incremented.retry_count,
        error=reason,
    )


# TODO: On Failure of post page, it doesn't remove it from the processing queue


async def find_comment(post: Post, source_queue: str) -> ScrapeResult:
    """
    Entry point that returns matching comment model or None for a post URL and username.
    Args:
        post: The Post object containing the URL and username to search comments for
        source_queue: Optional string indicating the source queue for logging and potential
    Returns:
        A ScrapeResult object if a matching comment is found, or None if not found or an
        error occurs.
    """

    # Check if the username exists in the first comments for the post

    comment: CommentStats | None = await search_comment(
        comments=post.first_comments, username=post.username, post_url=post.post_url
    )

    if comment:
        return ScrapeResult(
            status=ScrapeStatus.FOUND,
            post_url=post.post_url,
            username=post.username,
            comment=comment,
        )

    # Get an account used for scraping
    account: AccountCookies | None = await get_next_account_with_cookies()

    # If the account cookies is not available, put the account again into the queue of task
    # and return None to trigger retry with exponential backoff
    if account is None:
        logging.warning(
            "No account cookies available for scraping post=%s username=%s.",
            post.post_url,
            post.username,
        )
        # If the retries are exhausted, dead-letter the post instead of re-queuing
        if _should_dead_letter(post):
            return await _dead_letter(post, reason="no_account_cookies")
        return await _requeue(post, source_queue, reason="no_account_cookies")

    logging.info(f"Using account {account.account_id} for scraping {post.post_url}")

    # Pull a random proxy for the request, use that proxy throughout the scraping
    proxy_url: str = await get_random_proxy()

    # If not found in the first comments, return None to trigger pagination fallback
    # Get the latest post page data for the post URL, which may include updated first comments
    # and pagination info
    try:
        post_page_data: str = await get_post_page(
            post_url=post.post_url, proxy=proxy_url, cookies=account.cookies
        )
    except Exception as exc:
        logging.error(
            "Failed to fetch post page for post=%s account=%s: %s",
            post.post_url,
            account.account_id,
            exc,
        )
        if _should_dead_letter(post):
            return await _dead_letter(post, reason=f"post_page_fetch_failed: {exc}")
        return await _requeue(post, source_queue, reason="post_page_fetch_failed")

    # Create the session
    session = requests.Session(impersonate="chrome146", proxy=proxy_url)
    # Add cookies to the session
    session.cookies.update(account.cookies)

    post_id: str | None = await get_post_id(post_url=post.post_url)

    # Page Parsing
    page_parser = PostPageParser()

    # Extract the scripts from the HTML Page

    json_scripts: list[dict[str, Any]] = await page_parser.get_scripts_from_profile_page(
        html=post_page_data
    )

    # Headers data for the API call
    header_data: HeaderRequirements = await page_parser.get_header_data(
        json_scripts=json_scripts, html=post_page_data
    )

    if not header_data.lsd_token or not header_data.dtsg_token:
        raise Exception("Missing required header tokens for pagination. Cannot proceed.")

    # Data Payload for the API
    payload_data: DataRequirements = await page_parser.get_data_requirements(
        json_scripts=json_scripts, lsd_token=header_data.lsd_token, fb_dtsg=header_data.dtsg_token
    )

    # Extract all necessary fields for pagination from the page scripts and HTML
    rate_limit_hits = 0
    consecutive_empty_pages = 0
    _MAX_CONSECUTIVE_EMPTY = 2  # one genuine retry before giving up
    while True:
        try:
            api_response = await run_graphql_query(
                csrf_token=header_data.csrf_token,
                app_id=header_data.app_id,
                media_id=payload_data.media_id,
                post_id=post_id if post_id else payload_data.media_id,
                comment_cursor_bifilter_token=payload_data.cursor,
                cookies=account.cookies,
                session=session,
                proxy=proxy_url,
                lsd_token=payload_data.lsd_token,
                hmac_claim=header_data.hmac_claim,
                fb_dtsg=payload_data.fb_dtsg,
                include_requested_with=True,
            )
        except Exception as exc:
            logging.error(
                "GraphQL query failed for post=%s account=%s: %s",
                post.post_url,
                account.account_id,
                exc,
            )
            if _should_dead_letter(post):
                return await _dead_letter(post, reason=f"graphql_query_failed: {exc}")
            return await _requeue(post, source_queue, reason="graphql_query_failed")

        # Classify the page response to determine if it's a valid JSON response,
        # an HTML page (potentially a block or challenge),
        body_text = api_response.text
        content_type = api_response.headers.get("content-type")

        kind: str = await classify_response(api_response.status_code, content_type, body_text)

        if kind == "json":
            # If it's a JSON response, parse the body and search for the comment
            json_body = api_response.json()
            next_cursor, has_next_page = await parse_page_info(json_body=json_body)
            rate_limit_error = await extract_rate_limit_error(json_body=json_body)

            if rate_limit_error:
                rate_limit_hits += 1
                logging.warning(
                    "Rate limit hit %s/%s for post=%s account=%s. Details: %s",
                    rate_limit_hits,
                    MAX_RATE_LIMIT_RETRIES,
                    post.post_url,
                    account.account_id,
                    rate_limit_error,
                )
                if rate_limit_hits >= MAX_RATE_LIMIT_RETRIES:
                    # Cursor state is preserved in post; the re-queued job will
                    # resume pagination from the same point on the next attempt.
                    if _should_dead_letter(post):
                        return await _dead_letter(post, reason="rate_limit_exhausted")
                    return await _requeue(post, source_queue, reason="rate_limit_exhausted")
                # Back off, then retry the same page from where we left off.
                await asyncio.sleep(random.uniform(30, 60))
                continue

            else:
                comments = await get_comments(json_body=json_body)

                if not comments:
                    consecutive_empty_pages += 1
                    logging.info(
                        "No comments in response for %s (consecutive empty: %s/%s).",
                        post.post_url,
                        consecutive_empty_pages,
                        _MAX_CONSECUTIVE_EMPTY,
                    )
                    if consecutive_empty_pages >= _MAX_CONSECUTIVE_EMPTY:
                        logging.info(
                            "Consecutive empty page limit reached for %s. Ending pagination.",
                            post.post_url,
                        )
                        return ScrapeResult(
                            status=ScrapeStatus.NOT_FOUND,
                            post_url=post.post_url,
                            username=post.username,
                            comment=None,
                        )
                    # Brief pause then retry the same cursor once.
                    await asyncio.sleep(random.uniform(2, 5))
                    continue

                comment = await search_comment(
                    comments=comments, username=post.username, post_url=post.post_url
                )
                consecutive_empty_pages = 0  # got real comments — reset the guard

                if comment:
                    return ScrapeResult(
                        status=ScrapeStatus.FOUND,
                        post_url=post.post_url,
                        username=post.username,
                        comment=comment,
                    )

                if not has_next_page:
                    logging.info(
                        f"No more pages to paginate for {post.post_url}. Ending pagination."
                    )
                    # Exit the loop and remove it from the processing queue
                    await remove_url_from_processing_queue(post_url=post.post_url)

                    return ScrapeResult(
                        status=ScrapeStatus.NOT_FOUND,
                        post_url=post.post_url,
                        username=post.username,
                        comment=None,
                    )

                # Update the payload cursor for the next pagination request
                if next_cursor:
                    payload_data.cursor = next_cursor

                    await asyncio.sleep(
                        random.uniform(1, 3)
                    )  # Sleep for a short duration before the next request
                    # to avoid hitting rate limits
                    continue

        elif kind == "html":
            logging.warning(
                "Received HTML response (block/challenge) for post=%s account=%s.",
                post.post_url,
                account.account_id,
            )
            if _should_dead_letter(post):
                return await _dead_letter(post, reason="html_block_challenge")
            return await _requeue(post, source_queue, reason="html_block_challenge")

        else:
            # Unknown response kind — don't spin; treat as a transient error.
            logging.error(
                "Unknown response kind=%r for post=%s account=%s. Re-queuing.",
                kind,
                post.post_url,
                account.account_id,
            )
            if _should_dead_letter(post):
                return await _dead_letter(post, reason=f"unknown_response_kind:{kind}")
            return await _requeue(post, source_queue, reason=f"unknown_response_kind:{kind}")
