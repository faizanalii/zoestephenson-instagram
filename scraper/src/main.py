"""
Instagram Comment Scraper - Main Entry Point
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
from src.google_sheets.output_sheets import flush_buffer
from src.models import (
    CommentNotFound,
    CommentStats,
    Post,
    ScrapeResult,
    ScrapeStatus,
    UpdateCommentCheckDay,
)
from src.redis_client import (
    add_url_to_processing_queue,
    delete_processing_task,
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

    logger.info("Starting Instagram Comment Scraper...")

    # Get initial queue length
    queue_length = await get_video_queue_length(queue_key=queue_key)
    logger.info(f"Videos in queue: {queue_length} for queue {queue_key}")

    if queue_length == 0:
        logger.info(f"No videos in queue for queue {queue_key}. Exiting.")
        return

    processed_count = 0
    found_count = 0
    error_count = 0

    # Track found comments whose DB upserts are pending a successful Sheets flush.
    pending_found_comments: dict[str, CommentStats] = {}
    db = SupabaseDB()
    # Process videos until queue is empty
    while not await is_video_queue_empty(queue_key=queue_key):
        # Pop next video from queue
        post_job: Post | None = await pop_post_from_queue(queue_key=queue_key)

        if not post_job:
            break

        # Add to processing queue as soon as we start handling this job.
        await add_url_to_processing_queue(post_job)

        should_clear_task_state = False

        try:
            scrape_result: ScrapeResult = await find_comment(
                post=post_job,
                source_queue=queue_key,
            )

            processed_count += 1
            # If the comment is not found then update the DB
            if scrape_result.status == ScrapeStatus.NOT_FOUND:
                logger.info(
                    "Comment not found for %s on video %s",
                    post_job.username,
                    post_job.post_url,
                )
                not_found_ok = db.comment_not_found(
                    CommentNotFound(post_url=post_job.post_url, comment_exists=False)
                )
                if not not_found_ok:
                    logger.warning(
                        "Comment-not-found DB update failed for %s; re-queuing.",
                        post_job.post_url,
                    )
                    await push_post_to_queue(post_job, queue_key=queue_key)
                    error_count += 1
                else:
                    await remove_url_from_processing_queue(post_job.post_url)
                    await delete_processing_task(post_job.post_url, post_job.username)

            elif scrape_result.status == ScrapeStatus.FOUND:
                comment: CommentStats | None = scrape_result.comment

                if not comment:
                    logger.error(
                        "ScrapeResult status is FOUND but comment is None for %s",
                        post_job.post_url,
                    )
                    await remove_url_from_processing_queue(post_job.post_url)
                    continue

                found_count += 1
                logger.info(f"Found comment for {post_job.username} on video {post_job.post_url}")
                logger.info(f"  Likes: {comment.likes}, Replies: {comment.reply_count}")

                # Push comment to Google Sheets buffer
                # sheets_ok = await push_comment_data(comment_stats=comment)
                sheets_ok = True

                if sheets_ok:
                    # Keep only one pending result per post_url to stay idempotent.
                    pending_found_comments[post_job.post_url] = comment
                    should_clear_task_state = True
                    await remove_url_from_processing_queue(post_job.post_url)

                else:
                    logger.error(
                        "Sheets push failed for video %s. Supabase NOT updated — re-queuing.",
                        post_job.post_url,
                    )
                    await push_post_to_queue(post_job, queue_key=queue_key)
                    error_count += 1

            elif scrape_result.status == ScrapeStatus.RETRY:
                # entry_point.py already re-queued the post with an incremented
                # retry_count. We just track it here.
                logger.warning(
                    "Retry scheduled for post=%s username=%s retry_count=%s/%s",
                    post_job.post_url,
                    post_job.username,
                    scrape_result.retry_count,
                    post_job.retry_count,
                )
                error_count += 1

            elif scrape_result.status == ScrapeStatus.ERROR:
                logger.error(
                    "Post dead-lettered: post=%s reason=%s",
                    post_job.post_url,
                    scrape_result.error,
                )
                error_count += 1

            # Add a small delay between requests
            await asyncio.sleep(random.uniform(0.5, 1.5))

        except Exception:
            logger.exception(
                "Unexpected error processing post=%s username=%s queue=%s",
                post_job.post_url,
                post_job.username,
                queue_key,
            )
            error_count += 1

            if should_clear_task_state:
                await delete_processing_task(post_job.post_url, post_job.username)

    # Flush any remaining buffered rows to Google Sheets
    flush_ok = flush_buffer()
    if flush_ok and pending_found_comments:
        logger.info(f"Committing {len(pending_found_comments)} pending Supabase updates...")
        for post_url, comment in pending_found_comments.items():
            # Retry the DB write in-place rather than re-scraping the whole post.
            # The comment is already in memory; only the DB call needs to succeed.
            db_ok = False
            for attempt in range(1, 4):  # up to 3 attempts
                stats_ok = db.insert_found_comment(comment)
                status_ok = db.update_comment_update_day(UpdateCommentCheckDay(post_url=post_url))
                if stats_ok and status_ok:
                    db_ok = True
                    break
                logger.warning(
                    "Supabase commit attempt %s/3 failed for post=%s. Retrying...",
                    attempt,
                    post_url,
                )
                await asyncio.sleep(2**attempt)  # 2s, 4s, 8s

            if not db_ok:
                logger.error(
                    "Supabase commit exhausted retries for post=%s. Re-queueing for next cycle.",
                    post_url,
                )
                await push_post_to_queue(
                    Post(post_url=post_url, username=comment.username),
                    queue_key=queue_key,
                )
                error_count += 1

        pending_found_comments.clear()

    elif not flush_ok:
        logger.error(
            f"Final Sheets flush failed — {len(pending_found_comments)} "
            "Supabase updates skipped; videos will be re-processed next cycle."
        )

        for post_url, comment in pending_found_comments.items():
            await push_post_to_queue(
                Post(post_url=post_url, username=comment.username),
                queue_key=queue_key,
            )
            error_count += 1

        pending_found_comments.clear()

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
