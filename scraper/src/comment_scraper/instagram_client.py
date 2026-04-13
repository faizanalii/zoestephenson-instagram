from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any, Callable

from bs4 import BeautifulSoup
from curl_cffi import requests
from curl_cffi.requests.exceptions import RequestException

from .models import AccountCookies, PageRequirements, TaskState
from .queue_manager import RedisQueueManager
from .utils import extract_edges, extract_post_id, parse_page_info

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


async def fetch_page_requirements(post_url: str) -> PageRequirements:
    """Fetches post page and extracts all fields required for GraphQL pagination requests."""

    post_page_module = _load_module("post_page")
    legacy_utils = _load_module("utils")
    common_module = _load_module("common")

    page_html = await post_page_module.get_post_page(post_url=post_url, proxy="")
    soup = BeautifulSoup(page_html, "html.parser")
    scripts = await legacy_utils.get_scripts_from_profile_page(soup)

    csrf_token = await legacy_utils.get_csrf_token(scripts)
    app_id = await legacy_utils.get_app_id(scripts)
    media_id = await legacy_utils.get_media_id(scripts)
    cursor = await legacy_utils.get_comment_and_bifilter_token(scripts)

    if not csrf_token or not app_id or not media_id or not cursor:
        raise RuntimeError(
            "Missing required page extraction fields for GraphQL pagination."
        )

    return PageRequirements(
        post_id=extract_post_id(post_url),
        csrf_token=csrf_token,
        app_id=app_id,
        media_id=media_id,
        cursor=cursor,
        lsd_token=common_module.extract_lsd_token(page_html),
        dtsg_token=common_module.extract_dtsg_token(page_html),
        claim_token=common_module.extract_claim_token(page_html),
    )


def _is_restriction_response(
    status_code: int, kind: str, payload: dict[str, Any] | None
) -> bool:
    """Determines whether a response indicates restriction and should trigger queue reprocessing."""

    common_module = _load_module("common")

    if status_code != 200:
        return True
    if kind != "json":
        return True
    if payload and common_module.extract_rate_limit_error(payload):
        return True
    return False


async def paginate_and_search(
    *,
    task: TaskState,
    account: AccountCookies,
    page_requirements: PageRequirements,
    queue_manager: RedisQueueManager,
    search_comment: Callable[[list[dict[str, Any]], str], Any],
) -> Any:
    """Paginates Instagram comments and searches username after each API page until found or exhausted."""

    common_module = _load_module("common")
    ig_query_client_module = _load_module("ig_query_client")

    session = requests.Session(impersonate="chrome142")
    session.cookies.update(account.cookies)

    cursor = task.variables or page_requirements.cursor

    while True:
        try:
            response = ig_query_client_module.run_graphql_query(
                csrf_token=page_requirements.csrf_token,
                app_id=page_requirements.app_id,
                media_id=page_requirements.media_id,
                post_id=page_requirements.post_id,
                comment_cursor_bifilter_token=cursor,
                cookies=account.cookies,
                proxy=None,
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
        kind = common_module.classify_response(
            response.status_code,
            response.headers.get("content-type"),
            body,
        )

        payload = None
        if kind == "json":
            try:
                payload = response.json()
            except json.JSONDecodeError:
                payload = None

        if _is_restriction_response(response.status_code, kind, payload):
            queue_manager.requeue_task(task, variables=cursor)
            return None

        if payload is None:
            queue_manager.requeue_task(task, variables=cursor)
            return None

        edges = extract_edges(payload)
        found_comment = search_comment(edges, task.username)
        if found_comment is not None:
            return found_comment

        next_cursor, has_next_page = parse_page_info(payload)
        if not has_next_page or next_cursor is None:
            return None

        cursor = next_cursor
