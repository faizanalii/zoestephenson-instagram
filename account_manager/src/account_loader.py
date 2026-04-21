"""Account model helpers for leased Instagram accounts."""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import Any, Mapping

from src.settings import PROXY_COUNTRIES, PROXY_TEMPLATE

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Account:
    account_id: str
    email: str
    password: str
    proxy: str


def build_account(account_id: str, email: str, password: str) -> Account:
    """Build an Account with a randomized proxy assignment."""
    country = random.choice(PROXY_COUNTRIES)
    proxy = PROXY_TEMPLATE.replace("{COUNTRY}", country)
    return Account(
        account_id=str(account_id),
        email=email.strip(),
        password=password,
        proxy=proxy,
    )


def build_account_from_row(row: Mapping[str, Any]) -> Account:
    """Build an Account from a Supabase row payload."""
    account_id = row.get("id")
    email = row.get("email")
    password = row.get("password")

    if not account_id or not email or not password:
        raise ValueError("Supabase account row is missing id, email, or password")

    account = build_account(
        account_id=str(account_id),
        email=str(email),
        password=str(password),
    )
    logger.info("Prepared leased account %s", account.email)
    return account
