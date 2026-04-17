"""
Docstring for  video_manager.src.settings
"""

import os

from dotenv import load_dotenv

load_dotenv()


# =============================================================================
# CONFIGURATION
# =============================================================================

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)
REDIS_DB = int(os.getenv("REDIS_DB", "0"))

INPUT_SHEET_COMMENT_STATS: str = os.getenv(
    "INPUT_SHEET_COMMENT_STATS", "14HP03EiwdcXTBYpoY0nmcHHoqqLIqaKXuZlTBF3e59M"
)

OUTPUT_SHEET_COMMENT_STATS: str = ""
SUPABASE_STATS_TABLE_NAME: str = os.getenv("SUPABASE_STATS_TABLE_NAME", "instagram_stats")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TABLE_NAME = "instagram"
ERROR_TABLE_NAME = "instagram_error_videos"

COMMENTS_FILE_PATH: str = "comments_data.json"

# Sheets Credentials
SHEETS_CREDENTIALS_FILE: str = "zoecredentials.json"

# Account Cookies
KEY_COOKIES_AVAILABLE = "cookies:available"

# Redis key names
KEY_VIDEO_QUEUE_40 = "instagram:40"
KEY_VIDEO_QUEUE_120 = "instagram:120"
KEY_VIDEO_QUEUE_240 = "instagram:240"
KEY_VIDEO_QUEUE_REST = "instagram:rest"
PROCESSING_QUEUE: str = "instagram:processing"
TASK_STATE_PREFIX: str = "instagram:task_state"

PROXY: str = "http://62570d546c329a5d28b4__cr.{COUNTRY}:b59a5a071a414fec@74.81.81.81:823"

PROXY_COUNTRIES_LIST: list[str] = ["de", "be", "fr", "nl", "us", "gb", "ca", "au", "at"]

# Retry behavior for comment scraping requeues.
RETRY_DELAY_MIN_SECONDS: int = int(os.getenv("RETRY_DELAY_MIN_SECONDS", "120"))
RETRY_DELAY_MAX_SECONDS: int = int(os.getenv("RETRY_DELAY_MAX_SECONDS", "240"))
MAX_PAGINATION_RETRIES: int = int(os.getenv("MAX_PAGINATION_RETRIES", "2"))
CURSOR_MAX_AGE_SECONDS: int = int(os.getenv("CURSOR_MAX_AGE_SECONDS", "240"))

# Maximum number of times a single post can be re-queued before it is sent to
# the dead-letter (error) table and dropped from active queues.
MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "5"))

# Hard cap on pagination pages per find_comment call. Prevents runaway loops on
# posts with huge comment counts or corrupt cursors.
MAX_PAGINATION_DEPTH: int = int(os.getenv("MAX_PAGINATION_DEPTH", "300"))

# Maximum consecutive rate-limit (429) hits before giving up and re-queuing.
MAX_RATE_LIMIT_RETRIES: int = int(os.getenv("MAX_RATE_LIMIT_RETRIES", "3"))
