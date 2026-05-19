"""Debug: raw GraphQL response for DWeD5LnjJt4"""

import asyncio, json, logging, sys, random
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("raw_test")

from src.comment_scraper.post_page import get_post_page
from src.comment_scraper.utils import PostPageParser
from src.comment_scraper.ig_query_client import run_graphql_query, build_query_data, build_headers
from src.settings import PROXY, PROXY_COUNTRIES_LIST
from curl_cffi import requests as curl_requests

REEL_URL = "https://www.instagram.com/reel/DWeD5LnjJt4/"
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

    logger.info("media_id=%s", media_id)
    logger.info("cursor_raw=%s", repr(cursor))
    logger.info("csrf=%s app_id=%s lsd=%s dtsg=%s...",
                header.csrf_token, header.app_id,
                (header.lsd_token or "")[:20],
                (header.dtsg_token or "")[:20])

    # Try with cursor=None first (fresh start)
    for label, cur in [
        ("cursor=None (empty)", None),
        ("cursor=raw_string", cursor),
        ("cursor=json_string('{}')", "{}"),
    ]:
        logger.info("--- Trying %s ---", label)
        headers = await build_headers(
            csrf_token=header.csrf_token,
            app_id=header.app_id,
            post_id=POST_ID,
            lsd_token=header.lsd_token,
            hmac_claim=header.hmac_claim,
        )
        data = await build_query_data(
            media_id=media_id,
            cursor=cur,
            fb_dtsg=header.dtsg_token,
            lsd_token=header.lsd_token,
        )

        # Make request directly so we can see full response
        page_proxy = PROXY.format(COUNTRY=random.choice(PROXY_COUNTRIES_LIST))
        resp = curl_requests.post(
            "https://www.instagram.com/graphql/query",
            impersonate="chrome142",
            headers=headers,
            data=data,
            proxy=page_proxy,
            timeout=30,
        )

        logger.info("status=%s content-type=%s", resp.status_code, resp.headers.get("content-type"))

        try:
            body = resp.json()
            errors = body.get("errors", [])
            if errors:
                logger.warning("  errors: %s", json.dumps(errors[0], indent=2)[:500])

            data_block = body.get("data", {})
            logger.info("  data keys: %s", list(data_block.keys())[:5])

            # Find the comments connection
            for key in data_block:
                val = data_block[key]
                if isinstance(val, dict):
                    edges = val.get("edges", [])
                    page_info = val.get("page_info", {})
                    logger.info("  %s -> edges=%d has_next=%s end_cursor=%s",
                               key[:60], len(edges), page_info.get("has_next_page"),
                               bool(page_info.get("end_cursor")))

                    for i, edge in enumerate(edges[:3]):
                        node = edge.get("node", {})
                        uname = node.get("user", {}).get("username", "?")
                        text = node.get("text")
                        gif = node.get("giphy_media_info")
                        logger.info("    [%d] @%s text=%s gif=%s pk=%s",
                                   i, uname, repr(text)[:40], bool(gif), node.get("pk", "?"))
        except Exception:
            logger.info("  RAW (first 800): %s", resp.text[:800])

        logger.info("")


asyncio.run(main())
