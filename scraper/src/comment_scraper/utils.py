from __future__ import annotations

import json
import random
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from jsonparse import find_key

from src.models import CommentStats
from src.settings import (
    PROXY,
    PROXY_COUNTRIES_LIST,
    RETRY_DELAY_MAX_SECONDS,
    RETRY_DELAY_MIN_SECONDS,
)

RUNS_DIR = Path(__file__).resolve().parent / "runs"

RATE_LIMIT_ERROR_CODE = 1675004

SENSITIVE_KEYS = {
    "cookie",
    "csrftoken",
    "sessionid",
    "x-csrftoken",
    "x-ig-www-claim",
    "proxy",
}


async def get_random_proxy() -> str:
    """
    Get a random proxy from the list of available proxies.
    Args:
    Returns:
        str: A random proxy string.
    """

    country: str = random.choice(PROXY_COUNTRIES_LIST)
    proxy_url: str = PROXY.format(COUNTRY=country)

    return proxy_url


async def get_scripts_from_profile_page(html: str) -> list[dict[str, Any]]:
    """
    Get the scripts from the profile page response.
    Args:
        html (str): The HTML content of the profile page.
    Returns:
        list[dict[str, Any]]: A list of dictionaries containing the JSON data
        from each script tag.
    """

    soup = BeautifulSoup(html, "html.parser")
    scripts = soup.find_all("script", attrs={"type": "application/json"})
    json_scripts: list[dict[str, Any]] = []

    for script in scripts:
        try:
            json_data: dict[str, Any] = json.loads(script.text)
            json_scripts.append(json_data)
        except Exception:  # noqa: BLE001
            continue

    return json_scripts


async def get_csrf_token(scripts: list[dict[str, Any]]) -> str | None:
    """
    Get the CSRF token from the scripts
    Args:
        :list[dict]: The list of scripts containing the CSRF token.
    Returns:
        str: The CSRF token.
    """
    for script in scripts:
        csrf_token: list[str] = find_key(script, "csrf_token")

        if not csrf_token:
            continue
        return csrf_token[0]

    return None


async def get_app_id(scripts: list[dict[str, Any]]) -> str | None:
    """
    Get the Instagram app ID from the scripts.
    Args:
        :list[dict]: The list of scripts containing the app ID.
    Returns:
        str: The app ID.
    """

    for data in scripts:
        app_id: list[str] = find_key(data, "app_id")
        if not app_id:
            continue
        return app_id[0]

    return None


async def get_media_id(scripts: list[dict[str, Any]]) -> str | None:
    """
    Get the media ID from the scripts.
    Args:
        :list[dict]: The list of scripts containing the media ID.
    Returns:
        str: The media ID.
    """

    for script in scripts:
        media_id: list[str] = find_key(script, "media_id")

        if not media_id:
            continue
        return media_id[0]

    return None


async def get_hmac_claim(scripts: list[dict[str, Any]]) -> str | None:
    """
    Get the HMAC claim from the scripts.
    Args:
        :list[dict]: The list of scripts containing the HMAC claim.
    Returns:
        str: The HMAC claim.
    """
    for script in scripts:
        hmac_claim: list[str] = find_key(script, "claim")
        if not hmac_claim:
            continue
        return hmac_claim[0]

    return None


async def get_first_comments(json_scripts: list) -> list | None:
    """
    Get the first comments from the scripts.
    Args:
        json_scripts (list): The list of scripts containing the first comments.
    Returns:
        str: The first comments.
    """
    for data in json_scripts:
        first_comments: list = find_key(data, "xdt_api__v1__media__media_id__comments__connection")

        if not first_comments:
            continue

        comments: dict[str, Any] = first_comments[0]

        edges: list[dict[str, Any]] = comments.get("edges", [])

        if not edges:
            continue

        return edges

    return None


async def has_next_comments(json_scripts: list) -> bool:
    """
    Check if there are more comments to load.
    Args:
        json_scripts (list): The list of scripts containing the comments data.
    Returns:
        bool: True if there are more comments to load, False otherwise.
    """
    for data in json_scripts:
        comments_data: list = find_key(data, "xdt_api__v1__media__media_id__comments__connection")

        if not comments_data:
            continue

        comments: dict[str, Any] = comments_data[0]

        page_info: dict[str, Any] = comments.get("page_info", {})

        has_next_page: bool = page_info.get("has_next_page", False)

        return has_next_page

    return False


async def get_cached_comment_cursor(scripts: list[BeautifulSoup]) -> str | None:
    """
    Get the cached comment cursor from the scripts.
    Args:
        :list[dict]: The list of scripts containing the cached comment cursor.
    Returns:
        str: The cached comment cursor.
    """
    for script in scripts:
        try:
            data = json.loads(script.text)
        except Exception:
            continue
        cached_comment_cursor: list[str] = find_key(data, "cached_comments_cursor")
        if not cached_comment_cursor:
            continue
        return cached_comment_cursor[0]

    return None


async def get_comment_and_bifilter_token(
    scripts: list[dict[str, Any]],
) -> dict[str, str] | None:
    """
    Get the comment and bifilter token from the scripts.
    Args:
        :list[dict]: The list of scripts containing the bifilter token.
    Returns:
        str: The bifilter token.
    """
    for script in scripts:
        end_cursor: list[str] = find_key(script, "end_cursor")

        if not end_cursor:
            continue

        # Skip the first script if it contains end_cursor

        cursor_data: dict[str, str] = json.loads(end_cursor[0])

        return cursor_data

    return None


async def get_comment_count(json_scripts: list) -> int:
    """
    Extract the comment count from the JSON scripts.
    Args:
        json_scripts (list): A list of JSON data extracted from script tags.
    Returns:
        int: The comment count extracted from the JSON data, or -1 if not found.
    """

    for data in json_scripts:
        comment_count: list[int] = find_key(data, "comment_count")

        if not comment_count:
            continue

        return comment_count[0]

    return 0


def normalize_post_url(post_url: str) -> str:
    """Normalizes a post URL into a stable format without trailing slash noise."""

    return post_url.strip().rstrip("/")


def extract_post_id(post_url: str) -> str:
    """Extracts Instagram post shortcode from a post URL."""

    normalized = normalize_post_url(post_url)
    return normalized.split("/")[-1]


async def parse_end_cursor(raw_end_cursor: str | None) -> dict[str, Any] | None:
    """Parses GraphQL end_cursor into a dictionary cursor used for subsequent requests."""

    if not raw_end_cursor:
        return None
    try:
        return json.loads(raw_end_cursor)
    except Exception:  # noqa: BLE001
        return None


async def parse_connection(payload: dict[str, Any]) -> dict[str, Any]:
    """Returns the Instagram comments connection object from a GraphQL payload."""

    return payload.get("data", {}).get("xdt_api__v1__media__media_id__comments__connection", {})


async def parse_page_info(
    payload: dict[str, Any],
) -> tuple[dict[str, Any] | None, bool | None]:
    """
    Extracts cursor and has_next_page from GraphQL response payload.
    Args:
        payload: The dictionary containing the API response.
    Returns:
        A tuple containing the next cursor (or None if not found) and a boolean indicating
        whether there are more pages of comments to load.
    """

    connection = await parse_connection(payload)
    page_info = connection.get("page_info", {})
    next_cursor = await parse_end_cursor(page_info.get("end_cursor"))
    has_next_page = page_info.get("has_next_page")
    return next_cursor, has_next_page


async def extract_edges(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extracts comments edges list from GraphQL response payload."""

    connection = await parse_connection(payload)
    edges = connection.get("edges", [])
    if not isinstance(edges, list):
        return []
    return [edge for edge in edges if isinstance(edge, dict)]


def random_retry_delay_seconds(
    min_seconds: int = RETRY_DELAY_MIN_SECONDS,
    max_seconds: int = RETRY_DELAY_MAX_SECONDS,
) -> int:
    """Generates a randomized retry delay in seconds within configured bounds."""

    return random.randint(min_seconds, max_seconds)


def build_retry_at(delay_seconds: int) -> datetime:
    """Builds a UTC retry timestamp based on delay seconds."""

    return datetime.now(UTC) + timedelta(seconds=delay_seconds)


def should_process_retry(retry_at: datetime | None, now: datetime | None = None) -> bool:
    """Returns True when retry gate is open and task can be processed now."""

    if retry_at is None:
        return True
    current = now or datetime.now(UTC)
    return current >= retry_at


def is_cursor_stale(
    cursor_timestamp: datetime | None,
    now: datetime | None = None,
    max_age_seconds: int = 240,
) -> bool:
    """
    Returns True when persisted cursor state is older than max_age_seconds.
    Args:
        cursor_timestamp: The datetime when the cursor was last updated.
        now: The current datetime for comparison. If None, uses current UTC time.
        max_age_seconds: The maximum age in seconds before a cursor is considered stale.
    Returns:
        bool: True if the cursor is stale and should be refreshed, False otherwise.
    """

    if cursor_timestamp is None:
        return False
    current = now or datetime.now(UTC)
    age_seconds = (current - cursor_timestamp).total_seconds()
    return age_seconds > max_age_seconds


async def normalize_comment_list(comments: Any) -> list[dict[str, Any]]:
    """Normalizes database/API comments into list form expected by search_comment."""

    if comments is None:
        return []
    if isinstance(comments, list):
        return comments
    return []


async def utc_stamp() -> str:
    """
    Get the current UTC timestamp as a string in the format YYYYMMDD_HHMMSS.
    Args:
    Returns:        A string representing the current UTC timestamp.
    """
    return datetime.now(UTC).strftime("%Y%m%d_%H%M%S")


async def normalize_content_type(content_type: str | None) -> str:
    """
    Normalize the content type by removing any parameters.
    Args:
        content_type: The content type string.
    Returns:
        The normalized content type.
    """
    if not content_type:
        return ""
    return content_type.split(";", 1)[0].strip().lower()


async def extract_html_markers(html: str) -> dict[str, bool]:
    """
    Extract markers from HTML content.
    Args:
        html: The HTML string to analyze.
    Returns:
        A dictionary of boolean values indicating the presence of each marker.
    """
    lowered = html.lower()
    return {
        "looks_logged_out": '"is_logged_out_user":true' in lowered,
        "has_account_id_zero": '"account_id":"0"' in lowered,
        "has_user_id_zero": '"user_id":"0"' in lowered,
        "has_http_error_page": "httperrorpage" in lowered,
    }


async def extract_lsd_token(html: str) -> str | None:
    """
    Extract the LSD token from HTML content using common patterns.
    Args:
        html: The HTML string to search for the LSD token.
    Returns:
        The extracted LSD token, or None if not found.
    """
    # Common payload shapes include ["LSD",[],{"token":"..."}] and "lsd":"..."
    patterns = [
        r'\["LSD",\[\],\{"token":"([^"]+)"\}',
        r'"lsd":"([^"]+)"',
    ]
    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            return match.group(1)
    return None


async def extract_dtsg_token(html: str) -> str | None:
    """
    Extract the DTSG token from HTML content using common patterns.
    Args:
        html: The HTML string to search for the DTSG token.
    Returns:
        The extracted DTSG token, or None if not found.
    """
    # Common payload shapes include MRequestConfig.dtsg.token and DTSGInitialData.token
    patterns = [
        r'"dtsg":\{"token":"([^"]+)"',
        r'\["DTSGInitialData",\[\],\{"token":"([^"]+)"\}',
    ]
    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            return match.group(1)
    return None


async def extract_rate_limit_error(payload: dict[str, Any]) -> dict[str, Any] | None:
    """
    Extract rate limit error information from a payload.
    Args:
        payload: The dictionary containing the API response.
    Returns:
        A dictionary with rate limit error details, or None if not found.
    """
    errors = payload.get("errors")
    if not isinstance(errors, list):
        return None

    for error in errors:
        if not isinstance(error, dict):
            continue
        message = str(error.get("message", ""))
        code = error.get("code")
        if code == RATE_LIMIT_ERROR_CODE or "rate limit exceeded" in message.lower():
            return {
                "message": message,
                "severity": error.get("severity"),
                "code": code,
            }

    return None


async def redact_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    """
    Redact sensitive information from a dictionary based on predefined keys.
    Args:
        mapping: The dictionary to redact.
    Returns:
        A new dictionary with sensitive information redacted.
    """
    redacted: dict[str, Any] = {}
    for key, value in mapping.items():
        key_l = key.lower()
        if key_l in SENSITIVE_KEYS:
            redacted[key] = "<redacted>"
            continue
        redacted[key] = value
    return redacted


async def search_comment(
    comments: list[dict[str, Any]], username: str, post_url: str
) -> CommentStats | None:
    """
    Search for a comment containing the target text.
    Args:
        comments: A list of comment dictionaries to search through.
        username: The username to search for within the comments.
    Returns:
        The first comment dictionary that contains the target username, or None if not found.
    """

    for comment in comments:
        node: dict[str, Any] = comment.get("node", {})
        if node.get("user", {}).get("username", "").lower() == username.lower():
            return CommentStats(
                post_url=post_url,
                username=comment.get("user", {}).get("username", ""),
                text=comment.get("text", ""),
                likes=comment.get("comment_like_count", 0),
                reply_count=comment.get("child_comment_count", 0),
                date_of_comment=comment.get("created_at", ""),
            )
    return None


async def classify_response(
    status_code: int,
    content_type: str | None,
    body_text: str,
) -> str:
    """
    Classify the response based on its status code and content.
    Args:
        status_code: The HTTP status code.
        content_type: The content type of the response.
        body_text: The text of the response body.
    Returns:
        A string indicating the classification of the response.
    """
    normalized = await normalize_content_type(content_type)
    body_head = body_text.lstrip()[:200].lower()

    if "json" in normalized:
        return "json"
    if normalized in {"text/javascript", "application/javascript", "text/plain"}:
        if body_head.startswith("{") or body_head.startswith("["):
            return "json"
    if body_head.startswith("{") or body_head.startswith("["):
        return "json"
    if body_head.startswith("<!doctype html") or body_head.startswith("<html"):
        return "html"
    if status_code >= 400:
        return "http_error"
    return "unknown"
