"""
Main entry point for the post manager application. Initializes the scraper
and starts the worker loop.
"""

import logging

from src.google_sheets import get_comment_data
from src.redis_client import get_all_post_urls_in_processing_queue
from src.supabase_client import (
    get_existing_post_urls,
    get_urls_where_comment_not_found,
    last_comment_update_urls,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("video_manager.log"),
        logging.StreamHandler(),
    ],
)

logger = logging.getLogger(__name__)


async def main() -> None:
    """
    Main function to start the post manager application.
    """

    # Example usage of get_comment_data
    comment_data = get_comment_data()

    # Extract all post URLs
    all_post_urls = [c.get("post_url", "") for c in comment_data if c.get("post_url")]

    # Check which posts already exist in Supabase
    logger.info("Checking Supabase for existing posts...")
    existing_urls: set[str] = get_existing_post_urls(all_post_urls)
    logger.info(f"Found {len(existing_urls)} posts already in Supabase")
    logger.info("Separating existing and new posts...")

    # Get URLs where comments were not found previously
    discarded_urls: set[str] = get_urls_where_comment_not_found()
    logger.info(f"Found {len(discarded_urls)} discarded posts in Supabase")

    # Get all the posts where last_comment_check date is today
    already_done_post_urls: set[str] = last_comment_update_urls()
    logger.info(f"Found {len(already_done_post_urls)} already processed posts today")

    # Add the already done URLs to discarded URLs
    discarded_urls.update(already_done_post_urls)

    # Also check here if the post_urls are not in processing queues in Redis
    processing_queue: set[str] = await get_all_post_urls_in_processing_queue()
    logger.info(f"Found {len(processing_queue)} posts currently in processing queue")
    # Add processing queue URLs to discarded URLs
    discarded_urls.update(processing_queue)

    # Separate into existing and new
    existing_comments = [c for c in comment_data if c.get("post_url") in existing_urls]
    # remove the discarded URLs from existing comments
    existing_comments = [c for c in existing_comments if c.get("post_url") not in discarded_urls]
    # Get only new comments that are not in existing URLs and not in discarded URLs
    new_comments = [c for c in comment_data if c.get("post_url") not in existing_urls]
    # Remove discarded URLs from new comments
    new_comments = [c for c in new_comments if c.get("post_url") not in discarded_urls]

    logger.info(f"Existing posts: {len(existing_comments)}, New posts: {len(new_comments)}")

    # TODO: Process existing comments (e.g., update comment counts, check for new comments)
    # Process Videos everyday at 12:00 PM, so we can skip processing existing comments for now


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
