"""Local cookie persistence for account sessions."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from src.account_loader import Account
from src.settings import COOKIE_STORAGE_DIR

logger = logging.getLogger(__name__)


def _cookies_dir() -> Path:
    path = Path(COOKIE_STORAGE_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cookie_path(account: Account) -> Path:
    safe_email = account.email.replace("@", "_at_").replace("/", "_")
    return _cookies_dir() / f"{account.account_id}_{safe_email}.json"


def load_account_cookies(account: Account) -> list[dict]:
    """Load a previously persisted cookie jar for an account."""
    path = _cookie_path(account)
    if not path.exists():
        return []

    try:
        data = json.loads(path.read_text())
    except Exception:
        logger.exception("Failed to read cookie jar for %s", account.email)
        return []

    if not isinstance(data, list):
        logger.warning("Cookie jar for %s is not a list. Ignoring.", account.email)
        return []

    cookies = [item for item in data if isinstance(item, dict)]
    logger.info("Loaded %s persisted cookies for %s", len(cookies), account.email)
    return cookies


def save_account_cookies(account: Account, cookies: list[dict]) -> None:
    """Persist the raw Selenium cookie jar for an account."""
    if not cookies:
        return

    path = _cookie_path(account)
    path.write_text(json.dumps(cookies, indent=2, sort_keys=True))
    logger.info("Saved %s cookies for %s to %s", len(cookies), account.email, path)
