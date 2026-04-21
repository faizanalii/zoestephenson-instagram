"""Account Manager — one leased Instagram account per container."""

import logging
import time

from src.account_loader import Account
from src.cookie_store import load_account_cookies, save_account_cookies
from src.instagram_driver import InstagramDriver
from src.redis_client import get_available_cookies_count, is_pool_full, push_cookies
from src.settings import (
    ACCOUNT_HEARTBEAT_INTERVAL_SECONDS,
    ACCOUNT_POLL_INTERVAL_SECONDS,
    COOKIE_POOL_IDLE_SLEEP_SECONDS,
    COOKIE_REFRESH_INTERVAL,
    MAX_COOKIES_POOL_SIZE,
    WORKER_ID,
)
from src.supabase_client import (
    claim_next_account,
    heartbeat_account_lease,
    mark_account_skipped,
    release_account,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - [%(threadName)s] %(message)s",
    handlers=[
        logging.FileHandler("account_manager.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


class AccountLoginError(RuntimeError):
    """Raised when an account session cannot be restored or logged in."""


def _authenticate_driver(driver: InstagramDriver, account: Account) -> None:
    driver.start()

    persisted_cookies = load_account_cookies(account)
    if persisted_cookies and driver.restore_session(persisted_cookies):
        return

    if persisted_cookies:
        logger.warning(
            "Saved cookies did not restore a valid session for %s. Falling back to login.",
            account.email,
        )

    if not driver.login():
        raise AccountLoginError(driver.get_login_failure_reason())

    cookies = driver.get_cookies()
    if cookies:
        save_account_cookies(account, cookies)


def _refresh_account_session(driver: InstagramDriver, account: Account) -> None:
    driver.stop()
    _authenticate_driver(driver, account)


def run_account_worker(account: Account) -> None:
    """Run a single leased account until interrupted or it becomes invalid."""
    driver = InstagramDriver(account)
    last_heartbeat = 0.0

    try:
        _authenticate_driver(driver, account)

        while True:
            now = time.monotonic()
            if now - last_heartbeat >= ACCOUNT_HEARTBEAT_INTERVAL_SECONDS:
                if not heartbeat_account_lease(account.account_id, WORKER_ID):
                    raise RuntimeError(
                        f"Lost Supabase lease ownership for account {account.email}"
                    )
                last_heartbeat = now

            if is_pool_full():
                pool_size = get_available_cookies_count()
                logger.info(
                    "Cookie pool full (%s >= %s). Keeping %s idle for %ss.",
                    pool_size,
                    MAX_COOKIES_POOL_SIZE,
                    account.email,
                    COOKIE_POOL_IDLE_SLEEP_SECONDS,
                )
                time.sleep(COOKIE_POOL_IDLE_SLEEP_SECONDS)
                continue

            driver.simulate_human_behaviour()

            cookies = driver.get_cookies_dict()
            if not cookies or "datr" not in cookies or not driver.is_logged_in():
                logger.warning(
                    "Session invalid for %s. Re-authenticating.", account.email
                )
                _refresh_account_session(driver, account)
                continue

            push_cookies(account_id=account.email, cookies=cookies)
            save_account_cookies(account, driver.get_cookies())

            logger.info(
                "Account %s: sleeping %ss before next cookie refresh.",
                account.email,
                COOKIE_REFRESH_INTERVAL,
            )
            time.sleep(COOKIE_REFRESH_INTERVAL)

    finally:
        driver.stop()


def _wait_for_cookie_demand() -> None:
    if not is_pool_full():
        return

    pool_size = get_available_cookies_count()
    logger.info(
        "Cookie pool full (%s >= %s). Sleeping %ss before checking again.",
        pool_size,
        MAX_COOKIES_POOL_SIZE,
        COOKIE_POOL_IDLE_SLEEP_SECONDS,
    )
    time.sleep(COOKIE_POOL_IDLE_SLEEP_SECONDS)


def main() -> None:
    logger.info("Starting account manager worker_id=%s", WORKER_ID)

    while True:
        leased_account: Account | None = None
        should_skip_account = False
        release_error: str | None = None

        try:
            _wait_for_cookie_demand()
            if is_pool_full():
                continue

            leased_account = claim_next_account(WORKER_ID)
            if leased_account is None:
                logger.info(
                    "No eligible Instagram accounts available. Retrying in %ss.",
                    ACCOUNT_POLL_INTERVAL_SECONDS,
                )
                time.sleep(ACCOUNT_POLL_INTERVAL_SECONDS)
                continue

            logger.info("Leased account %s to this container", leased_account.email)
            run_account_worker(leased_account)

        except KeyboardInterrupt:
            logger.info("Account manager interrupted. Releasing lease and exiting.")
            break
        except AccountLoginError as exc:
            should_skip_account = True
            release_error = str(exc)
            logger.error("Account login failure: %s", exc)
        except Exception as exc:
            release_error = str(exc)
            logger.exception("Fatal runtime error in account manager")
            time.sleep(ACCOUNT_POLL_INTERVAL_SECONDS)
        finally:
            if leased_account is None:
                continue

            if should_skip_account:
                mark_account_skipped(
                    leased_account.account_id,
                    WORKER_ID,
                    release_error or "Unknown Instagram account failure",
                )
            else:
                release_account(leased_account.account_id, WORKER_ID, release_error)


if __name__ == "__main__":
    main()
