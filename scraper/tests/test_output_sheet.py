"""Test Google Sheets output — push a test row."""

import asyncio, logging, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("sheet_test")

from src.google_sheets.output_sheets import push_comment_data, flush_buffer
from src.models import CommentStats


async def main():
    test_comment = CommentStats(
        post_url="https://www.instagram.com/reel/DVZRkipgX4x/",
        username="TEST_USER",
        text="this is a test comment from the scraper pipeline",
        likes=42,
        reply_count=3,
        date_of_comment="2026-05-19",
    )

    logger.info("Pushing test comment to output sheet...")
    ok = await push_comment_data(comment_stats=test_comment)
    logger.info("push_comment_data returned: %s", ok)

    logger.info("Flushing remaining buffer...")
    flush_ok = flush_buffer()
    logger.info("flush_buffer returned: %s", flush_ok)

    if ok and flush_ok:
        logger.info("SUCCESS: Google Sheets output works!")
    else:
        logger.error("FAILED: Check credentials and sheet permissions.")


if __name__ == "__main__":
    asyncio.run(main())
