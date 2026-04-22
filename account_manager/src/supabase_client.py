"""Supabase client and account lease helpers for the account manager."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from supabase import Client, create_client

from src.account_loader import Account, build_account_from_row
from src.settings import (
    ACCOUNT_LEASE_TIMEOUT_SECONDS,
    ACCOUNTS_TABLE_NAME,
    SUPABASE_KEY,
    SUPABASE_URL,
)

logger = logging.getLogger(__name__)

_supabase_client: Client | None = None


def get_supabase_client() -> Client:
    """Return a singleton Supabase client."""
    global _supabase_client

    if _supabase_client is not None:
        return _supabase_client

    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError(
            "Supabase credentials not found. "
            "Set SUPABASE_URL and SUPABASE_KEY environment variables."
        )

    _supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase_client


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _to_iso(value: datetime) -> str:
    return value.isoformat()


def _parse_timestamp(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        # Ensure all comparisons are done with timezone-aware UTC datetimes.
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except ValueError:
        logger.warning("Unable to parse timestamp value: %s", value)
        return None


def _lease_is_stale(row: dict[str, Any]) -> bool:
    if not row.get("in_use"):
        return False

    last_seen = _parse_timestamp(row.get("last_heartbeat")) or _parse_timestamp(
        row.get("claimed_at")
    )
    if last_seen is None:
        return True

    return _now_utc() - last_seen > timedelta(seconds=ACCOUNT_LEASE_TIMEOUT_SECONDS)


def _fetch_claim_candidates(limit: int = 25) -> list[dict[str, Any]]:
    client = get_supabase_client()
    response = (
        client.table(ACCOUNTS_TABLE_NAME)
        .select(
            "id,email,password,in_use,skip_account,error,claimed_by,claimed_at,last_heartbeat"
        )
        .eq("skip_account", False)
        .limit(limit)
        .execute()
    )

    rows = response.data or []
    eligible_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if not row.get("in_use") or _lease_is_stale(row):
            eligible_rows.append(row)

    eligible_rows.sort(
        key=lambda row: (
            0 if not row.get("in_use") else 1,
            row.get("last_heartbeat") or row.get("claimed_at") or "",
        )
    )
    return eligible_rows


def _try_claim_row(row: dict[str, Any], worker_id: str) -> bool:
    client = get_supabase_client()
    now_dt = _now_utc()
    now = _to_iso(now_dt)
    stale_cutoff = _to_iso(now_dt - timedelta(seconds=ACCOUNT_LEASE_TIMEOUT_SECONDS))
    query = (
        client.table(ACCOUNTS_TABLE_NAME)
        .update(
            {
                "in_use": True,
                "claimed_by": worker_id,
                "claimed_at": now,
                "last_heartbeat": now,
                "error": None,
            }
        )
        .eq("id", row["id"])
        .eq("skip_account", False)
    )

    if row.get("in_use"):
        if row.get("last_heartbeat"):
            query = query.eq("in_use", True).lt("last_heartbeat", stale_cutoff)
        elif row.get("claimed_at"):
            query = query.eq("in_use", True).lt("claimed_at", stale_cutoff)
        else:
            return False
    else:
        query = query.eq("in_use", False)

    response = query.execute()
    return bool(response.data)


def claim_next_account(worker_id: str) -> Account | None:
    """Claim the next available or stale-leased account for this worker."""
    for row in _fetch_claim_candidates():
        if _try_claim_row(row, worker_id):
            logger.info("Claimed account %s for worker %s", row.get("email"), worker_id)
            return build_account_from_row(row)

    return None


def heartbeat_account_lease(account_id: str, worker_id: str) -> bool:
    """Refresh last_heartbeat for an active account lease."""
    client = get_supabase_client()
    response = (
        client.table(ACCOUNTS_TABLE_NAME)
        .update({"last_heartbeat": _to_iso(_now_utc())})
        .eq("id", account_id)
        .eq("claimed_by", worker_id)
        .eq("in_use", True)
        .execute()
    )
    return bool(response.data)


def release_account(account_id: str, worker_id: str, error: str | None = None) -> bool:
    """Release an account lease while keeping the account claimable."""
    payload: dict[str, Any] = {
        "in_use": False,
        "claimed_by": None,
        "claimed_at": None,
        "last_heartbeat": None,
    }
    if error:
        payload["error"] = error

    client = get_supabase_client()
    response = (
        client.table(ACCOUNTS_TABLE_NAME)
        .update(payload)
        .eq("id", account_id)
        .eq("claimed_by", worker_id)
        .execute()
    )
    return bool(response.data)


def mark_account_skipped(account_id: str, worker_id: str, error: str) -> bool:
    """Mark an account as unusable so future workers avoid it."""
    client = get_supabase_client()
    response = (
        client.table(ACCOUNTS_TABLE_NAME)
        .update(
            {
                "in_use": False,
                "skip_account": True,
                "error": error,
                "claimed_by": None,
                "claimed_at": None,
                "last_heartbeat": None,
            }
        )
        .eq("id", account_id)
        .eq("claimed_by", worker_id)
        .execute()
    )
    return bool(response.data)
