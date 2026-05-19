"""
Child comments (replies) API client.

Queries Instagram's /api/graphql endpoint for child comments of a
specific parent comment.  No cookies or authentication are needed —
the endpoint works with page-extracted tokens and TLS impersonation.

The reply count is derived from the length of the ``edges`` array in
the response, as described in the Debugging/comment_replies research.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from curl_cffi import requests
from curl_cffi.requests.models import Response
from tenacity import retry, stop_after_attempt, wait_exponential

CHILD_COMMENTS_DOC_ID = "34884685271179117"
CHILD_COMMENTS_FRIENDLY_NAME = "PolarisPostChildCommentsQuery"


async def build_child_comments_headers(
    csrf_token: str,
    app_id: str,
    lsd_token: str | None = None,
) -> dict[str, str]:
    """Build headers for the child comments GraphQL request."""
    headers: dict[str, str] = {
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9,ur;q=0.8",
        "content-type": "application/x-www-form-urlencoded",
        "origin": "https://www.instagram.com",
        "sec-ch-ua": '"Google Chrome";v="137", "Chromium";v="137", "Not/A)Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
        "x-csrftoken": csrf_token,
        "x-fb-friendly-name": CHILD_COMMENTS_FRIENDLY_NAME,
        "x-ig-app-id": app_id,
    }
    if lsd_token:
        headers["x-fb-lsd"] = lsd_token
    return headers


async def build_child_comments_data(
    media_id: str,
    parent_comment_id: str,
    lsd_token: str | None = None,
) -> dict[str, str]:
    """Build the POST body for the child comments GraphQL request."""
    variables = {
        "after": None,
        "before": None,
        "media_id": media_id,
        "parent_comment_id": parent_comment_id,
        "__relay_internal__pv__PolarisIsLoggedInrelayprovider": True,
    }

    data: dict[str, str] = {
        "av": "0",
        "__d": "www",
        "__user": "0",
        "__a": "1",
        "__req": "1a",
        "__comet_req": "7",
        "fb_api_caller_class": "RelayModern",
        "fb_api_req_friendly_name": CHILD_COMMENTS_FRIENDLY_NAME,
        "server_timestamps": "true",
        "variables": json.dumps(variables),
        "doc_id": CHILD_COMMENTS_DOC_ID,
    }
    if lsd_token:
        data["lsd"] = lsd_token
    return data


async def _find_connection_with_edges(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Recursively find any dict containing 'edges' in the data tree."""
    data_block = payload.get("data", {})
    if not isinstance(data_block, dict):
        return []

    stack: list[dict[str, Any]] = [data_block]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            if "edges" in current and isinstance(current["edges"], list):
                return current["edges"]
            for value in current.values():
                if isinstance(value, dict):
                    stack.append(value)
    return []


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def get_child_comment_count(
    media_id: str,
    parent_comment_id: str,
    csrf_token: str,
    app_id: str,
    lsd_token: str | None = None,
    proxy: str | None = None,
    timeout: float = 30.0,
) -> int:
    """
    Get the number of child comments (replies) for a parent comment.

    This makes a single GraphQL request to Instagram's /api/graphql
    endpoint — no cookies or authentication required.

    Args:
        media_id: The Instagram media ID for the post.
        parent_comment_id: The comment ``pk`` whose replies to count.
        csrf_token: CSRF token extracted from the post page.
        app_id: Instagram app ID extracted from the post page.
        lsd_token: Optional LSD token extracted from the page HTML.
        proxy: Optional proxy URL for this request.
        timeout: Request timeout in seconds.

    Returns:
        The number of child comments (replies), or 0 on any error.
    """
    headers = await build_child_comments_headers(
        csrf_token=csrf_token,
        app_id=app_id,
        lsd_token=lsd_token,
    )
    data = await build_child_comments_data(
        media_id=media_id,
        parent_comment_id=parent_comment_id,
        lsd_token=lsd_token,
    )

    try:
        response: Response = requests.post(
            "https://www.instagram.com/api/graphql",
            impersonate="chrome142",
            headers=headers,
            data=data,
            proxy=proxy or None,
            timeout=timeout,
        )

        if response.status_code != 200:
            logging.warning(
                "Child comments API returned status %s for comment=%s",
                response.status_code,
                parent_comment_id,
            )
            return 0

        payload: dict[str, Any] = response.json()

        edges = await _find_connection_with_edges(payload)
        return len(edges)

    except Exception:
        logging.exception(
            "Failed to fetch child comment count for comment=%s", parent_comment_id
        )
        return 0
