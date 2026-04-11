"""
Utility functions for the post sorting module.
"""

import json
import random
from typing import Any

from bs4 import BeautifulSoup, Tag
from jsonparse import find_key

from src.settings import PROXY, PROXY_COUNTRIES_LIST


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


async def get_page_scripts(html_content: str) -> list[Tag]:
    """
    Extract all script tags from the HTML content.
    Args:
        html_content (str): The HTML content of the page.
    Returns:
        list: A list of script tags found in the HTML content.
    """

    soup = BeautifulSoup(html_content, "html.parser")

    scripts: list[Tag] = soup.find_all("script", attrs={"type": "application/json"})

    return scripts


async def filter_scripts_with_jsons(scripts: list[Tag]) -> list:
    """
    Filter the script tags to find those that contain JSON data.
    Args:
        scripts (list): A list of script tags.
    Returns:
        list: A list of script tags that contain JSON data.
    """

    json_scripts: list = []
    for script in scripts:
        try:
            data = json.loads(script.text)
            json_scripts.append(data)

        except (json.JSONDecodeError, TypeError):
            continue

    return json_scripts


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


async def get_media_id(json_scripts: list) -> str | None:
    """
    Get the media ID from the scripts.
    Args:
        json_scripts (list): The list of scripts containing the media ID.
    Returns:
        str: The media ID.
    """

    for data in json_scripts:
        media_id: list[str] = find_key(data, "media_id")

        if not media_id:
            continue

        return media_id[0]

    return None


async def get_hmac_claim(json_scripts: list) -> str | None:
    """
    Get the HMAC claim from the scripts.
    Args:
        json_scripts (list): The list of scripts containing the HMAC claim.
    Returns:
        str: The HMAC claim.
    """
    for data in json_scripts:
        hmac_claim: list[str] = find_key(data, "claim")

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
