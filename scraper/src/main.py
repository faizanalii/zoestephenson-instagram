"""
TikTok Comment Scraper - Main Entry Point
==========================================

Processes videos from Redis queue until empty.
For each video:
    1. Get tokens from Redis
    2. Build API URL with tokens
    3. Scrape comments and search for target user
    4. Update cursor in Supabase on success
    5. Re-queue on error for retry
"""

import asyncio
import logging
import random

from src.comment_scraper import find_comment
from src.google_sheets.output_sheets import flush_buffer, push_comment_data
from src.models import CommentNotFound, CommentStats, Post, UpdateCommentCheckDay
from src.redis_client import (
    add_url_to_processing_queue,
    get_video_queue_length,
    is_redis_connected,
    is_video_queue_empty,
    pop_post_from_queue,
    push_post_to_queue,
    remove_url_from_processing_queue,
)
from src.settings import (
    KEY_VIDEO_QUEUE_40,
    KEY_VIDEO_QUEUE_120,
    KEY_VIDEO_QUEUE_240,
    KEY_VIDEO_QUEUE_REST,
)
from src.supabase_client import SupabaseDB

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("scraper.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


async def main(queue_key: str) -> None:
    """
    Main function for the scraper module.

    Continuously processes videos from Redis queue until empty.
    """
    # Check Redis connection
    if not await is_redis_connected():
        logger.error("Redis is not connected. Check REDIS_HOST, REDIS_PORT, REDIS_PASSWORD.")
        return

    logger.info("Starting TikTok Comment Scraper...")

    # Get initial queue length
    queue_length = await get_video_queue_length(queue_key=queue_key)
    logger.info(f"Videos in queue: {queue_length} for queue {queue_key}")

    if queue_length == 0:
        logger.info(f"No videos in queue for queue {queue_key}. Exiting.")
        return

    processed_count = 0
    found_count = 0
    error_count = 0

    # Track video_ids whose Supabase update is pending a Sheets batch flush
    pending_supabase_updates: list[str] = []

    # Process videos until queue is empty
    while not await is_video_queue_empty(queue_key=queue_key):
        # Pop next video from queue
        post_job: Post | None = await pop_post_from_queue(queue_key=queue_key)

        if not post_job:
            break

        # Add to processing queue
        await add_url_to_processing_queue(post_job)

        try:
            result = await find_comment(post_url=post_job.post_url, username=post_job.username)

            processed_count += 1

            if isinstance(result, CommentStats):
                found_count += 1
                logger.info(f"Found comment for {post_job.username} on video {post_job.post_url}")
                logger.info(f"  Likes: {result.likes}, Replies: {result.reply_count}")

                # Push comment to Google Sheets buffer
                sheets_ok = await push_comment_data(result)

                # TODO: Also add the same to the Supabase table, 'instagram_stats'

                if sheets_ok:
                    # Add the exact same result to the Supabase also
                    # Row is either buffered or batch-flushed successfully.
                    # Queue the Supabase update; it will be committed when we
                    # know the batch reached the sheet.
                    pending_supabase_updates.append(post_job.post_url)

                else:
                    logger.error(
                        f"  Sheets push failed for video {post_job.post_url}. "
                        "Supabase NOT updated — video will be re-processed next cycle."
                    )

                # Remove from processing queue
                await remove_url_from_processing_queue(post_job.post_url)

            # For the requeing we can maybe use the same redis list and check it
            # Either it's for the first time or it's a retry, we can check
            elif isinstance(result, int):
                pass
                # TODO: Handle the case where the comment was not found but we want to track the number of retries or mark it in Supabase
                # Comment not found and failure/restart count, retry where it's left off
            # TODO: If result is None then mark comment not found in Supabase
            # Supabase update for comment not found is not working as expected
            else:
                logger.info(
                    f"- Comment not found for {post_job.username} on video {post_job.post_url}"
                )

                db = SupabaseDB()
                # Update last comment check day in Supabase
                db.comment_not_found(
                    CommentNotFound(video_id=post_job.post_url, comment_exists=False)
                )
                # Remove from processing queue
                await remove_url_from_processing_queue(post_job.post_url)

            # Add a small delay between requests
            await asyncio.sleep(random.uniform(0.5, 1.5))

        except Exception as e:
            logger.error(f"Unexpected error processing video {post_job.post_url}: {e}")

            # Re-queue the video for retry
            await push_post_to_queue(post_job, queue_key=queue_key)
            error_count += 1

            # Remove from processing queue
            await remove_url_from_processing_queue(post_job.post_url)

    # Flush any remaining buffered rows to Google Sheets
    flush_ok = flush_buffer()
    if flush_ok and pending_supabase_updates:
        logger.info(f"Committing {len(pending_supabase_updates)} pending Supabase updates...")
        db = SupabaseDB()
        for vid in pending_supabase_updates:
            db.update_comment_update_day(UpdateCommentCheckDay(video_id=vid))
        pending_supabase_updates.clear()
    elif not flush_ok:
        logger.error(
            f"Final Sheets flush failed — {len(pending_supabase_updates)} "
            "Supabase updates skipped; videos will be re-processed next cycle."
        )
        pending_supabase_updates.clear()

    # Final summary
    logger.info("=" * 50)
    logger.info(f"Scraping complete for queue: {queue_key}")
    logger.info(f"  Total processed: {processed_count}")
    logger.info(f"  Comments found: {found_count}")
    logger.info(f"  Errors (re-queued): {error_count}")
    logger.info("=" * 50)


if __name__ == "__main__":
    while True:
        for queue_key in [
            KEY_VIDEO_QUEUE_40,
            KEY_VIDEO_QUEUE_120,
            KEY_VIDEO_QUEUE_240,
            KEY_VIDEO_QUEUE_REST,
        ]:
            logger.info(f"Checking queue: {queue_key}")
            asyncio.run(main(queue_key=queue_key))

            logger.info(f"Finished processing queue: {queue_key}")
            # Small delay between queue checks
            asyncio.run(asyncio.sleep(5))
        # Delay before next full cycle through queues
        logger.info("Waiting before next queue cycle...")
        asyncio.run(asyncio.sleep(100))
