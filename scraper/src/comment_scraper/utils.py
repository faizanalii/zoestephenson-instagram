"""
Utility functions for the comment scraper module.
"""

import asyncio
import json
import logging
import random
import re
from datetime import UTC, datetime
from typing import Any

from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests
from jsonparse import find_key

from src.models import CommentStats, DataRequirements, HeaderRequirements
from src.settings import PROXY, PROXY_COUNTRIES_LIST, RELAY_CHUNK_URL

RATE_LIMIT_ERROR_CODE = 1675004


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

    def _created_at_to_date(created_at: Any) -> str:
        """Convert Unix timestamp-like values to UTC date string (YYYY-MM-DD)."""

        if created_at is None:
            return ""

        if isinstance(created_at, (int, float)):
            return datetime.fromtimestamp(created_at, tz=UTC).date().isoformat()

        if isinstance(created_at, str):
            value = created_at.strip()
            if not value:
                return ""
            try:
                return datetime.fromtimestamp(float(value), tz=UTC).date().isoformat()
            except ValueError:
                # Already a date/ISO string or unknown format; keep original text.
                return value

        return str(created_at)

    for comment in comments:
        node: dict[str, Any] = comment.get("node", {})
        if node.get("user", {}).get("username", "").lower() == username.lower():
            created_at_value = node.get("created_at", "")
            comment_id = node.get("pk")
            raw_text = node.get("text")

            # Detect GIF / image comments. Instagram sets text to null
            # or an empty string when the comment body is a GIF or image.
            # The presence of giphy_media_info confirms it's a GIF.
            if raw_text is None:
                display_text = "GIF" if node.get("giphy_media_info") else "IMAGE/GIF"
            elif raw_text == "" and node.get("giphy_media_info"):
                display_text = "GIF"
            elif raw_text == "":
                display_text = ""
            else:
                display_text = raw_text

            return CommentStats(
                post_url=post_url,
                username=node.get("user", {}).get("username", ""),
                text=display_text,
                likes=node.get("comment_like_count", 0),
                reply_count=node.get("child_comment_count", 0)
                if node.get("child_comment_count") is not None
                else 0,
                date_of_comment=_created_at_to_date(created_at_value),
                comment_id=str(comment_id) if comment_id else None,
            )
    return None


async def get_random_proxy() -> str:
    """
    Get a random proxy from the list of available proxies.
    Args:
    Returns:
        str: A random proxy string.
    """
    # TODO: Disabled the proxy for now
    # return ""
    country: str = random.choice(PROXY_COUNTRIES_LIST)
    proxy_url: str = PROXY.format(COUNTRY=country)

    return proxy_url


async def get_post_id(post_url: str) -> str | None:
    """
    Extract the post ID from the given post URL.
    Args:
        post_url: The URL of the Instagram post.
    Returns:
        The extracted post ID as a string, or None if the post ID cannot be extracted.
    """
    post_id = post_url.rstrip("/").split("/")[-1]
    return post_id if post_id else None


async def normalize_content_type(content_type: str | None) -> str:
    if not content_type:
        return ""
    return content_type.split(";", 1)[0].strip().lower()


async def classify_response(
    status_code: int,
    content_type: str | None,
    body_text: str,
) -> str:
    """
    Classify the response type based on status code, content type, and body text.
    Args:
        status_code: The HTTP status code of the response.
        content_type: The Content-Type header of the response.
        body_text: The raw text of the response body.
    Returns:
        A string classification of the response, such as "json", "html", "http_error
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


async def parse_page_info(
    json_body: dict[str, Any],
) -> tuple[dict[str, Any] | str | None, bool | None]:
    """
    Args:
        json_body: The JSON payload from the GraphQL response.
    Returns:
        A tuple containing the parsed cursor data (or None
        if parsing fails) and a boolean indicating
        whether there is a next page.
    """

    connection: dict = json_body.get("data", {}).get(
        "xdt_api__v1__media__media_id__comments__connection", {}
    )
    page_info: dict = connection.get("page_info", {})
    cursor_raw: str | None = page_info.get("end_cursor")
    has_next_page: bool | None = page_info.get("has_next_page")

    if not cursor_raw:
        return None, has_next_page

    try:
        return json.loads(cursor_raw), has_next_page
    except Exception:  # noqa: BLE001
        # Some responses return an opaque cursor string rather than JSON.
        return cursor_raw, has_next_page


async def extract_rate_limit_error(json_body: dict[str, Any]) -> dict[str, Any] | None:
    """
    Check if the GraphQL response payload contains a rate limit error.
    Args:
        json_body: The JSON payload from the GraphQL response.
    Returns:
        A dictionary containing error details if a rate limit error is found, or None otherwise.
    """
    errors = json_body.get("errors")
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


async def extract_general_errors(json_body: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Extract non-rate-limit errors from the GraphQL response payload.
    Args:
        json_body: The JSON payload from the GraphQL response.
    Returns:
        A list of error dictionaries (excluding rate-limit errors).
    """
    errors = json_body.get("errors")
    if not isinstance(errors, list):
        return []

    general_errors: list[dict[str, Any]] = []
    for error in errors:
        if not isinstance(error, dict):
            continue
        code = error.get("code")
        message = str(error.get("message", ""))
        if code == RATE_LIMIT_ERROR_CODE or "rate limit exceeded" in message.lower():
            continue
        general_errors.append(error)
    return general_errors


async def get_comments(json_body: dict[str, Any]) -> list[dict[str, Any]] | None:
    """
    Extract the list of comments from the GraphQL response JSON body.
    Args:
        json_body: The JSON payload from the GraphQL response.
    Returns:
        A list of comment dictionaries if found, or None otherwise.
    """
    return (
        json_body.get("data", {})
        .get("xdt_api__v1__media__media_id__comments__connection", {})
        .get("edges", [])
    )


# -----
# The following the PAGE Parser related utils
# Parse the first page, extract related utils and return
# -----


class PostPageParser:
    """
    A utility class for parsing
    the post page data and extracting relevant information
    such as first comments, pagination info, and retry timing.
    """

    _FALLBACK_DOC_IDS: dict[str, str] = {
        "PolarisPostCommentsPaginationQuery": "26864966453197043",
        "PolarisPostChildCommentsQuery": "27130774429946606",
    }

    def __init__(self) -> None:
        pass

    @staticmethod
    def _looks_like_doc_id(value: str) -> bool:
        return bool(re.fullmatch(r"\d{15,25}", str(value)))

    @classmethod
    async def get_doc_id(
        cls,
        friendly_name: str,
        json_scripts: list[dict[str, Any]],
        html: str,
    ) -> str:
        """
        Extract the GraphQL doc_id for a given friendly name from the page.

        Searches JSON script blocks first, then falls back to regex on the raw
        HTML, then to hardcoded fallback values.
        """

        for script in json_scripts:
            candidates: list = find_key(script, friendly_name)
            if not candidates:
                continue
            for candidate in candidates:
                if cls._looks_like_doc_id(str(candidate)):
                    logging.info(
                        "Extracted doc_id via find_key for %s: %s",
                        friendly_name,
                        candidate,
                    )
                    return str(candidate)
                if isinstance(candidate, dict):
                    for v in candidate.values():
                        if cls._looks_like_doc_id(str(v)):
                            logging.info(
                                "Extracted doc_id via dict value for %s: %s",
                                friendly_name,
                                v,
                            )
                            return str(v)

        patterns = [
            rf'"{re.escape(friendly_name)}"[\]\s:,]*"?(\d{{15,25}})"?',
            rf"{re.escape(friendly_name)}[\]\s:,]*\"?(\d{{15,25}})\"?",
        ]
        for pattern in patterns:
            match = re.search(pattern, html)
            if match:
                doc_id = match.group(1)
                logging.info(
                    "Extracted doc_id via regex for %s: %s",
                    friendly_name,
                    doc_id,
                )
                return doc_id

        # ── Search CDN JS chunks for relay operation definitions ─────────
        relay_module_name = f"{friendly_name}_instagramRelayOperation"
        cdn_urls: set[str] = set(
            re.findall(
                r"https?://static\.cdninstagram\.com/rsrc\.php/[^\s\"'<>]+\.js",
                html,
            )
        )

        for url in cdn_urls:
            try:
                resp = await asyncio.to_thread(
                    cffi_requests.get, url, impersonate="chrome142", timeout=10
                )
                if resp.status_code != 200:
                    continue
                text = resp.text
            except Exception:
                continue

            if relay_module_name in text:
                idx = text.find(relay_module_name)
                m = re.search(
                    r'a\.exports\s*=\s*"(\d+)"', text[idx : idx + 300]
                )
                if m:
                    doc_id = m.group(1)
                    logging.info(
                        "Extracted doc_id via CDN chunk for %s: %s",
                        friendly_name,
                        doc_id,
                    )
                    return doc_id

                m = re.search(r'(\d{15,25})', text[idx : idx + 300])
                if m:
                    doc_id = m.group(1)
                    logging.info(
                        "Extracted doc_id via CDN chunk (fallback match) for %s: %s",
                        friendly_name,
                        doc_id,
                    )
                    return doc_id

        # ── Try the known relay chunk URL (lazy-loaded JS chunk) ──────────
        if RELAY_CHUNK_URL:
            try:
                resp = await asyncio.to_thread(
                    cffi_requests.get,
                    RELAY_CHUNK_URL,
                    impersonate="chrome142",
                    timeout=10,
                    headers={
                        "accept": "*/*",
                        "sec-fetch-dest": "script",
                        "sec-fetch-mode": "cors",
                        "sec-fetch-site": "cross-site",
                    },
                )
                if resp.status_code == 200 and relay_module_name in resp.text:
                    idx = resp.text.find(relay_module_name)
                    m = re.search(
                        r'a\.exports\s*=\s*"(\d+)"', resp.text[idx : idx + 300]
                    )
                    if m:
                        doc_id = m.group(1)
                        logging.info(
                            "Extracted doc_id via relay chunk for %s: %s",
                            friendly_name,
                            doc_id,
                        )
                        return doc_id
            except Exception:
                pass

        fallback = cls._FALLBACK_DOC_IDS.get(friendly_name, "")
        if fallback:
            logging.info(
                "Using pre-configured doc_id for %s: %s",
                friendly_name,
                fallback,
            )
        return fallback

    async def get_scripts_from_profile_page(self, html: str) -> list[dict[str, Any]]:
        """
        Get the scripts from the profile page response.
        Args:
            html (str): The HTML content of the profile page.
        Returns:
            list[dict[str, Any]]: A list of dictionaries containing JSON
            data from script tags.
        """

        soup = BeautifulSoup(html, "html.parser")

        scripts = soup.find_all("script", attrs={"type": "application/json"})

        # Load them into JSON
        scripts_json: list[dict[str, Any]] = []

        for script in scripts:
            try:
                data = script.text
                if data:
                    scripts_json.append(json.loads(data))
            except json.JSONDecodeError:
                continue

        return scripts_json

    @staticmethod
    async def get_csrf_token(json_scripts: list[dict[str, Any]]) -> str | None:
        """
        Get the CSRF token from the scripts
        Args:
            json_scripts (list[dict]): The list of scripts containing the CSRF token.
        Returns:
            str: The CSRF token.
        """
        for script in json_scripts:
            csrf_token: list[str] = find_key(script, "csrf_token")
            if not csrf_token:
                continue
            return str(csrf_token[0])

        return None

    @staticmethod
    async def get_app_id(json_scripts: list[dict[str, Any]]) -> str | None:
        """
        Get the Instagram app ID from the scripts.
        Args:
            json_scripts (list[dict]): The list of scripts containing the app ID.
        Returns:
            str: The app ID.
        """

        for script in json_scripts:
            app_id: list[str] = find_key(script, "app_id")

            if not app_id:
                continue

            return str(app_id[0])

        return None

    @staticmethod
    async def get_media_id(json_scripts: list[dict[str, Any]]) -> str | None:
        """
        Get the media ID from the scripts.
        Args:
            json_scripts (list[dict]): The list of scripts containing the media ID.
        Returns:
        str: The media ID.
        """

        for script in json_scripts:
            media_id: list[str] = find_key(script, "media_id")

            if not media_id:
                continue

            return str(media_id[0])

        return None

    @staticmethod
    async def get_comment_and_bifilter_token(
        json_scripts: list[dict[str, Any]],
    ) -> dict[str, str] | str | None:
        """
        Get the comment and bifilter token from the scripts.
        Args:
            json_scripts (list[dict[str, Any]]): The list of scripts containing the bifilter token.
        Returns:
            dict[str, str] | None: The bifilter token.
        """
        for script in json_scripts:
            end_cursor: list[str] = find_key(script, "end_cursor")

            if not end_cursor:
                continue

            logging.info("Found end_cursor in script")

            import pprint

            logging.info("end_cursor content: %s", pprint.pformat(end_cursor[0]))

            cursor_raw: str = end_cursor[0]
            try:
                cursor_data = json.loads(cursor_raw)
                if isinstance(cursor_data, dict):
                    return cursor_data
                # Plain JSON value (number, string) — not a valid cursor object.
                return None
            except Exception:
                # Raw opaque token (base64, etc.) — unreliable for the
                # initial GraphQL query. Start pagination fresh with an
                # empty cursor; the response end_cursor drives subsequent pages.
                return None
        logging.warning("No end_cursor found in any script")
        return None

    @staticmethod
    async def extract_lsd_token(html: str) -> str | None:
        """
        Extract the LSD token from the HTML using regex.
        Args:
            html (str): The HTML content to search within.
        Returns:
            str | None: The extracted LSD token, or None if not found.
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

    @staticmethod
    async def extract_dtsg_token(html: str) -> str | None:
        """
        Extract the dtsg token from the HTML using regex.
        Args:
            html (str): The HTML content to search within.
        Returns:
            str | None: The extracted dtsg token, or None if not found.
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

    @staticmethod
    async def extract_claim_token(html: str) -> str | None:
        """
        Extract the claim token from the HTML using regex.
        Args:
            html (str): The HTML content to search within.
        Returns:
            str | None: The extracted claim token, or None if not found.
        """
        match = re.search(r'"claim":"([^"]+)"', html)
        if not match:
            return None
        return match.group(1)

    @staticmethod
    async def get_first_comments(json_scripts: list) -> list | None:
        """
        Get the first comments from the scripts.
        Args:
            json_scripts (list): The list of scripts containing the first comments.
        Returns:
            str: The first comments.
        """
        for data in json_scripts:
            first_comments: list = find_key(
                data, "xdt_api__v1__media__media_id__comments__connection"
            )

            if not first_comments:
                continue

            comments: dict[str, Any] = first_comments[0]

            edges: list[dict[str, Any]] = comments.get("edges", [])

            if not edges:
                continue

            return edges

        return None

    @staticmethod
    async def has_next_comments(json_scripts: list) -> bool:
        """
        Check if there are more comments to load.
        Args:
            json_scripts (list): The list of scripts containing the comments data.
        Returns:
            bool: True if there are more comments to load, False otherwise.
        """
        for data in json_scripts:
            comments_data: list = find_key(
                data, "xdt_api__v1__media__media_id__comments__connection"
            )

            if not comments_data:
                continue

            comments: dict[str, Any] = comments_data[0]

            page_info: dict[str, Any] = comments.get("page_info", {})

            has_next_page: bool = page_info.get("has_next_page", False)

            return has_next_page

        return False

    async def get_header_data(
        self, json_scripts: list[dict[str, Any]], html: str
    ) -> HeaderRequirements:
        """
        Extract header data required for pagination and rate limit checks.
        Args:
            json_scripts (list[dict[str, Any]]): The list of scripts containing the header
            data.
            html (str): The HTML content of the page for extracting tokens not found in scripts.
        Returns:
            HeaderRequirements: The extracted header data.
        """

        csrf_token: str | None = await self.get_csrf_token(json_scripts)
        app_id: str | None = await self.get_app_id(json_scripts)
        hmac_claim: str | None = await self.extract_claim_token(html)
        lsd_token: str | None = await self.extract_lsd_token(html)
        dtsg_token: str | None = await self.extract_dtsg_token(html)
        claim_token: str | None = await self.extract_claim_token(html)

        if not csrf_token or not app_id:
            raise Exception(
                "App ID or CSRF token not found in page scripts, cannot proceed with pagination."
            )

        return HeaderRequirements(
            app_id=app_id,
            csrf_token=csrf_token,
            hmac_claim=hmac_claim,
            lsd_token=lsd_token,
            claim_token=claim_token,
            dtsg_token=dtsg_token,
        )

    async def get_data_requirements(
        self, json_scripts: list[dict[str, Any]], lsd_token: str, fb_dtsg: str
    ) -> DataRequirements:
        """
        Extract data requirements needed for pagination.
        Args:
            json_scripts (list[dict[str, Any]]): The list of scripts containing the data.
            lsd_token (str): The LSD token extracted from the HTML.
            fb_dtsg (str): The FB_DTSG token extracted from the HTML.
        Returns:
            DataRequirements: The extracted data requirements.
        """

        media_id: str | None = await self.get_media_id(json_scripts)
        cursor: dict[str, Any] | str | None = await self.get_comment_and_bifilter_token(
            json_scripts
        )

        # Some reel pages do not expose bifilter cursor in the initial HTML payload.
        # In that case we do an initial media_id-only comments query first.
        if not media_id or not fb_dtsg:
            raise Exception("Missing required data fields for pagination. Cannot proceed.")

        return DataRequirements(
            media_id=media_id,
            cursor=cursor,
            fb_dtsg=fb_dtsg,
            lsd_token=lsd_token,
        )
