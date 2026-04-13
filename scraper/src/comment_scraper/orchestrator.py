from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any, Callable

from .instagram_client import fetch_page_requirements, paginate_and_search
from .queue_manager import RedisQueueManager
from .utils import normalize_comment_list, normalize_post_url

MODULE_DIR = Path(__file__).resolve().parent
DEBUGGING_DIR = MODULE_DIR.parent
WORKSPACE_DIR = DEBUGGING_DIR.parent

if str(DEBUGGING_DIR) not in sys.path:
    sys.path.insert(0, str(DEBUGGING_DIR))
if str(WORKSPACE_DIR) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_DIR))


def _load_search_comment() -> Callable[[list[dict[str, Any]], str], Any]:
    """Loads the existing search_comment function from user utility modules."""

    candidate_modules = ["utils", "Debugging.utils"]

    for module_name in candidate_modules:
        try:
            module = importlib.import_module(module_name)
        except Exception:  # noqa: BLE001
            continue
        func = getattr(module, "search_comment", None)
        if callable(func):
            return func

    raise RuntimeError("search_comment function was not found in expected utils modules.")


def _load_get_comment_from_db() -> Callable[[str], Any]:
    """Loads the existing Supabase accessor function for first comments by post URL."""

    try:
        module = importlib.import_module("supabase_client")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("Unable to import supabase_client module.") from exc

    func = getattr(module, "get_comment_from_db", None)
    if not callable(func):
        raise RuntimeError("supabase_client.get_comment_from_db is missing or not callable.")

    return func


def _load_redis_client_module() -> Any:
    """Loads redis_client module used for queue and account-cookie operations."""

    try:
        return importlib.import_module("redis_client")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("Unable to import redis_client module.") from exc


async def run(post_url: str, username: str) -> Any:
    """Runs the DB-first then pagination fallback pipeline and returns found comment or None."""

    normalized_post_url = normalize_post_url(post_url)
    search_comment = _load_search_comment()
    get_comment_from_db = _load_get_comment_from_db()
    redis_client_module = _load_redis_client_module()
    queue_manager = RedisQueueManager(redis_client_module)

    first_comments = get_comment_from_db(normalized_post_url)
    found_from_db = search_comment(normalize_comment_list(first_comments), username)
    if found_from_db is not None:
        return found_from_db

    task = queue_manager.get_task_state(normalized_post_url, username)
    if not queue_manager.ensure_retry_gate(task):
        return None

    account = queue_manager.get_account_cookies(task)
    task.account_id = account.account_id

    page_requirements = await fetch_page_requirements(normalized_post_url)
    return await paginate_and_search(
        task=task,
        account=account,
        page_requirements=page_requirements,
        queue_manager=queue_manager,
        search_comment=search_comment,
    )
