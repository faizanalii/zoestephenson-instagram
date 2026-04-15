from __future__ import annotations

import json
from typing import Any

from curl_cffi import requests
from curl_cffi.requests.models import Response
from tenacity import retry, stop_after_attempt, wait_exponential


async def build_headers(csrf_token: str, app_id: str, post_id: str) -> dict[str, str]:
    """
    Builds the headers for the GraphQL query request.
    Args:
        csrf_token: The CSRF token extracted from the post page.
        app_id: The Instagram app ID extracted from the post page.
        post_id: The post ID extracted from the post page.
    Returns:
        A dictionary of headers for the GraphQL query request.
    """
    return {
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
        "x-fb-friendly-name": "PolarisPostCommentsPaginationQuery",
        "x-fb-lsd": "9TXxZWXSdt5xjxL4UOPc92",
        "x-ig-app-id": app_id,
        "x-root-field-name": "xdt_api__v1__media__media_id__comments__connection",
    }


async def build_headers_dynamic(
    csrf_token: str,
    app_id: str,
    post_id: str,
    lsd_token: str | None = None,
    hmac_claim: str | None = None,
    include_requested_with: bool = False,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, str]:
    """
    Build the headers dynamically
    Args:
        csrf_token: str
        app_id: str
        post_id: str
        lsd_token: str
        hmac_claim: str
        include_requested_with: bool
        extra_headers: dict[str, str]
    Returns:
        dict[str, str]: The headers to be used in the request
    """
    headers = await build_headers(csrf_token=csrf_token, app_id=app_id, post_id=post_id)

    if lsd_token:
        headers["x-fb-lsd"] = lsd_token
    if hmac_claim:
        headers["x-ig-www-claim"] = hmac_claim
    if include_requested_with:
        headers["x-requested-with"] = "XMLHttpRequest"
    if extra_headers:
        headers.update(extra_headers)

    return headers


async def build_query_data(media_id: str, cursor: dict[str, Any]) -> dict[str, str]:
    """
    Build the data payload for the GraphQL query request.
    Args:
        media_id: The media ID extracted from the post page.
        cursor: The comment cursor extracted from the post page.
    Returns:
        A dictionary of data payload for the GraphQL query request.
    """
    variables = {
        "after": json.dumps(cursor),
        "before": None,
        "first": 10,
        "last": None,
        "media_id": media_id,
        "sort_order": "popular",
        "__relay_internal__pv__PolarisIsLoggedInrelayprovider": True,
    }
    return {
        "__crn": "comet.igweb.PolarisDesktopPostRoute",
        "fb_api_caller_class": "RelayModern",
        "fb_api_req_friendly_name": "PolarisPostCommentsPaginationQuery",
        "variables": json.dumps(variables),
        "server_timestamps": "true",
        "doc_id": "26224338453892885",
    }


async def build_query_data_dynamic(
    media_id: str,
    cursor: dict[str, Any],
    fb_dtsg: str | None = None,
    lsd_token: str | None = None,
    extra_data: dict[str, str] | None = None,
) -> dict[str, str]:
    """
    Build the data payload for the GraphQL query request dynamically
    Args:
        media_id: The media ID extracted from the post page.
        cursor: The comment cursor extracted from the post page.
        fb_dtsg: The fb_dtsg token extracted from the post page.
        lsd_token: The LSD token extracted from the post page.
        extra_data: Any extra data to be included in the payload
    Returns:
        A dictionary of data payload for the GraphQL query request.
    """
    data = await build_query_data(media_id=media_id, cursor=cursor)
    if fb_dtsg:
        data["fb_dtsg"] = fb_dtsg
    if lsd_token:
        data["lsd"] = lsd_token
    if extra_data:
        data.update(extra_data)
    return data


@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=2, max=10))
async def run_graphql_query(
    csrf_token: str,
    app_id: str,
    media_id: str,
    post_id: str,
    comment_cursor_bifilter_token: dict[str, Any],
    cookies: dict[str, str] | None = None,
    proxy: str | None = None,
    lsd_token: str | None = None,
    hmac_claim: str | None = None,
    fb_dtsg: str | None = None,
    include_requested_with: bool = False,
    extra_headers: dict[str, str] | None = None,
    extra_data: dict[str, str] | None = None,
    session: requests.Session | None = None,
    timeout: float | None = None,
) -> Response:
    """
    Run the GraphQL query to fetch comments.
    Args:
        csrf_token: The CSRF token extracted from the post page.
        app_id: The Instagram app ID extracted from the post page.
        media_id: The media ID extracted from the post page.
        post_id: The post ID extracted from the post page.
        comment_cursor_bifilter_token: The comment cursor bifilter
        token extracted from the post page.
        cookies: The cookies to be used in the request.
        proxy: The proxy to be used in the request.
        lsd_token: The LSD token extracted from the post page.
        hmac_claim: The HMAC claim extracted from the post page.
        fb_dtsg: The fb_dtsg token extracted from the post page.
        include_requested_with: Whether to include the X-Requested-With header.
        extra_headers: Any extra headers to be included in the request.
        extra_data: Any extra data to be included in the payload.
        session: The requests session to be used for the request.
        timeout: The timeout for the request.
    Returns:
        The response from the GraphQL query request.
    """
    headers = await build_headers_dynamic(
        csrf_token=csrf_token,
        app_id=app_id,
        post_id=post_id,
        lsd_token=lsd_token,
        hmac_claim=hmac_claim,
        include_requested_with=include_requested_with,
        extra_headers=extra_headers,
    )
    data = await build_query_data_dynamic(
        media_id=media_id,
        cursor=comment_cursor_bifilter_token,
        fb_dtsg=fb_dtsg,
        lsd_token=lsd_token,
        extra_data=extra_data,
    )

    call = session.post if session else requests.post
    response = call(
        "https://www.instagram.com/graphql/query",
        cookies=cookies,
        headers=headers,
        data=data,
        impersonate="chrome146",
        proxy=proxy if proxy is not None else None,
        timeout=timeout,
    )

    if response.status_code != 200:
        raise Exception(
            f"GraphQL query failed with status code {response.status_code} and response: {response.text}"
        )

    return response
