"""Full integration test: doc_id sources + API calls with proxy."""

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
logger = logging.getLogger("full_test")

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

TEST_URL = "https://www.instagram.com/reel/DVZRkipgX4x/"
TEST_USERNAME = "arladairyuk"


async def extract_and_call() -> bool:
    # ── Step 0: fetch page via proxy ──
    proxy0 = await get_random_proxy()
    logger.info("STEP 0: Fetch page via proxy")
    logger.info("  URL: %s", TEST_URL)
    html = await get_post_page(TEST_URL, proxy=proxy0)
    logger.info("  HTML: %d bytes", len(html))

    parser = PostPageParser()
    scripts = await parser.get_scripts_from_profile_page(html=html)
    header = await parser.get_header_data(scripts, html=html)
    media_id = await parser.get_media_id(scripts)
    post_id = TEST_URL.rstrip("/").split("/")[-1]

    # ── Step 1: extract doc_ids ──
    logger.info("STEP 1: Extract doc_ids (cascade: JSON -> HTML -> CDN -> relay chunk -> fallback)")

    pag_doc = await parser.get_doc_id(PAGINATION_FRIENDLY_NAME, scripts, html)
    child_doc = await parser.get_doc_id(CHILD_COMMENTS_FRIENDLY_NAME, scripts, html)

    logger.info("  Pagination doc_id = %s", pag_doc)
    logger.info("  Child comments doc_id = %s", child_doc)

    # ── Step 2: comment pagination API ──
    proxy1 = await get_random_proxy()
    logger.info("STEP 2: Comment Pagination API (via proxy)")
    logger.info("  doc_id: %s", pag_doc)

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
        doc_id=pag_doc,
    )

    resp = await asyncio.to_thread(
        cffi_requests.post,
        "https://www.instagram.com/graphql/query",
        impersonate="chrome142",
        headers=page_headers,
        data=page_data,
        proxy=proxy1,
        timeout=30,
    )
    logger.info("  Status: %s", resp.status_code)

    if resp.status_code != 200:
        logger.error("  FAIL: non-200")
        return False

    body = resp.json()
    if body.get("errors"):
        logger.error("  FAIL: %s", json.dumps(body["errors"])[:300])
        return False

    comments = await get_comments(body)
    _, has_next = await parse_page_info(body)
    logger.info("  Comments: %d | has_next_page: %s", len(comments), has_next)

    found_target = False
    first_comment_pk = None

    for i, edge in enumerate(comments[:8]):
        node = edge.get("node", {})
        username = node.get("user", {}).get("username", "?")
        text = (node.get("text") or "(gif)")[:50]
        pk = node.get("pk")
        child_count = node.get("child_comment_count")

        if i == 0 and pk:
            first_comment_pk = str(pk)

        marker = " <-- TARGET" if username.lower() == TEST_USERNAME.lower() else ""
        logger.info(
            "    [%d] @%-22s replies=%s pk=%s %s%s", i, username, child_count, pk, text, marker
        )

        if username.lower() == TEST_USERNAME.lower():
            found_target = True

    if len(comments) > 8:
        logger.info("    ... +%d more", len(comments) - 8)

    if found_target:
        logger.info("  RESULT: Target user @%s found in first page!", TEST_USERNAME)
    else:
        logger.info("  RESULT: @%s not in first page (may be deeper)", TEST_USERNAME)

    # ── Step 3: child comments API ──
    if not first_comment_pk:
        logger.warning("  SKIP child comments: no first comment")
        return True

    proxy2 = await get_random_proxy()
    logger.info("STEP 3: Child Comments API (via proxy)")
    logger.info("  doc_id: %s", child_doc)
    logger.info("  parent_comment_id: %s", first_comment_pk)

    reply_count = await get_child_comment_count(
        media_id=media_id,
        parent_comment_id=first_comment_pk,
        csrf_token=header.csrf_token,
        app_id=header.app_id,
        lsd_token=header.lsd_token,
        doc_id=child_doc,
        proxy=proxy2,
        timeout=30,
    )
    logger.info("  Child comments for pk=%s: %d", first_comment_pk, reply_count)

    return True


if __name__ == "__main__":
    ok = asyncio.run(extract_and_call())
    logger.info("=" * 50)
    logger.info("OVERALL: %s", "PASS" if ok else "FAIL")
    logger.info("=" * 50)
    sys.exit(0 if ok else 1)
