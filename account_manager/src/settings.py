"""
Account Manager Settings
"""

import os
import socket

from dotenv import load_dotenv

load_dotenv()


# =============================================================================
# REDIS
# =============================================================================

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)
REDIS_DB = int(os.getenv("REDIS_DB", "0"))

# Redis key names
KEY_COOKIES_AVAILABLE = "cookies:available"

# =============================================================================
# ACCOUNTS
# =============================================================================

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
ACCOUNTS_TABLE_NAME: str = os.getenv("ACCOUNTS_TABLE_NAME", "instagram_accounts")
WORKER_ID: str = os.getenv("WORKER_ID", socket.gethostname())
ACCOUNT_POLL_INTERVAL_SECONDS: int = int(
    os.getenv("ACCOUNT_POLL_INTERVAL_SECONDS", "10")
)
ACCOUNT_LEASE_TIMEOUT_SECONDS: int = int(
    os.getenv("ACCOUNT_LEASE_TIMEOUT_SECONDS", "180")
)
ACCOUNT_HEARTBEAT_INTERVAL_SECONDS: int = int(
    os.getenv("ACCOUNT_HEARTBEAT_INTERVAL_SECONDS", "30")
)
COOKIE_STORAGE_DIR: str = os.getenv(
    "COOKIE_STORAGE_DIR", "downloaded_files/account_cookies"
)

# =============================================================================
# PROXY
# =============================================================================

# Template with {COUNTRY} placeholder, same format as the scraper.
PROXY_TEMPLATE: str = os.getenv(
    "PROXY_TEMPLATE",
    "http://62570d546c329a5d28b4__cr.{COUNTRY}:b59a5a071a414fec@74.81.81.81:823",
)
PROXY_COUNTRIES: list[str] = os.getenv(
    "PROXY_COUNTRIES", "de,be,fr,nl,us,gb,ca,au,at"
).split(",")

# =============================================================================
# COOKIE POOL
# =============================================================================

# Don't push more cookies when the pool already has this many.
MAX_COOKIES_POOL_SIZE: int = int(os.getenv("MAX_COOKIES_POOL_SIZE", "100"))

# How often (seconds) each worker refreshes cookies and pushes to Redis.
COOKIE_REFRESH_INTERVAL: int = int(os.getenv("COOKIE_REFRESH_INTERVAL", "5"))

# How long a leased worker should idle when enough cookies are already available.
COOKIE_POOL_IDLE_SLEEP_SECONDS: int = int(
    os.getenv("COOKIE_POOL_IDLE_SLEEP_SECONDS", "20")
)

# How long (seconds) to idle-browse between cookie refreshes to keep the session warm.
HUMAN_SIM_DURATION: int = int(os.getenv("HUMAN_SIM_DURATION", "120"))

PROXY: str = (
    "http://62570d546c329a5d28b4__cr.{COUNTRY}:b59a5a071a414fec@74.81.81.81:823"
)

PROXY_COUNTRIES_LIST: list[str] = ["de", "be", "fr", "nl", "us", "gb", "ca", "au", "at"]

# Retry behavior for comment scraping requeues.
RETRY_DELAY_MIN_SECONDS: int = int(os.getenv("RETRY_DELAY_MIN_SECONDS", "120"))
RETRY_DELAY_MAX_SECONDS: int = int(os.getenv("RETRY_DELAY_MAX_SECONDS", "240"))
MAX_PAGINATION_RETRIES: int = int(os.getenv("MAX_PAGINATION_RETRIES", "2"))
CURSOR_MAX_AGE_SECONDS: int = int(os.getenv("CURSOR_MAX_AGE_SECONDS", "240"))
