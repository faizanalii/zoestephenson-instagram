"""
Utility functions for the post sorting module.
Cookie-free — extracts metadata from Instagram's public page JSON.
"""

import json
import random
from typing import Any

from bs4 import BeautifulSoup, Tag
from jsonparse import find_key

from src.settings import PROXY, PROXY_COUNTRIES_LIST


async def get_random_proxy() -> str:
    country: str = random.choice(PROXY_COUNTRIES_LIST)
    proxy_url: str = PROXY.format(COUNTRY=country)
    return proxy_url


async def get_page_scripts(html_content: str) -> list[Tag]:
    soup = BeautifulSoup(html_content, "html.parser")
    scripts: list[Tag] = soup.find_all("script", attrs={"type": "application/json"})
    return scripts


async def filter_scripts_with_jsons(scripts: list[Tag]) -> list[dict[str, Any]]:
    json_scripts: list[dict[str, Any]] = []
    for script in scripts:
        try:
            data = json.loads(script.text)
            json_scripts.append(data)
        except (json.JSONDecodeError, TypeError):
            continue
    return json_scripts


async def get_comment_count(json_scripts: list[dict[str, Any]]) -> int:
    for data in json_scripts:
        comment_count: list[int] = find_key(data, "comment_count")
        if not comment_count:
            continue
        return int(comment_count[0])
    return 0


async def get_media_id(json_scripts: list[dict[str, Any]]) -> str | None:
    for data in json_scripts:
        media_id: list[str] = find_key(data, "media_id")
        if not media_id:
            continue
        return str(media_id[0])
    return None


async def get_hmac_claim(json_scripts: list[dict[str, Any]]) -> str | None:
    for data in json_scripts:
        hmac_claim: list[str] = find_key(data, "claim")
        if not hmac_claim:
            continue
        return str(hmac_claim[0])
    return None


async def get_first_comments(json_scripts: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    for data in json_scripts:
        first_comments: list[dict[str, Any]] = find_key(
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


def first_comments_have_reply_metadata(first_comments: list[dict[str, Any]] | None) -> bool:
    if not first_comments:
        return False
    for edge in first_comments:
        if not isinstance(edge, dict):
            continue
        node = edge.get("node", {})
        if not isinstance(node, dict):
            continue
        if "child_comment_count" in node:
            return True
    return False


async def has_next_comments(json_scripts: list[dict[str, Any]]) -> bool:
    for data in json_scripts:
        comments_data: list[dict[str, Any]] = find_key(
            data, "xdt_api__v1__media__media_id__comments__connection"
        )
        if not comments_data:
            continue
        comments: dict[str, Any] = comments_data[0]
        page_info: dict[str, Any] = comments.get("page_info", {})
        has_next_page: bool = page_info.get("has_next_page", False)
        return has_next_page
    return False
