"""
Account loader — reads accounts.txt and pairs each account with a proxy.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from pathlib import Path

from src.settings import ACCOUNTS_FILE, PROXY_COUNTRIES, PROXY_TEMPLATE

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Account:
    email: str
    password: str
    proxy: str


def load_accounts() -> list[Account]:
    """Parse accounts.txt and assign each account a random country proxy."""
    path = Path(ACCOUNTS_FILE)
    if not path.exists():
        raise FileNotFoundError(f"Accounts file not found: {path.resolve()}")

    accounts: list[Account] = []
    for line_no, raw_line in enumerate(path.read_text().splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 2 or not parts[0] or not parts[1]:
            logger.warning("Skipping malformed line %s in %s", line_no, ACCOUNTS_FILE)
            continue

        country = random.choice(PROXY_COUNTRIES)
        proxy = PROXY_TEMPLATE.replace("{COUNTRY}", country)
        accounts.append(Account(email=parts[0], password=parts[1], proxy=proxy))

    logger.info("Loaded %s accounts from %s", len(accounts), ACCOUNTS_FILE)
    return accounts
