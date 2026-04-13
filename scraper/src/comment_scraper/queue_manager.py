from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from typing import Any

from src.comment_scraper.utils import (
    build_retry_at,
    random_retry_delay_seconds,
    should_process_retry,
)
from src.models import AccountCookies, TaskState


class RedisQueueManager:
    """Provides a thin adapter over redis_client helpers for task and cookie operations."""

    def __init__(self, redis_client_module: Any) -> None:
        """Initializes queue manager with a loaded redis_client module."""

        self.redis_client = redis_client_module

    def _call_first(self, method_names: list[str], *args: Any, **kwargs: Any) -> Any:
        """Calls the first available method name from redis_client with provided args."""

        for method_name in method_names:
            method = getattr(self.redis_client, method_name, None)
            if callable(method):
                return method(*args, **kwargs)
        return None

    def get_task_state(self, post_url: str, username: str) -> TaskState:
        """Loads existing processing task state for a post/username or returns default state."""

        payload = self._call_first(
            [
                "get_processing_task",
                "get_task_state",
                "get_task",
                "peek_processing_queue_task",
            ],
            post_url,
            username,
        )

        if payload is None:
            return TaskState(post_url=post_url, username=username)

        if isinstance(payload, str):
            payload = json.loads(payload)

        retry_at_raw = payload.get("retry_at")
        retry_at = None
        if retry_at_raw:
            try:
                retry_at = datetime.fromisoformat(retry_at_raw)
            except ValueError:
                retry_at = None

        return TaskState(
            post_url=payload.get("post_url", post_url),
            username=payload.get("username", username),
            account_id=payload.get("account_id"),
            requeued=bool(payload.get("requeued", False)),
            retry_at=retry_at,
            variables=payload.get("variables"),
        )

    def ensure_retry_gate(self, task: TaskState) -> bool:
        """
        Checks retry timing gate for requeued tasks and defers task
        when retry time is not reached.
        """

        if should_process_retry(task.retry_at):
            return True

        self._call_first(
            ["push_processing_task", "enqueue_processing_task", "requeue_processing_task"],
            self.task_to_payload(task),
        )
        return False

    def get_account_cookies(self, task: TaskState) -> AccountCookies:
        """Fetches cookies for the bound account or allocates a fresh account+cookies pair."""

        if task.account_id:
            cookies = self._call_first(
                [
                    "get_cookies_for_account",
                    "get_account_cookies",
                    "fetch_cookies",
                ],
                task.account_id,
            )
            if isinstance(cookies, dict) and cookies:
                return AccountCookies(account_id=task.account_id, cookies=cookies)

        account_payload = self._call_first(
            [
                "pop_account_with_cookies",
                "get_next_account_with_cookies",
                "get_processing_account",
            ]
        )
        if isinstance(account_payload, str):
            account_payload = json.loads(account_payload)

        if not isinstance(account_payload, dict):
            raise RuntimeError(
                "No account cookies available from redis_client. "
                "Expected one of: pop_account_with_cookies/get_next_account_with_cookies/get_processing_account"
            )

        account_id = account_payload.get("account_id")
        cookies = account_payload.get("cookies")
        if not account_id or not isinstance(cookies, dict) or not cookies:
            raise RuntimeError("Invalid account cookies payload returned by redis_client.")

        return AccountCookies(account_id=str(account_id), cookies=cookies)

    def requeue_task(self, task: TaskState, variables: dict[str, Any] | None = None) -> None:
        """
        Requeues a task into processing queue with randomized retry timer
        and latest cursor state.
        """

        delay_seconds = random_retry_delay_seconds()
        updated = TaskState(
            post_url=task.post_url,
            username=task.username,
            account_id=task.account_id,
            requeued=True,
            retry_at=build_retry_at(delay_seconds),
            variables=variables if variables is not None else task.variables,
        )
        payload = self.task_to_payload(updated)

        result = self._call_first(
            [
                "push_processing_task",
                "enqueue_processing_task",
                "requeue_processing_task",
                "put_processing_task",
            ],
            payload,
        )

        if result is None:
            raise RuntimeError(
                "Unable to requeue task: redis_client is missing a supported enqueue method."
            )

    def task_to_payload(self, task: TaskState) -> dict[str, Any]:
        """Converts TaskState to queue payload format used by processing queue."""

        payload = asdict(task)
        if task.retry_at is not None:
            payload["retry_at"] = task.retry_at.isoformat()
        return payload
