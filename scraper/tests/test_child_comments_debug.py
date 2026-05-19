"""Debug the child-comments API endpoint directly."""

import asyncio
import json
import logging
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("debug_child")

from curl_cffi import requests
from src.settings import PROXY, PROXY_COUNTRIES_LIST

MEDIA_ID = "3844181034832854577_3233830524"
PARENT_COMMENT_ID = "17920090185142904"
CSRF_TOKEN = ""   # will be extracted
APP_ID = ""
LSD_TOKEN = ""

CHILD_COMMENTS_DOC_ID = "34884685271179117"
CHILD_COMMENTS_FRIENDLY_NAME = "PolarisPostChildCommentsQuery"


async def page_fetch_and_tokens():
    """Fetch the page and get fresh tokens."""
    from src.comment_scraper.post_page import get_post_page
    from src.comment_scraper.utils import PostPageParser

    global CSRF_TOKEN, APP_ID, LSD_TOKEN

    country = random.choice(PROXY_COUNTRIES_LIST)
    proxy = PROXY.format(COUNTRY=country)
    logger.info("Fetching page via proxy country=%s", country)
    html = await get_post_page(
        post_url="https://www.instagram.com/reel/DVZRkipgX4x/",
        proxy=proxy,
    )
    parser = PostPageParser()
    scripts = await parser.get_scripts_from_profile_page(html=html)
    header = await parser.get_header_data(scripts, html=html)

    CSRF_TOKEN = header.csrf_token
    APP_ID = header.app_id
    LSD_TOKEN = header.lsd_token or ""

    logger.info("CSRF=%s APP_ID=%s LSD=%s", CSRF_TOKEN, APP_ID, LSD_TOKEN)

    # Also get first comment's pk
    media_id = await parser.get_media_id(scripts)
    logger.info("MEDIA_ID=%s", media_id)


async def try_child_comments_no_proxy():
    logger.info("=== TRY 1: No proxy, minimal headers ===")
    await page_fetch_and_tokens()

    headers = {
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9",
        "content-type": "application/x-www-form-urlencoded",
        "origin": "https://www.instagram.com",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
        "x-csrftoken": CSRF_TOKEN,
        "x-fb-friendly-name": CHILD_COMMENTS_FRIENDLY_NAME,
        "x-ig-app-id": APP_ID,
    }
    if LSD_TOKEN:
        headers["x-fb-lsd"] = LSD_TOKEN

    variables = {
        "after": None,
        "before": None,
        "media_id": MEDIA_ID,
        "parent_comment_id": PARENT_COMMENT_ID,
        "__relay_internal__pv__PolarisIsLoggedInrelayprovider": True,
    }
    data = {
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
    if LSD_TOKEN:
        data["lsd"] = LSD_TOKEN

    resp = requests.post(
        "https://www.instagram.com/api/graphql",
        impersonate="chrome142",
        headers=headers,
        data=data,
        timeout=30,
    )
    logger.info("Status: %s", resp.status_code)
    logger.info("Headers: %s", dict(resp.headers))
    logger.info("Body (first 2000 chars):\n%s", resp.text[:2000])

    try:
        body = resp.json()
        logger.info("Parsed JSON keys at root: %s", list(body.keys()))
        data_block = body.get("data", {})
        logger.info("data keys: %s", list(data_block.keys()) if isinstance(data_block, dict) else type(data_block))
        for key, val in data_block.items() if isinstance(data_block, dict) else []:
            if isinstance(val, dict):
                logger.info("  %s -> subkeys: %s", key, list(val.keys())[:10])
                if "edges" in val:
                    logger.info("  >>> edges count: %d", len(val["edges"]))
                for sk, sv in val.items():
                    if isinstance(sv, dict) and "edges" in sv:
                        logger.info("  >>> %s -> edges count: %d", sk, len(sv["edges"]))
    except Exception:
        pass


async def main():
    await try_child_comments_no_proxy()


if __name__ == "__main__":
    asyncio.run(main())
