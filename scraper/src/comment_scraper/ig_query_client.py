"""
GraphQL query client for Instagram comment pagination.

No cookies or authentication required — uses page-extracted tokens
and TLS fingerprint impersonation to call Instagram's internal
GraphQL API, matching the approach proven in the Apify scraper.
"""

from __future__ import annotations

import json
from typing import Any

from curl_cffi import requests
from curl_cffi.requests.models import Response
from tenacity import retry, stop_after_attempt, wait_exponential

PAGINATION_FRIENDLY_NAME = "PolarisPostCommentsPaginationQuery"
_FALLBACK_PAGINATION_DOC_ID = "26864966453197043"


async def build_headers(
    csrf_token: str,
    app_id: str,
    post_id: str,
    lsd_token: str | None = None,
    hmac_claim: str | None = None,
) -> dict[str, str]:
    """
    Build request headers for the GraphQL comments query.

    Always uses /p/{post_id} as the referer (works for both posts and reels).
    """
    headers: dict[str, str] = {
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9,ur;q=0.8",
        "cache-control": "no-cache",
        "content-type": "application/x-www-form-urlencoded",
        "origin": "https://www.instagram.com",
        "pragma": "no-cache",
        "priority": "u=1, i",
        "referer": f"https://www.instagram.com/p/{post_id}/",
        "sec-ch-prefers-color-scheme": "dark",
        "sec-ch-ua": '"Google Chrome";v="137", "Chromium";v="137", "Not/A)Brand";v="24"',
        "sec-ch-ua-full-version-list": '"Google Chrome";v="137.0.7151.56", "Chromium";v="137.0.7151.56", "Not/A)Brand";v="24.0.0.0"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-model": '""',
        "sec-ch-ua-platform": '"Windows"',
        "sec-ch-ua-platform-version": '"19.0.0"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
        "x-asbd-id": "359341",
        "x-csrftoken": csrf_token,
        "x-fb-friendly-name": PAGINATION_FRIENDLY_NAME,
        "x-ig-app-id": app_id,
        "x-requested-with": "XMLHttpRequest",
        "x-root-field-name": "xdt_api__v1__media__media_id__comments__connection",
    }
    if lsd_token:
        headers["x-fb-lsd"] = lsd_token
    if hmac_claim:
        headers["x-ig-www-claim"] = hmac_claim
    return headers


async def build_query_data(
    media_id: str,
    cursor: dict[str, Any] | str | None,
    fb_dtsg: str | None = None,
    lsd_token: str | None = None,
    doc_id: str | None = None,
) -> dict[str, str]:
    """
    Build the POST body for the GraphQL comments query.

    Uses the same doc_id and route for both posts and reels
    (Apify scraper confirms this works for both media types).
    """
    if isinstance(cursor, str):
        after_cursor = cursor
    else:
        after_cursor = json.dumps(cursor or {})

    variables = {
        "after": after_cursor,
        "before": None,
        "first": 50,
        "last": None,
        "media_id": media_id,
        "sort_order": "popular",
        "__relay_internal__pv__PolarisIsLoggedInrelayprovider": True,
    }

    data: dict[str, str] = {
        "__crn": "comet.igweb.PolarisDesktopPostRoute",
        "fb_api_caller_class": "RelayModern",
        "fb_api_req_friendly_name": PAGINATION_FRIENDLY_NAME,
        "variables": json.dumps(variables),
        "server_timestamps": "true",
        "doc_id": doc_id or _FALLBACK_PAGINATION_DOC_ID,
    }
    if fb_dtsg:
        data["fb_dtsg"] = fb_dtsg
    if lsd_token:
        data["lsd"] = lsd_token
    return data


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=2, max=10))
async def run_graphql_query(
    csrf_token: str,
    app_id: str,
    media_id: str,
    post_id: str,
    cursor: dict[str, Any] | str | None,
    proxy: str | None = None,
    lsd_token: str | None = None,
    hmac_claim: str | None = None,
    fb_dtsg: str | None = None,
    doc_id: str | None = None,
    session: requests.Session | None = None,
    timeout: float | None = None,
) -> Response:
    """
    Execute a GraphQL query to fetch a page of comments.

    No cookies are sent — the query works against Instagram's public
    GraphQL endpoint using tokens extracted from the post page.

    Args:
        csrf_token: CSRF token from the post page.
        app_id: Instagram app ID from the post page.
        media_id: Media ID for the post/reel.
        post_id: Shortcode / post ID for the referer header.
        cursor: Pagination cursor (dict, JSON string, or plain string).
        proxy: Optional proxy URL for this request (overrides session-level proxy).
        lsd_token: Optional LSD token from the page HTML.
        hmac_claim: Optional HMAC claim from the page HTML.
        fb_dtsg: Optional DTSG token from the page HTML.
        session: Optional curl_cffi Session for connection reuse.
        timeout: Request timeout in seconds.
    Returns:
        The HTTP response from the GraphQL endpoint.
    """
    headers = await build_headers(
        csrf_token=csrf_token,
        app_id=app_id,
        post_id=post_id,
        lsd_token=lsd_token,
        hmac_claim=hmac_claim,
    )
    data = await build_query_data(
        media_id=media_id,
        cursor=cursor,
        fb_dtsg=fb_dtsg,
        lsd_token=lsd_token,
        doc_id=doc_id,
    )

    call = session.post if session else requests.post

    kwargs: dict[str, Any] = {
        "headers": headers,
        "data": data,
        "timeout": timeout,
    }
    if proxy:
        kwargs["proxy"] = proxy
    if not session:
        kwargs["impersonate"] = "chrome142"

    response = call("https://www.instagram.com/graphql/query", **kwargs)

    if response.status_code != 200:
        raise Exception(
            f"GraphQL query failed with status code {response.status_code}"
            f" and response: {response.text[:200]}"
        )

    return response
