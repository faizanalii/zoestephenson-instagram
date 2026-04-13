from __future__ import annotations

import json
import random
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from src.models import CommentStats

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


def normalize_post_url(post_url: str) -> str:
    """Normalizes a post URL into a stable format without trailing slash noise."""

    return post_url.strip().rstrip("/")


def extract_post_id(post_url: str) -> str:
    """Extracts Instagram post shortcode from a post URL."""

    normalized = normalize_post_url(post_url)
    return normalized.split("/")[-1]


def parse_end_cursor(raw_end_cursor: str | None) -> dict[str, Any] | None:
    """Parses GraphQL end_cursor into a dictionary cursor used for subsequent requests."""

    if not raw_end_cursor:
        return None
    try:
        return json.loads(raw_end_cursor)
    except Exception:  # noqa: BLE001
        return None


def parse_connection(payload: dict[str, Any]) -> dict[str, Any]:
    """Returns the Instagram comments connection object from a GraphQL payload."""

    return payload.get("data", {}).get("xdt_api__v1__media__media_id__comments__connection", {})


def parse_page_info(
    payload: dict[str, Any],
) -> tuple[dict[str, Any] | None, bool | None]:
    """Extracts cursor and has_next_page from GraphQL response payload."""

    connection = parse_connection(payload)
    page_info = connection.get("page_info", {})
    next_cursor = parse_end_cursor(page_info.get("end_cursor"))
    has_next_page = page_info.get("has_next_page")
    return next_cursor, has_next_page


def extract_edges(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extracts comments edges list from GraphQL response payload."""

    connection = parse_connection(payload)
    edges = connection.get("edges", [])
    if not isinstance(edges, list):
        return []
    return [edge for edge in edges if isinstance(edge, dict)]


def random_retry_delay_seconds(min_minutes: int = 3, max_minutes: int = 5) -> int:
    """Generates a randomized retry delay in seconds within the configured minute range."""

    return random.randint(min_minutes * 60, max_minutes * 60)


def build_retry_at(delay_seconds: int) -> datetime:
    """Builds a UTC retry timestamp based on delay seconds."""

    return datetime.now(UTC) + timedelta(seconds=delay_seconds)


def should_process_retry(retry_at: datetime | None, now: datetime | None = None) -> bool:
    """Returns True when retry gate is open and task can be processed now."""

    if retry_at is None:
        return True
    current = now or datetime.now(UTC)
    return current >= retry_at


def normalize_comment_list(comments: Any) -> list[dict[str, Any]]:
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


async def make_run_dir(prefix: str) -> Path:
    """
    Create a directory for storing run data.
    Args:
        prefix: A string prefix to include in the directory name (e.g., "comments").
    Returns:
        path: The Path object of the created directory.
    """
    run_dir = RUNS_DIR / f"{prefix}_{await utc_stamp()}"
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


async def write_json(path: Path, payload: Any) -> None:
    """
    Write a JSON payload to a file, creating parent directories if needed.
    Args:
        path: The file path to write to.
        payload: The data to write as JSON.
    Returns:
        None
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, ensure_ascii=False)


async def write_text(path: Path, text: str) -> None:
    """
    Write text to a file, creating parent directories if needed.
    Args:
        path: The file path to write to.
        text: The text to write.
    Returns:
        None
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        file.write(text)


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


async def classify_response(
    status_code: int,
    content_type: str | None,
    body_text: str,
) -> str:
    """
    Classify the response based on its status code, content type, and body text.
    Args:
        status_code: The HTTP status code.
        content_type: The content type string.
        body_text: The body text of the response.
    Returns:
        The classification of the response.
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


async def summarize_body(body_text: str, max_chars: int = 500) -> str:
    """
    Create a short summary of the body text for logging, with newlines removed.
    Args:
        body_text: The text to summarize.
        max_chars: The maximum number of characters to include in the summary.
    Returns:
        A summarized version of the body text.
    """
    summary = body_text[:max_chars]
    return summary.replace("\n", " ").replace("\r", " ")


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


async def extract_claim_token(html: str) -> str | None:
    """
    Extract the claim token from HTML content.
    Args:
        html: The HTML string to search for the claim token.
    Returns:
        The extracted claim token, or None if not found.
    """
    match = re.search(r'"claim":"([^"]+)"', html)
    if not match:
        return None
    return match.group(1)


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
