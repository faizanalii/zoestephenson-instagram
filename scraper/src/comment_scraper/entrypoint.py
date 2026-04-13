from __future__ import annotations

import asyncio
from typing import Any

from .orchestrator import run


def find_comment(post_url: str, username: str) -> Any:
    """Entry point that returns matching comment model or None for a post URL and username."""

    return asyncio.run(run(post_url=post_url, username=username))
