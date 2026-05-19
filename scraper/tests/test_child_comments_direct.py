"""Debug child-comments API with hardcoded tokens from a known-good scrape."""

import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("debug_child")

from curl_cffi import requests

# Tokens from the successful Phase 2 run (2026-05-19 test)
CSRF_TOKEN = "UFp-tqu8OD7YpTxGNctLGm"
APP_ID = "936619743392459"
LSD_TOKEN = "AdSTqCfBzghvK16smaCDQridjAw"
MEDIA_ID = "3844181034832854577_3233830524"
PARENT_COMMENT_ID = "17920090185142904"

CHILD_COMMENTS_DOC_ID = "34884685271179117"
FRIENDLY_NAME = "PolarisPostChildCommentsQuery"


async def test_variant(name: str, headers: dict, data: dict):
    logger.info("=== %s ===", name)
    resp = requests.post(
        "https://www.instagram.com/api/graphql",
        impersonate="chrome142",
        headers=headers,
        data=data,
        timeout=30,
    )
    logger.info("Status: %s | content-type: %s", resp.status_code, resp.headers.get("content-type"))
    text_head = resp.text[:1500]
    logger.info("Response:\n%s", text_head)

    try:
        body = resp.json()
        data_block = body.get("data", {})
        if isinstance(data_block, dict):
            for key, val in data_block.items():
                if isinstance(val, dict):
                    edges = None
                    if "edges" in val:
                        edges = val["edges"]
                    else:
                        for sk, sv in val.items():
                            if isinstance(sv, dict) and "edges" in sv:
                                edges = sv["edges"]
                                break
                    if edges is not None:
                        logger.info("  >>> FOUND edges: %d items", len(edges))
                        for e in edges[:3]:
                            n = e.get("node", {})
                            logger.info("    user=%s text=%s", n.get("user", {}).get("username"), (n.get("text") or "")[:50])
        if "errors" in body:
            logger.warning("  ERRORS in response: %s", json.dumps(body["errors"], indent=2)[:1000])
    except Exception as exc:
        logger.info("  (not JSON or parse error: %s)", exc)


async def main():
    # --- Variant 1: Minimal (DEBUGGING STYLE - original approach) ---
    headers_v1 = {
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9,ur;q=0.8",
        "content-type": "application/x-www-form-urlencoded",
        "origin": "https://www.instagram.com",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/137.0.0.0 Safari/537.36",
        "x-csrftoken": CSRF_TOKEN,
        "x-fb-friendly-name": FRIENDLY_NAME,
        "x-ig-app-id": APP_ID,
    }
    if LSD_TOKEN:
        headers_v1["x-fb-lsd"] = LSD_TOKEN

    data_v1 = {
        "av": "0",
        "__d": "www",
        "__user": "0",
        "__a": "1",
        "__req": "1a",
        "__comet_req": "7",
        "fb_api_caller_class": "RelayModern",
        "fb_api_req_friendly_name": FRIENDLY_NAME,
        "server_timestamps": "true",
        "variables": json.dumps({
            "after": None,
            "before": None,
            "media_id": MEDIA_ID,
            "parent_comment_id": PARENT_COMMENT_ID,
        }),
        "doc_id": CHILD_COMMENTS_DOC_ID,
    }
    if LSD_TOKEN:
        data_v1["lsd"] = LSD_TOKEN

    await test_variant("V1: by the book", headers_v1, data_v1)

    # --- Variant 2: Same as V1 but with the full headers we use for main comments ---
    headers_v2 = {
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9,ur;q=0.8",
        "cache-control": "no-cache",
        "content-type": "application/x-www-form-urlencoded",
        "origin": "https://www.instagram.com",
        "pragma": "no-cache",
        "priority": "u=1, i",
        "referer": "https://www.instagram.com/p/DVZRkipgX4x/",
        "sec-ch-ua": '"Google Chrome";v="137", "Chromium";v="137", "Not/A)Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/137.0.0.0 Safari/537.36",
        "x-asbd-id": "359341",
        "x-csrftoken": CSRF_TOKEN,
        "x-fb-friendly-name": FRIENDLY_NAME,
        "x-ig-app-id": APP_ID,
        "x-requested-with": "XMLHttpRequest",
    }
    if LSD_TOKEN:
        headers_v2["x-fb-lsd"] = LSD_TOKEN

    data_v2 = {
        "av": "0",
        "__d": "www",
        "__user": "0",
        "__a": "1",
        "__req": "1a",
        "__comet_req": "7",
        "__crn": "comet.igweb.PolarisDesktopPostRoute",
        "fb_api_caller_class": "RelayModern",
        "fb_api_req_friendly_name": FRIENDLY_NAME,
        "server_timestamps": "true",
        "variables": json.dumps({
            "after": None,
            "before": None,
            "media_id": MEDIA_ID,
            "parent_comment_id": PARENT_COMMENT_ID,
        }),
        "doc_id": CHILD_COMMENTS_DOC_ID,
    }
    if LSD_TOKEN:
        data_v2["lsd"] = LSD_TOKEN

    await test_variant("V2: full headers like main comments", headers_v2, data_v2)

    # --- Variant 3: try /graphql/query endpoint ---
    logger.info("=== V3: /graphql/query endpoint (not /api/graphql) ===")
    resp = requests.post(
        "https://www.instagram.com/graphql/query",
        impersonate="chrome142",
        headers=headers_v2,
        data=data_v2,
        timeout=30,
    )
    logger.info("Status: %s", resp.status_code)
    logger.info("Response:\n%s", resp.text[:1000])


if __name__ == "__main__":
    asyncio.run(main())
