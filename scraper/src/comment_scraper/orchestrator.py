from __future__ import annotations

import importlib
import logging
import sys
from pathlib import Path
from typing import Any

from src.comment_scraper.instagram_client import fetch_page_requirements, paginate_and_search
from src.comment_scraper.queue_manager import RedisQueueManager
from src.comment_scraper.utils import get_random_proxy, normalize_post_url, search_comment
from src.models import CommentStats
from src.supabase_client import get_first_comments

MODULE_DIR = Path(__file__).resolve().parent
DEBUGGING_DIR = MODULE_DIR.parent
WORKSPACE_DIR = DEBUGGING_DIR.parent
MAX_PAGINATION_RETRIES: int = 5
if str(DEBUGGING_DIR) not in sys.path:
    sys.path.insert(0, str(DEBUGGING_DIR))
if str(WORKSPACE_DIR) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_DIR))


def _load_get_comment_from_db(post_url: str) -> list[dict[str, Any]] | None:
    """
    Loads the existing search_comment function from user utility modules.
    Args:
        post_url: The post URL to search comments for,
        used for logging and potential future extensions.
    Returns:
        A callable search_comment function that takes a list of comments
        and a username and returns a matching comment or None.
    """

    return get_first_comments(post_url)


def _load_redis_client_module() -> Any:
    """Loads redis_client module used for queue and account-cookie operations."""

    try:
        return importlib.import_module("redis_client")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("Unable to import redis_client module.") from exc


async def run(
    post_url: str,
    username: str,
    source_queue: str | None = None,
) -> CommentStats | int | None:
    """Runs the DB-first then pagination fallback pipeline and returns found comment or None."""

    normalized_post_url = normalize_post_url(post_url)
    logging.info(f"Starting comment search for {username} on {normalized_post_url}")
    first_comments: list[dict[str, Any]] | None = _load_get_comment_from_db(
        post_url=normalized_post_url
    )
    logging.info(
        f"Loaded {len(first_comments) if first_comments else 0} comments from DB for {normalized_post_url}"
    )
    # Search in the first comments if the comments are available
    if first_comments is not None:
        comment: CommentStats | None = await search_comment(
            comments=first_comments, username=username, post_url=post_url
        )

        if comment:
            return comment

    logging.info(f"No comment found in DB for {username} on {post_url}, proceeding to pagination.")

    # TODO: Work on redis client module, it shoudl be direct import not like this
    redis_client_module = _load_redis_client_module()

    logging.info(f"Loaded redis client module: {redis_client_module}")
    queue_manager = RedisQueueManager(redis_client_module)

    task = await queue_manager.get_task_state(normalized_post_url, username)

    if source_queue:
        task.source_queue = source_queue

    logging.info(f"Loaded task state for {username} on {normalized_post_url}: {task}")

    if task.retry_count >= MAX_PAGINATION_RETRIES:
        logging.info(
            "Retries exhausted (%s/%s) for %s on %s — giving up.",
            task.retry_count,
            MAX_PAGINATION_RETRIES,
            username,
            normalized_post_url,
        )
        await queue_manager.clear_task_state(task)
        return None

    if not queue_manager.ensure_retry_gate(task):
        return max(1, task.retry_count)

    logging.info(f"Passed retry gate for {username} on {normalized_post_url}")
    account = await queue_manager.get_account_cookies(task)

    task.account_id = account.account_id

    # TODO:use the same proxy for the retries of the same task
    proxy: str = task.proxy if task.proxy else await get_random_proxy()

    # TODO: If the page requirements already exist in the persisted variables use them
    page_requirements = await fetch_page_requirements(normalized_post_url, proxy=proxy)

    logging.info(f"Fetched page requirements for {normalized_post_url}: {page_requirements}")

    return await paginate_and_search(
        task=task,
        account=account,
        proxy=proxy,
        page_requirements=page_requirements,
        queue_manager=queue_manager,
    )
