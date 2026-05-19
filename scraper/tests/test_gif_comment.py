"""Debug: find arladairyuk's GIF comment on reel DWeD5LnjJt4"""

import asyncio, json, logging, sys, random
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("gif_test")

from curl_cffi import requests
from src.comment_scraper.post_page import get_post_page
from src.comment_scraper.utils import PostPageParser, classify_response, get_comments, parse_page_info, extract_rate_limit_error
from src.comment_scraper.ig_query_client import run_graphql_query
from src.settings import PROXY, PROXY_COUNTRIES_LIST

REEL_URL = "https://www.instagram.com/reel/DWeD5LnjJt4/"
TARGET = "arladairyuk"
POST_ID = "DWeD5LnjJt4"


async def main():
    country = random.choice(PROXY_COUNTRIES_LIST)
    proxy = PROXY.format(COUNTRY=country)
    logger.info("Fetching page via %s", country)

    html = await get_post_page(REEL_URL, proxy=proxy)
    parser = PostPageParser()
    scripts = await parser.get_scripts_from_profile_page(html=html)
    header = await parser.get_header_data(scripts, html=html)
    media_id = await parser.get_media_id(scripts)
    cursor = await parser.get_comment_and_bifilter_token(scripts)

    logger.info("media_id=%s cursor=%s", media_id, cursor is not None)
    logger.info("csrf=%s app_id=%s", header.csrf_token[:8], header.app_id)

    total_comments = 0
    page = 0

    while page < 50:  # max 50 pages
        page_proxy = PROXY.format(COUNTRY=random.choice(PROXY_COUNTRIES_LIST))
        try:
            resp = await run_graphql_query(
                csrf_token=header.csrf_token,
                app_id=header.app_id,
                media_id=media_id,
                post_id=POST_ID,
                cursor=cursor,
                proxy=page_proxy,
                lsd_token=header.lsd_token,
                hmac_claim=header.hmac_claim,
                fb_dtsg=header.dtsg_token,
            )
        except Exception as e:
            logger.error("Page %d query failed: %s", page, e)
            break

        body = resp.json()
        comments = await get_comments(body)
        next_cursor, has_next = await parse_page_info(body)
        rate = await extract_rate_limit_error(body)

        logger.info("Page %d: %d comments, has_next=%s, rate_limit=%s",
                     page, len(comments or []), has_next, bool(rate))

        if comments:
            for i, edge in enumerate(comments):
                node = edge.get("node", {})
                username = node.get("user", {}).get("username", "?")
                text = node.get("text")
                pk = node.get("pk", "?")
                likes = node.get("comment_like_count", 0)
                reply_count = node.get("child_comment_count")

                # Highlight if it's a GIF comment (text is None)
                is_gif = text is None
                prefix = ">>>" if is_gif else "   "

                logger.info("%s [p%d #%d] @%-25s | text=%s | likes=%s | replies=%s | pk=%s | gif=%s",
                          ">>>" if username.lower() == TARGET.lower() else "   ",
                          page, i, username,
                          repr(text)[:60] if text else "(None/gif)",
                          likes, reply_count, pk, is_gif)

                if username.lower() == TARGET.lower():
                    logger.info("=" * 60)
                    logger.info("FOUND @%s on page %d, index %d", TARGET, page, i)
                    logger.info("  text:      %s", repr(text))
                    logger.info("  likes:     %s", likes)
                    logger.info("  replies:   %s", reply_count)
                    logger.info("  pk:        %s", pk)
                    logger.info("  is_gif:    %s", is_gif)
                    logger.info("  full node: %s", json.dumps(node, indent=2))
                    logger.info("=" * 60)
                    return

            total_comments += len(comments)

        if rate:
            logger.warning("Rate limited on page %d, sleeping 30s...", page)
            await asyncio.sleep(30)
            continue

        if not has_next or not next_cursor:
            logger.info("No more pages. Total comments scanned: %d", total_comments)
            break

        cursor = next_cursor
        page += 1
        await asyncio.sleep(random.uniform(0.3, 0.8))

    logger.info("NOT FOUND. Scanned %d comments across %d pages.", total_comments, page + 1)


asyncio.run(main())
