"""Test post_manager cookie-free extraction on a reel and a post."""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("test_pm")

from src.post_sorting import get_post, _is_reel_url

REEL_URL = "https://www.instagram.com/reel/DS2SjGyjXmM/"
POST_URL = "https://www.instagram.com/p/DW4V3knk2Jb/"


async def test_url(label: str, url: str):
    logger.info("=" * 60)
    logger.info("TEST: %s", label)
    logger.info("  URL:     %s", url)
    logger.info("  Is reel: %s", _is_reel_url(url))

    post = await get_post(post_url=url, username="test_user")

    logger.info("RESULT for %s:", label)
    logger.info("  post_url:        %s", post.post_url)
    logger.info("  media_id:        %s", post.media_id)
    logger.info("  hmac_claim:      %s...", (post.hmac_claim or "")[:50])
    logger.info("  comment_count:   %s", post.comment_count)
    logger.info("  has_next_comments: %s", post.has_next_comments)
    logger.info("  first_comments:  %d edges", len(post.first_comments or []))
    logger.info("  post_exists:     %s", post.post_exists)
    logger.info("  retry_count:     %s", post.retry_count)

    if post.post_exists:
        logger.info("  >>> SUCCESS: Post data extracted correctly")
    else:
        logger.warning("  >>> PARTIAL: Missing required fields (media_id or hmac_claim)")

    logger.info("")
    return post


async def main():
    await test_url("REEL", REEL_URL)
    await test_url("POST", POST_URL)


if __name__ == "__main__":
    asyncio.run(main())
