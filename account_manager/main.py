"""
Account Manager — keeps Instagram sessions alive and feeds cookies to Redis.

For each account in accounts.txt:
  1. Launch a headless undetected-Chrome browser through a unique proxy.
  2. Log in to Instagram.
  3. Loop forever:
     a. Simulate human browsing (scroll, explore, open posts).
     b. Extract cookies from the live session.
     c. If the Redis cookie pool has < MAX_COOKIES_POOL_SIZE entries, push cookies.
     d. Wait COOKIE_REFRESH_INTERVAL seconds, then repeat.
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.account_loader import Account, load_accounts
from src.instagram_driver import InstagramDriver
from src.redis_client import get_available_cookies_count, is_pool_full, push_cookies
from src.settings import COOKIE_REFRESH_INTERVAL, MAX_COOKIES_POOL_SIZE

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - [%(threadName)s] %(message)s",
    handlers=[
        logging.FileHandler("account_manager.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# TODO: Work on Keep pushing the cookies to the redis
# Currently it's just staying where it is


def run_account_worker(account: Account) -> None:
    """Long-running worker for a single account.  Runs in its own thread."""
    driver = InstagramDriver(account)
    try:
        driver.start()

        if not driver.login():
            logger.error("Skipping account %s — login failed.", account.email)
            return

        while True:
            # 1. Simulate human browsing to keep the session warm
            driver.simulate_human_behaviour()

            # 2. Extract cookies from the live browser
            cookies = driver.get_cookies_dict()
            if not cookies:
                logger.warning(
                    "No cookies extracted for %s — session may be dead.", account.email
                )
                # Try re-login once
                driver.stop()
                driver.start()
                if not driver.login():
                    logger.error(
                        "Re-login failed for %s. Exiting worker.", account.email
                    )
                    return
                continue

            # 3. Push to Redis if the pool isn't full
            if is_pool_full():
                pool_size = get_available_cookies_count()
                logger.info(
                    "Cookie pool full (%s >= %s). Waiting for pool to drain...",
                    pool_size,
                    MAX_COOKIES_POOL_SIZE,
                )
            else:
                push_cookies(account_id=account.email, cookies=cookies)

            # 4. Wait before next refresh cycle
            logger.info(
                "Account %s: sleeping %ss before next cookie refresh.",
                account.email,
                COOKIE_REFRESH_INTERVAL,
            )
            time.sleep(COOKIE_REFRESH_INTERVAL)

    except KeyboardInterrupt:
        logger.info("Worker for %s interrupted.", account.email)
    except Exception:
        logger.exception("Fatal error in worker for %s", account.email)
    finally:
        driver.stop()


def main() -> None:
    accounts = load_accounts()
    if not accounts:
        logger.error("No accounts loaded. Add accounts to accounts.txt and retry.")
        return

    logger.info("Starting account manager with %s account(s).", len(accounts))

    # One thread per account — each thread owns its own browser instance.
    with ThreadPoolExecutor(
        max_workers=len(accounts),
        thread_name_prefix="ig-worker",
    ) as executor:
        futures = {executor.submit(run_account_worker, acct): acct for acct in accounts}
        for future in as_completed(futures):
            acct = futures[future]
            try:
                future.result()
            except Exception:
                logger.exception("Worker for %s exited with error.", acct.email)


if __name__ == "__main__":
    main()
