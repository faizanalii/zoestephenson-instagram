from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any

from curl_cffi import requests
from curl_cffi.requests.exceptions import RequestException
from scraper.src.comment_scraper.post_page import get_post_page

from src.comment_scraper.ig_query_client import run_graphql_query
from src.comment_scraper.utils import search_comment
from src.models import AccountCookies, CommentStats, PageRequirements, TaskState

from .queue_manager import RedisQueueManager
from .utils import (
    classify_response,
    extract_dtsg_token,
    extract_edges,
    extract_lsd_token,
    extract_post_id,
    extract_rate_limit_error,
    get_app_id,
    get_comment_and_bifilter_token,
    get_csrf_token,
    get_hmac_claim,
    get_media_id,
    get_scripts_from_profile_page,
    parse_page_info,
)

# Reuse existing probe utilities without modifying original files.
MODULE_DIR = Path(__file__).resolve().parent
DEBUGGING_DIR = MODULE_DIR.parent
RESTRICTION_DEBUGGER_DIR = DEBUGGING_DIR / "restriction_debugger"

if str(DEBUGGING_DIR) not in sys.path:
    sys.path.insert(0, str(DEBUGGING_DIR))
if str(RESTRICTION_DEBUGGER_DIR) not in sys.path:
    sys.path.insert(0, str(RESTRICTION_DEBUGGER_DIR))


def _load_module(module_name: str) -> Any:
    """Loads a module by name using runtime import to support non-package Debugging layout."""

    return importlib.import_module(module_name)


async def fetch_page_requirements(post_url: str, proxy: str) -> PageRequirements:
    """Fetches post page and extracts all fields required for GraphQL pagination requests."""

    page_html = await get_post_page(post_url=post_url, proxy=proxy)

    scripts = await get_scripts_from_profile_page(html=page_html)

    csrf_token = await get_csrf_token(scripts)
    app_id = await get_app_id(scripts)
    media_id = await get_media_id(scripts)
    claim_token: str | None = await get_hmac_claim(scripts=scripts)
    cursor = await get_comment_and_bifilter_token(scripts)

    lsd_token: str | None = await extract_lsd_token(page_html)
    dtsg_token: str | None = await extract_dtsg_token(page_html)

    if not csrf_token or not app_id or not media_id or not cursor:
        raise RuntimeError("Missing required page extraction fields for GraphQL pagination.")

    return PageRequirements(
        post_id=extract_post_id(post_url),
        csrf_token=csrf_token,
        app_id=app_id,
        media_id=media_id,
        cursor=cursor,
        lsd_token=lsd_token,
        dtsg_token=dtsg_token,
        claim_token=claim_token,
    )


async def _is_restriction_response(status_code: int, kind: str, payload: dict[str, Any]) -> bool:
    """
    Determines whether a response indicates restriction and should trigger queue reprocessing
    instead of immediate failure.
    Args:
        status_code: The HTTP status code of the response.
        kind: The classified content type of the response (e.g., "json", "html").
        payload: The parsed JSON payload if kind is "json", otherwise None.
    Returns:
        bool: True if the response indicates a restriction (e.g., rate limit, temporary block
    """

    if status_code != 200:
        return True
    if kind != "json":
        return True
    is_rate_limited: dict[str, Any] | None = await extract_rate_limit_error(payload=payload)
    if payload and is_rate_limited:
        return True
    return False


async def paginate_and_search(
    *,
    task: TaskState,
    account: AccountCookies,
    proxy: str,
    page_requirements: PageRequirements,
    queue_manager: RedisQueueManager,
) -> CommentStats | None:
    """
    Paginates Instagram comments and searches username after each API page
    until found or exhausted.
    Args:
        task: The TaskState object representing the current processing state.
        account: The AccountCookies object containing cookies for API calls.
        page_requirements: The PageRequirements object with fields extracted from the post page.
        queue_manager: The RedisQueueManager instance for managing task state and requeuing.
    Returns:
        CommentStats if a matching comment is found, or None if not found or on failure.
    """

    session = requests.Session(impersonate="chrome142")
    session.cookies.update(account.cookies)

    cursor = task.variables or page_requirements.cursor

    while True:
        try:
            response = await run_graphql_query(
                csrf_token=page_requirements.csrf_token,
                app_id=page_requirements.app_id,
                media_id=page_requirements.media_id,
                post_id=page_requirements.post_id,
                comment_cursor_bifilter_token=cursor,
                cookies=account.cookies,
                proxy=proxy,
                lsd_token=page_requirements.lsd_token,
                hmac_claim=page_requirements.claim_token,
                fb_dtsg=page_requirements.dtsg_token,
                include_requested_with=True,
                session=session,
                timeout=120.0,
            )
        except RequestException:
            queue_manager.requeue_task(task, variables=cursor)
            return None

        body = response.text
        kind = await classify_response(
            response.status_code,
            response.headers.get("content-type"),
            body,
        )

        payload = None
        # TODO: In the requeue put the last cursor, proxy, username, post_url
        if kind == "json":
            try:
                payload = response.json()
                if await _is_restriction_response(response.status_code, kind, payload):
                    queue_manager.requeue_task(task, variables=cursor)
                    return None
            except json.JSONDecodeError:
                payload = None

        if payload is None:
            queue_manager.requeue_task(task, variables=cursor)
            return None

        edges = await extract_edges(payload)

        found_comment = await search_comment(edges, task.username, post_url=task.post_url)

        if found_comment is not None:
            return found_comment

        next_cursor, has_next_page = await parse_page_info(payload)
        # TODO: Update the supabase from here and return, or create a different way of
        # exiting from here
        if not has_next_page or next_cursor is None:
            return None

        cursor = next_cursor
