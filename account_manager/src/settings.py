"""
Account Manager Settings
"""

import os

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

ACCOUNTS_FILE: str = os.getenv("ACCOUNTS_FILE", "accounts.txt")

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
COOKIE_REFRESH_INTERVAL: int = int(os.getenv("COOKIE_REFRESH_INTERVAL", "10"))

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
