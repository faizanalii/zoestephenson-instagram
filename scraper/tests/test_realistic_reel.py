"""Realistic end-to-end test: cookie-free scraper on a reel, searching for a specific username."""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("test_realistic")

from src.comment_scraper import find_comment
from src.comment_scraper.post_page import _is_reel_url
from src.models import Post, ScrapeStatus

REEL_URL = "https://www.instagram.com/reel/DVMRX9wjo09/"
TARGET_USERNAME = "arlaprotein"


async def main():
    post = Post(
        post_url=REEL_URL,
        username=TARGET_USERNAME,
        first_comments=[],  # start fresh — no cache
    )

    logger.info("=" * 60)
    logger.info("REALISTIC TEST")
    logger.info("  URL:      %s", REEL_URL)
    logger.info("  Username: %s", TARGET_USERNAME)
    logger.info("  Is reel:  %s", _is_reel_url(REEL_URL))
    logger.info("=" * 60)

    result = await find_comment(post=post, source_queue="test")

    logger.info("=" * 60)
    logger.info("RESULT")
    logger.info("  Status:      %s", result.status)
    logger.info("  Post URL:    %s", result.post_url)
    logger.info("  Username:    %s", result.username)

    if result.comment:
        c = result.comment
        logger.info("  Comment text:    %s", c.text[:100] if c.text else "(none)")
        logger.info("  Likes:           %s", c.likes)
        logger.info("  Reply count:     %s", c.reply_count)
        logger.info("  Comment ID:      %s", c.comment_id)
        logger.info("  Date of comment: %s", c.date_of_comment)
    else:
        logger.info("  Comment:     None")
        if result.status == ScrapeStatus.NOT_FOUND:
            logger.info("  → Comment by @%s was NOT found on this post", TARGET_USERNAME)
        elif result.status == ScrapeStatus.RETRY:
            logger.info("  → Post was re-queued (reason: %s)", result.error)
        elif result.status == ScrapeStatus.ERROR:
            logger.info("  → Dead-lettered (reason: %s)", result.error)

    logger.info("  Error:       %s", result.error)
    logger.info("  Retry count: %s", result.retry_count)
    logger.info("=" * 60)

    return result


if __name__ == "__main__":
    asyncio.run(main())
