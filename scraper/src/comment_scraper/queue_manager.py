from __future__ import annotations

import json
from asyncio import iscoroutine
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from src.comment_scraper.utils import (
    build_retry_at,
    random_retry_delay_seconds,
    should_process_retry,
)
from src.models import AccountCookies, TaskState
from src.settings import MAX_PAGINATION_RETRIES


class RedisQueueManager:
    """Provides a thin adapter over redis_client helpers for task and cookie operations."""

    def __init__(self, redis_client_module: Any) -> None:
        """Initializes queue manager with a loaded redis_client module."""

        self.redis_client = redis_client_module

    async def _call_first(self, method_names: list[str], *args: Any, **kwargs: Any) -> Any:
        """Calls the first available method name from redis_client with provided args."""

        for method_name in method_names:
            method = getattr(self.redis_client, method_name, None)
            if callable(method):
                result = method(*args, **kwargs)
                if iscoroutine(result):
                    return await result
                return result
        return None

    async def get_task_state(self, post_url: str, username: str) -> TaskState:
        """
        Loads existing processing task state for a post/username or returns default state.
        Args:
            post_url: The URL of the TikTok post
            username: The username of the user
        Returns:
            TaskState object with persisted state or default values
        """

        payload = await self._call_first(
            [
                "get_processing_task",
            ],
            post_url,
            username,
        )

        if payload is None:
            return TaskState(post_url=post_url, username=username)

        if isinstance(payload, str):
            payload = json.loads(payload)

        # If the retry is mentioned in the payload
        retry_at_raw = payload.get("retry_at")

        retry_at = None

        if retry_at_raw:
            try:
                retry_at = datetime.fromisoformat(retry_at_raw)
            except ValueError:
                retry_at = None

        last_cursor_at = None

        last_cursor_at_raw = payload.get("last_cursor_at", "")

        if last_cursor_at_raw:
            try:
                last_cursor_at = datetime.fromisoformat(last_cursor_at_raw)

            except ValueError:
                last_cursor_at = None

        return TaskState(
            post_url=payload.get("post_url", post_url),
            username=payload.get("username", username),
            account_id=payload.get("account_id"),
            source_queue=payload.get("source_queue"),
            requeued=bool(payload.get("requeued", False)),
            retry_at=retry_at,
            proxy=payload.get("proxy"),
            variables=payload.get("variables"),
            retry_count=int(payload.get("retry_count", 0)),
            last_cursor_at=last_cursor_at,
            last_error=payload.get("last_error"),
        )

    def ensure_retry_gate(self, task: TaskState) -> bool:
        """
        Checks retry timing gate for requeued tasks and defers task
        when retry time is not reached.
        """

        return should_process_retry(task.retry_at)

    async def get_account_cookies(self, task: TaskState) -> AccountCookies:
        """Fetches cookies for the bound account or allocates a fresh account+cookies pair."""

        if task.account_id:
            cookies = await self._call_first(
                [
                    "get_cookies_for_account",
                ],
                task.account_id,
            )
            if isinstance(cookies, dict) and cookies:
                return AccountCookies(account_id=task.account_id, cookies=cookies)

        account_payload = await self._call_first(
            [
                "get_next_account_with_cookies",
            ]
        )
        if isinstance(account_payload, str):
            account_payload = json.loads(account_payload)

        if not isinstance(account_payload, dict):
            raise RuntimeError(
                "No account cookies available from redis_client. "
                "Expected one of: pop_account_with_cookies/"
                "get_next_account_with_cookies/get_processing_account"
            )

        account_id = account_payload.get("account_id")
        cookies = account_payload.get("cookies")
        if not account_id or not isinstance(cookies, dict) or not cookies:
            raise RuntimeError("Invalid account cookies payload returned by redis_client.")

        return AccountCookies(account_id=str(account_id), cookies=cookies)

    async def requeue_task(
        self,
        task: TaskState,
        variables: dict[str, Any] | None = None,
        failure_reason: str = "unknown",
    ) -> int:
        """
        Requeues a task into processing queue with randomized retry timer
        and latest cursor state.
        """

        next_retry_count = task.retry_count + 1

        if next_retry_count > MAX_PAGINATION_RETRIES:
            return next_retry_count

        delay_seconds = random_retry_delay_seconds()

        updated = TaskState(
            post_url=task.post_url,
            username=task.username,
            account_id=task.account_id,
            source_queue=task.source_queue,
            requeued=True,
            proxy=task.proxy,
            retry_at=build_retry_at(delay_seconds),
            variables=variables if variables is not None else task.variables,
            retry_count=next_retry_count,
            last_cursor_at=datetime.now(UTC),
            last_error=failure_reason,
        )
        payload = self.task_to_payload(updated)

        result = await self._call_first(
            [
                "set_processing_task_state",
            ],
            payload,
        )

        if result in (None, False):
            raise RuntimeError(
                "Unable to requeue task: redis_client is missing a supported enqueue method."
            )

        return next_retry_count

    async def clear_task_state(self, task: TaskState) -> None:
        """Removes persisted retry state for a completed task."""

        await self._call_first(
            ["delete_processing_task", "delete_task_state", "remove_processing_task"],
            task.post_url,
            task.username,
        )

    def task_to_payload(self, task: TaskState) -> dict[str, Any]:
        """Converts TaskState to queue payload format used by processing queue."""

        payload = asdict(task)
        if task.retry_at is not None:
            payload["retry_at"] = task.retry_at.isoformat()
        return payload
