"""Integration test: extract doc_ids from CDN chunks and call the actual APIs."""

import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("test_api")

from curl_cffi import requests as cffi_requests

from src.comment_scraper.child_comments import (
    CHILD_COMMENTS_FRIENDLY_NAME,
    get_child_comment_count,
)
from src.comment_scraper.ig_query_client import (
    PAGINATION_FRIENDLY_NAME,
    build_headers,
    build_query_data,
)
from src.comment_scraper.post_page import get_post_page
from src.comment_scraper.utils import (
    PostPageParser,
    get_comments,
    get_random_proxy,
    parse_page_info,
)

TEST_URL = "https://www.instagram.com/p/DWte0fylh5b"


async def main():
    proxy = await get_random_proxy()
    logger.info("Fetching page: %s", TEST_URL)

    html = await get_post_page(TEST_URL, proxy=proxy)
    logger.info("Page fetched: %d bytes", len(html))

    parser = PostPageParser()
    scripts = await parser.get_scripts_from_profile_page(html=html)
    header = await parser.get_header_data(scripts, html=html)
    media_id = await parser.get_media_id(scripts)
    post_id = TEST_URL.rstrip("/").split("/")[-1]

    logger.info(
        "Tokens: csrf=%s app=%s media=%s lsd=%s dtsg=%s",
        header.csrf_token[:8],
        header.app_id,
        media_id,
        (header.lsd_token or "")[:20],
        (header.dtsg_token or "")[:20],
    )

    # ---- PHASE 1: Extract doc_ids ----
    logger.info("=" * 60)
    logger.info("PHASE 1: Extract doc_ids via CDN chunks")
    logger.info("=" * 60)

    pagination_doc = await parser.get_doc_id(PAGINATION_FRIENDLY_NAME, scripts, html)
    child_doc = await parser.get_doc_id(CHILD_COMMENTS_FRIENDLY_NAME, scripts, html)
    logger.info("Pagination doc_id = %s", pagination_doc)
    logger.info("Child comments doc_id = %s", child_doc)

    # ---- PHASE 2: Test comment pagination API ----
    logger.info("=" * 60)
    logger.info("PHASE 2: Call comment pagination API")
    logger.info("=" * 60)

    page_headers = await build_headers(
        csrf_token=header.csrf_token,
        app_id=header.app_id,
        post_id=post_id,
        lsd_token=header.lsd_token,
        hmac_claim=header.hmac_claim,
    )
    page_data = await build_query_data(
        media_id=media_id,
        cursor=None,
        fb_dtsg=header.dtsg_token,
        lsd_token=header.lsd_token,
        doc_id=pagination_doc,
    )

    proxy2 = await get_random_proxy()
    resp = await asyncio.to_thread(
        cffi_requests.post,
        "https://www.instagram.com/graphql/query",
        impersonate="chrome142",
        headers=page_headers,
        data=page_data,
        proxy=proxy2,
        timeout=30,
    )

    logger.info("Status: %s | Content-Type: %s", resp.status_code, resp.headers.get("content-type"))

    if resp.status_code != 200:
        logger.error("FAIL: non-200 response: %s", resp.text[:300])
        return False

    body = resp.json()
    errors = body.get("errors", [])
    if errors:
        logger.error("FAIL: API errors: %s", json.dumps(errors, indent=2)[:500])
        return False

    comments = await get_comments(body)
    next_cursor, has_next = await parse_page_info(body)
    logger.info("Comments: %d | has_next_page: %s", len(comments), has_next)

    first_pk = None
    for i, edge in enumerate(comments[:3]):
        node = edge.get("node", {})
        username = node.get("user", {}).get("username", "?")
        text = (node.get("text") or "(gif/empty)")[:60]
        pk = node.get("pk", "?")
        child_count = node.get("child_comment_count")
        if i == 0:
            first_pk = str(pk) if pk else None
        logger.info("  [%d] @%-20s | replies=%s | pk=%s | %s", i, username, child_count, pk, text)

    if not comments:
        logger.error("FAIL: No comments returned")
        return False

    logger.info("PASS: Comment pagination API works")

    # ---- PHASE 3: Test child comments API ----
    logger.info("=" * 60)
    logger.info("PHASE 3: Call child comments API")
    logger.info("=" * 60)

    if not first_pk:
        logger.warning("SKIP: No first comment pk to test child comments")
        return True

    logger.info("Using parent_comment_id=%s", first_pk)
    reply_count = await get_child_comment_count(
        media_id=media_id,
        parent_comment_id=first_pk,
        csrf_token=header.csrf_token,
        app_id=header.app_id,
        lsd_token=header.lsd_token,
        doc_id=child_doc,
        proxy=await get_random_proxy(),
        timeout=30,
    )
    logger.info("Child comment count for pk=%s: %d", first_pk, reply_count)
    logger.info("PASS: Child comments API works")

    logger.info("=" * 60)
    logger.info("ALL PHASES PASSED")
    logger.info("=" * 60)
    return True


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
