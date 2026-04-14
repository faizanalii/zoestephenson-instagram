from __future__ import annotations

from typing import Any

from src.comment_scraper.orchestrator import run


async def find_comment(post_url: str, username: str, source_queue: str | None = None) -> Any:
    """
    Entry point that returns matching comment model or None for a post URL and username.
    Args:
        post_url: The URL of the Instagram post to search comments for
        username: The Instagram username to find in the comments
    Returns:
        A CommentStats object if a matching comment is found, or None if not found or an
    """

    return await run(post_url=post_url, username=username, source_queue=source_queue)
