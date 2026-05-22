"""
Entry point for the comment scraper.

Orchestrates the cookie-free comment search pipeline:
  1. Check cached first_comments from the database.
  2. Fetch the post page (no account cookies).
  3. Extract GraphQL tokens from embedded JSON + HTML.
  4. Paginate through comments using Instagram's public GraphQL API.
  5. When the target comment is found, verify the reply count via
     the child-comments API (also cookie-free).
  6. Rotate proxies per page to avoid IP-based rate limiting.

Cookie-free operation means we never depend on account-manager
capacity and can scale independently.
"""

import asyncio
import logging
import random
from typing import Any

from src.models import (
    CommentStats,
    DataRequirements,
    HeaderRequirements,
    Post,
    ScrapeResult,
    ScrapeStatus,
)
from src.redis_client import (
    push_post_to_queue,
    remove_url_from_processing_queue,
)
from src.settings import MAX_PAGINATION_DEPTH, MAX_RATE_LIMIT_RETRIES, MAX_RETRIES
from src.supabase_client import push_error_post

from .child_comments import CHILD_COMMENTS_FRIENDLY_NAME, get_child_comment_count
from .ig_query_client import PAGINATION_FRIENDLY_NAME, run_graphql_query
from .post_page import _is_reel_url, get_post_page
from .utils import (
    PostPageParser,
    classify_response,
    extract_general_errors,
    extract_rate_limit_error,
    get_comments,
    get_post_id,
    get_random_proxy,
    parse_page_info,
    search_comment,
)

_MAX_CONSECUTIVE_EMPTY = 2


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
    """Increment retry counter, push back to source queue."""
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


async def _verify_reply_count(
    comment: CommentStats,
    header_data: HeaderRequirements,
    media_id: str,
    child_doc_id: str | None = None,
) -> CommentStats:
    """
    Verify / correct the reply_count via the child-comments API.

    When ``child_comment_count`` is missing (null) or unreliable in the
    main comment response, this makes a single cookie-free API call to
    count the actual edges returned for the parent comment.

    Falls back to the original ``reply_count`` on any error.
    """
    if not comment.comment_id:
        return comment

    try:
        verified_count = await get_child_comment_count(
            media_id=media_id,
            parent_comment_id=comment.comment_id,
            csrf_token=header_data.csrf_token,
            app_id=header_data.app_id,
            lsd_token=header_data.lsd_token,
            proxy=await get_random_proxy(),
            doc_id=child_doc_id,
        )
        logging.info(
            "Child-comment API returned %s replies for comment=%s (original reply_count=%s)",
            verified_count,
            comment.comment_id,
            comment.reply_count,
        )
        return comment.model_copy(update={"reply_count": verified_count})
    except Exception:
        logging.exception(
            "Child-comment API failed for comment=%s, keeping original reply_count",
            comment.comment_id,
        )
        return comment


async def find_comment(post: Post, source_queue: str) -> ScrapeResult:
    """
    Search a post for a comment by the target username.

    Returns a ``ScrapeResult`` with status FOUND, NOT_FOUND, RETRY,
    or ERROR.  All HTTP requests are cookie-free — tokens extracted
    from the public page drive the GraphQL pagination, and IPs rotate
    per page to avoid rate limits.
    """

    # ── Phase 1: check cached first_comments ────────────────────────────
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

    # ── Phase 2: fetch the post page (no cookies) ───────────────────────
    proxy_url: str = await get_random_proxy()

    try:
        post_page_data: str = await get_post_page(post_url=post.post_url, proxy=proxy_url)
    except Exception as exc:
        logging.error("Failed to fetch post page for %s: %s", post.post_url, exc)
        if _should_dead_letter(post):
            return await _dead_letter(post, reason=f"post_page_fetch_failed: {exc}")
        return await _requeue(post, source_queue, reason="post_page_fetch_failed")

    # ── Phase 3: extract tokens from the page ───────────────────────────
    post_id: str | None = await get_post_id(post_url=post.post_url)
    page_parser = PostPageParser()

    json_scripts: list[dict[str, Any]] = await page_parser.get_scripts_from_profile_page(
        html=post_page_data
    )

    header_data: HeaderRequirements = await page_parser.get_header_data(
        json_scripts=json_scripts, html=post_page_data
    )

    if not header_data.lsd_token or not header_data.dtsg_token:
        if _should_dead_letter(post):
            return await _dead_letter(
                post,
                reason=f"post_page_fetch_failed: "
                f"{'lsd_token_missing' if not header_data.lsd_token else 'dtsg_token_missing'}",
            )
        return await _requeue(post, source_queue, reason="post_page_fetch_failed")

    payload_data: DataRequirements = await page_parser.get_data_requirements(
        json_scripts=json_scripts,
        lsd_token=header_data.lsd_token,
        fb_dtsg=header_data.dtsg_token,
    )

    is_reel = _is_reel_url(post.post_url)
    logging.info(
        "Post %s identified as %s — starting cookie-free pagination",
        post.post_url,
        "reel" if is_reel else "non-reel",
    )

    # ── Extract GraphQL doc_ids from the page (prevents breakage on rotation) ──
    pagination_doc_id = await page_parser.get_doc_id(
        friendly_name=PAGINATION_FRIENDLY_NAME,
        json_scripts=json_scripts,
        html=post_page_data,
    )
    child_doc_id = await page_parser.get_doc_id(
        friendly_name=CHILD_COMMENTS_FRIENDLY_NAME,
        json_scripts=json_scripts,
        html=post_page_data,
    )

    # ── Phase 4: pagination loop (per-page proxy rotation) ──────────────
    rate_limit_hits = 0
    consecutive_empty_pages = 0
    page_count = 0

    while page_count < MAX_PAGINATION_DEPTH:
        page_proxy = await get_random_proxy()

        try:
            api_response = await run_graphql_query(
                csrf_token=header_data.csrf_token,
                app_id=header_data.app_id,
                media_id=payload_data.media_id,
                post_id=post_id if post_id else payload_data.media_id,
                cursor=payload_data.cursor,
                proxy=page_proxy,
                lsd_token=payload_data.lsd_token,
                hmac_claim=header_data.hmac_claim,
                fb_dtsg=payload_data.fb_dtsg,
                doc_id=pagination_doc_id,
            )
        except Exception as exc:
            logging.error(
                "GraphQL query failed for post=%s page=%s: %s",
                post.post_url,
                page_count,
                exc,
            )
            if _should_dead_letter(post):
                return await _dead_letter(post, reason=f"graphql_query_failed: {exc}")
            return await _requeue(post, source_queue, reason="graphql_query_failed")

        page_count += 1

        body_text = api_response.text
        content_type = api_response.headers.get("content-type")
        kind: str = await classify_response(api_response.status_code, content_type, body_text)

        if kind == "json":
            json_body = api_response.json()
            next_cursor, has_next_page = await parse_page_info(json_body=json_body)
            rate_limit_error = await extract_rate_limit_error(json_body=json_body)
            general_errors = await extract_general_errors(json_body=json_body)

            if rate_limit_error:
                rate_limit_hits += 1
                logging.warning(
                    "Rate limit hit %s/%s for post=%s proxy=%s. Details: %s",
                    rate_limit_hits,
                    MAX_RATE_LIMIT_RETRIES,
                    post.post_url,
                    page_proxy,
                    rate_limit_error,
                )
                if rate_limit_hits >= MAX_RATE_LIMIT_RETRIES:
                    if _should_dead_letter(post):
                        return await _dead_letter(post, reason="rate_limit_exhausted")
                    return await _requeue(post, source_queue, reason="rate_limit_exhausted")
                await asyncio.sleep(random.uniform(30, 60))
                continue

            if general_errors:
                error_msgs = "; ".join(
                    str(e.get("message", ""))[:120] for e in general_errors
                )
                logging.warning(
                    "GraphQL errors for post=%s page=%s: %s",
                    post.post_url,
                    page_count,
                    error_msgs,
                )
                if _should_dead_letter(post):
                    return await _dead_letter(post, reason=f"graphql_errors: {error_msgs}")
                return await _requeue(post, source_queue, reason=f"graphql_errors: {error_msgs}")

            comments = await get_comments(json_body=json_body)

            if not comments:
                consecutive_empty_pages += 1
                if page_count <= 1:
                    logging.warning(
                        "No comments in response for %s (page %s). Response preview: %s",
                        post.post_url,
                        page_count,
                        body_text[:500],
                    )
                else:
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
                await asyncio.sleep(random.uniform(2, 5))
                continue

            comment = await search_comment(
                comments=comments, username=post.username, post_url=post.post_url
            )
            consecutive_empty_pages = 0

            if comment:
                comment = await _verify_reply_count(
                    comment=comment,
                    header_data=header_data,
                    media_id=payload_data.media_id,
                    child_doc_id=child_doc_id,
                )
                return ScrapeResult(
                    status=ScrapeStatus.FOUND,
                    post_url=post.post_url,
                    username=post.username,
                    comment=comment,
                )

            if not has_next_page:
                logging.info("No more pages to paginate for %s.", post.post_url)
                await remove_url_from_processing_queue(post_url=post.post_url)
                return ScrapeResult(
                    status=ScrapeStatus.NOT_FOUND,
                    post_url=post.post_url,
                    username=post.username,
                    comment=None,
                )

            if next_cursor:
                payload_data.cursor = next_cursor
                await asyncio.sleep(random.uniform(1, 3))
                continue

        elif kind == "html":
            logging.warning(
                "Received HTML response (block/challenge) for post=%s proxy=%s.",
                post.post_url,
                page_proxy,
            )
            if _should_dead_letter(post):
                return await _dead_letter(post, reason="html_block_challenge")
            return await _requeue(post, source_queue, reason="html_block_challenge")

        else:
            logging.error(
                "Unknown response kind=%r for post=%s proxy=%s. Re-queuing.",
                kind,
                post.post_url,
                page_proxy,
            )
            if _should_dead_letter(post):
                return await _dead_letter(post, reason=f"unknown_response_kind:{kind}")
            return await _requeue(post, source_queue, reason=f"unknown_response_kind:{kind}")

    logging.warning(
        "Max pagination depth (%s) reached for %s.", MAX_PAGINATION_DEPTH, post.post_url
    )
    return ScrapeResult(
        status=ScrapeStatus.NOT_FOUND,
        post_url=post.post_url,
        username=post.username,
        comment=None,
    )
