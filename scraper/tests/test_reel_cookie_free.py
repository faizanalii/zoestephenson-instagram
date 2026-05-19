"""
Integration test: run the cookie-free pipeline against a reel URL.

Tests each phase independently:
  1. Fetch page (no cookies) via rnet
  2. Extract tokens (csrf, app_id, media_id, cursor, lsd, dtsg, claim)
  3. First GraphQL query with extracted tokens
  4. Search comments from the response
  5. Child-comments API call to verify reply count
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("test_reel")

REEL_URL = "https://www.instagram.com/reel/DVZRkipgX4x/"
TEST_USERNAME = os.getenv("TEST_USERNAME", "")  # set env var or leave empty


async def phase1_fetch_page() -> str:
    """Fetch the reel page HTML (no cookies)."""
    from src.comment_scraper.post_page import get_post_page
    from src.settings import PROXY, PROXY_COUNTRIES_LIST
    import random

    country = random.choice(PROXY_COUNTRIES_LIST)
    proxy = PROXY.format(COUNTRY=country)
    logger.info("Phase 1: fetching page via proxy country=%s url=%s", country, REEL_URL)

    html = await get_post_page(post_url=REEL_URL, proxy=proxy)
    logger.info("Phase 1: got %s bytes of HTML", len(html))
    return html


async def phase2_extract_tokens(html: str) -> dict:
    """Extract GraphQL tokens from the page."""
    from src.comment_scraper.utils import PostPageParser

    parser = PostPageParser()
    json_scripts = await parser.get_scripts_from_profile_page(html=html)
    logger.info("Phase 2: found %d JSON script blocks", len(json_scripts))

    header_data = await parser.get_header_data(json_scripts=json_scripts, html=html)
    media_id = await parser.get_media_id(json_scripts)
    cursor = await parser.get_comment_and_bifilter_token(json_scripts)
    first_comments = await parser.get_first_comments(json_scripts)
    comment_count = sum(
        1 for _ in (first_comments or [])
    )

    tokens = {
        "csrf_token": header_data.csrf_token,
        "app_id": header_data.app_id,
        "lsd_token": header_data.lsd_token,
        "dtsg_token": header_data.dtsg_token,
        "hmac_claim": header_data.hmac_claim,
        "claim_token": header_data.claim_token,
        "media_id": media_id,
        "cursor": cursor,
        "first_comments_count": comment_count,
    }
    for k, v in tokens.items():
        if k in ("cursor",):
            logger.info("  %s = (present, type=%s)", k, type(v).__name__)
        elif isinstance(v, str) and len(str(v)) > 60:
            logger.info("  %s = %s...", k, str(v)[:60])
        else:
            logger.info("  %s = %s", k, v)
    return tokens


async def phase3_graphql_query(tokens: dict, page_num: int = 0) -> dict | None:
    """Run a cookie-free GraphQL query and return the parsed JSON body."""
    from src.comment_scraper.ig_query_client import run_graphql_query
    from src.settings import PROXY, PROXY_COUNTRIES_LIST
    import random

    country = random.choice(PROXY_COUNTRIES_LIST)
    proxy = PROXY.format(COUNTRY=country)

    logger.info(
        "Phase 3 (page %d): GraphQL query via proxy country=%s", page_num, country
    )

    cursor = tokens["cursor"] if page_num == 0 else tokens.get(f"cursor_page_{page_num}")

    try:
        response = await run_graphql_query(
            csrf_token=tokens["csrf_token"],
            app_id=tokens["app_id"],
            media_id=tokens["media_id"],
            post_id="DVZRkipgX4x",
            cursor=cursor,
            proxy=proxy,
            lsd_token=tokens.get("lsd_token"),
            hmac_claim=tokens.get("hmac_claim"),
            fb_dtsg=tokens.get("dtsg_token"),
        )
    except Exception as exc:
        logger.error("GraphQL query failed: %s", exc)
        return None

    logger.info("Phase 3: status=%s content-type=%s", response.status_code, response.headers.get("content-type"))

    raw = response.text
    try:
        body = response.json()
    except Exception:
        logger.error("Response is not valid JSON. First 500 chars:\n%s", raw[:500])
        return None

    return body


async def phase4_search_comments(body: dict) -> list[dict]:
    """Extract and display comments from the response."""
    from src.comment_scraper.utils import (
        get_comments,
        parse_page_info,
        extract_rate_limit_error,
    )

    rate_limit = await extract_rate_limit_error(body)
    if rate_limit:
        logger.warning("RATE LIMITED: %s", rate_limit)
        return []

    comments = await get_comments(body)
    if not comments:
        logger.info("Phase 4: no comments in response")
        return []

    next_cursor, has_next = await parse_page_info(body)
    logger.info(
        "Phase 4: %d comments, has_next=%s",
        len(comments),
        has_next,
    )

    for i, edge in enumerate(comments[:5]):
        node = edge.get("node", {})
        username = node.get("user", {}).get("username", "?")
        text = (node.get("text") or "(no text)")[:80]
        pk = node.get("pk", "?")
        reply_count = node.get("child_comment_count")
        logger.info("  [%d] @%s | replies=%s | pk=%s | %s", i, username, reply_count, pk, text)

    if len(comments) > 5:
        logger.info("  ... and %d more comments", len(comments) - 5)

    return comments


async def phase5_child_comments(tokens: dict, parent_comment_id: str):
    """Test the child-comments API for reply count verification."""
    from src.comment_scraper.child_comments import get_child_comment_count
    from src.settings import PROXY, PROXY_COUNTRIES_LIST
    import random

    logger.info(
        "Phase 5: child-comments API for parent_comment_id=%s (no proxy, direct)",
        parent_comment_id,
    )

    count = await get_child_comment_count(
        media_id=tokens["media_id"],
        parent_comment_id=parent_comment_id,
        csrf_token=tokens["csrf_token"],
        app_id=tokens["app_id"],
        lsd_token=tokens.get("lsd_token"),
        proxy=None,
        timeout=30.0,
    )
    logger.info("Phase 5: reply count = %d", count)
    return count


async def main():
    logger.info("=" * 60)
    logger.info("TEST: Cookie-free reel scraping on %s", REEL_URL)
    logger.info("=" * 60)

    # ── Phase 1: Fetch page ──
    try:
        html = await phase1_fetch_page()
    except Exception as exc:
        logger.error("Phase 1 FAILED: %s", exc)
        return

    # ── Phase 2: Extract tokens ──
    try:
        tokens = await phase2_extract_tokens(html)
        if not tokens.get("csrf_token") or not tokens.get("app_id"):
            logger.error("Phase 2 FAILED: missing csrf_token or app_id. Blocked or no scripts?")
            return
    except Exception as exc:
        logger.error("Phase 2 FAILED: %s", exc)
        return

    # ── Phase 3: First GraphQL page ──
    body = await phase3_graphql_query(tokens, page_num=0)
    if body is None:
        logger.error("Phase 3 FAILED.")
        return

    # ── Phase 4: Search comments ──
    comments = await phase4_search_comments(body)
    if not comments:
        logger.info("Phase 4: no comments. Checking if we have a cursor for the next page...")
        from src.comment_scraper.utils import parse_page_info
        next_cursor, has_next = await parse_page_info(body)
        if has_next and next_cursor:
            logger.info("  has_next=True, next_cursor present. Page 0 was empty — trying page 1...")
            tokens["cursor_page_0"] = tokens.get("cursor")
            tokens["cursor"] = next_cursor
            body2 = await phase3_graphql_query(tokens, page_num=1)
            if body2:
                comments = await phase4_search_comments(body2)

    logger.info("Phase 4: total comments extracted = %d", len(comments))

    # ── Phase 5: Test child-comments API on the first comment with replies ──
    if comments:
        comment_with_replies = None
        for edge in comments:
            node = edge.get("node", {})
            if node.get("child_comment_count"):
                comment_with_replies = edge
                break
        if not comment_with_replies:
            comment_with_replies = comments[0]

        parent_pk = comment_with_replies.get("node", {}).get("pk")
        if parent_pk:
            await phase5_child_comments(tokens, str(parent_pk))

    # ── Summary ──
    logger.info("=" * 60)
    logger.info("SUMMARY")
    logger.info("  Phase 1 (page fetch):   OK (%d bytes)", len(html))
    logger.info("  Phase 2 (tokens):       csrf=%s app_id=%s media_id=%s cursor=%s",
                "YES" if tokens.get("csrf_token") else "NO",
                "YES" if tokens.get("app_id") else "NO",
                "YES" if tokens.get("media_id") else "NO",
                "YES" if tokens.get("cursor") else "NO")
    logger.info("  Phase 3 (GraphQL):      OK")
    logger.info("  Phase 4 (comments):     %d comments found", len(comments))
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
