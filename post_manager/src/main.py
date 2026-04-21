"""
Main entry point for the post manager application. Initializes the scraper
and starts the worker loop.
"""

import logging

from src.google_sheets import get_comment_data
from src.models import Post
from src.post_sorting import get_post
from src.redis_client import (
    get_all_post_urls_in_processing_queue,
    get_video_queue_length,
    is_video_url_in_queue,
    push_posts_to_queue,
)
from src.settings import (
    KEY_VIDEO_QUEUE_40,
    KEY_VIDEO_QUEUE_120,
    KEY_VIDEO_QUEUE_240,
    KEY_VIDEO_QUEUE_REST,
)
from src.supabase_client import (
    bulk_upsert_posts,
    get_existing_post_urls,
    get_urls_where_comment_not_found,
    last_comment_update_urls,
    push_error_post,
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

# TODO: No need to use account cookies for the reels as the first_comments never show up
# However, for the posts they should be used as the page does return the comments on first page


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

    # ==========================================================================
    # PROCESS NEW & EXISTING VIDEOS - Push to Redis queue with stored data
    # ==========================================================================
    # Here we can push both existing and new comments to the Redis processing queue
    # since the worker will handle upserting to Supabase and we have already filtered out
    # the discarded URLs.
    logging.info("Adding posts to processing queue...")
    logging.info("Existing posts to add to queue: %d", len(existing_comments))
    logging.info("New posts to add to queue: %d", len(new_comments))

    unexisting_posts: list[Post] = []
    existing_posts: list[Post] = []
    all_comments = existing_comments + new_comments

    queue_list_40: list[Post] = []
    queue_list_120: list[Post] = []
    queue_list_240: list[Post] = []
    queue_list_rest: list[Post] = []

    for comment in all_comments:
        post_url: str = comment.get("post_url", "")
        username: str = comment.get("username", "")

        if not post_url or not username:
            continue

        # Check if the post is already in the processing queue to avoid duplicates
        # Check if the post is already in any of the queues
        # Skip if already in any queue
        already_in_queue = False

        for queue_key in [
            KEY_VIDEO_QUEUE_40,
            KEY_VIDEO_QUEUE_120,
            KEY_VIDEO_QUEUE_240,
            KEY_VIDEO_QUEUE_REST,
        ]:
            if await is_video_url_in_queue(post_url, queue_key):
                already_in_queue = True
                break

        if already_in_queue:
            logger.info(f"Post already in queue: {post_url}")
            continue

        logger.info(f"Adding existing post to processing queue: {post_url}")

        # Get the post data again to ensure we have the latest media_id
        #  and hmac_claim (in case they were missing before)
        try:
            post: Post = await get_post(post_url, username)
            existing_posts.append(post)

        except Exception as e:
            logger.error(f"Error occurred while fetching post data for {post_url}: {e}")
            # pUsh an error post to Supabase for tracking
            push_error_post(post_url=post_url, error_message=str(e))
            continue

        if not post.media_id or not post.hmac_claim:
            logger.warning(f"Post {post_url} is missing media_id or hmac_claim.")
            # You could choose to add it to a separate queue for
            # reprocessing or handle it differently
            unexisting_posts.append(post)
            continue  # For now, we just skip it

        # If not in any queue, push to the appropriate queue based on comment
        # count or other criteria
        # For example, you could push to different queues based on comment count:
        if post.comment_count is not None:
            if post.comment_count <= 40:
                queue_list_40.append(post)
            elif post.comment_count <= 120:
                queue_list_120.append(post)
            elif post.comment_count <= 240:
                queue_list_240.append(post)
            else:
                queue_list_rest.append(post)

    # Now push the lists to Redis
    if queue_list_40:
        await push_posts_to_queue(queue_list_40, KEY_VIDEO_QUEUE_40)
    if queue_list_120:
        await push_posts_to_queue(queue_list_120, KEY_VIDEO_QUEUE_120)
    if queue_list_240:
        await push_posts_to_queue(queue_list_240, KEY_VIDEO_QUEUE_240)
    if queue_list_rest:
        await push_posts_to_queue(queue_list_rest, KEY_VIDEO_QUEUE_REST)

    # Upsert the videos to Supabase to ensure we have the latest data stored, including
    # any new media_id or hmac_claim
    # This will also update the updated_at timestamp so we know when it was last processed
    if existing_posts:
        logging.info(f"Upserting {len(existing_posts)} existing posts to Supabase..")
        bulk_upsert_posts(existing_posts)

    # Final summary
    for queue_key in [
        KEY_VIDEO_QUEUE_40,
        KEY_VIDEO_QUEUE_120,
        KEY_VIDEO_QUEUE_240,
        KEY_VIDEO_QUEUE_REST,
    ]:
        queue_length = await get_video_queue_length(queue_key=queue_key)
        logger.info(f"Queue {queue_key}: {queue_length} videos waiting")

    logger.info("=" * 50)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
