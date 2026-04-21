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

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TABLE_NAME = "instagram"
ERROR_TABLE_NAME = "instagram_error_videos"

COMMENTS_FILE_PATH: str = "comments_data.json"

# Sheets Credentials
SHEETS_CREDENTIALS_FILE: str = "zoecredentials.json"

# Account Cookies
KEY_COOKIES_AVAILABLE = "cookies:available"
POST_PAGE_COOKIE_RETRY_ATTEMPTS: int = int(os.getenv("POST_PAGE_COOKIE_RETRY_ATTEMPTS", "3"))

# Redis key names
KEY_VIDEO_QUEUE_40 = "instagram:40"
KEY_VIDEO_QUEUE_120 = "instagram:120"
KEY_VIDEO_QUEUE_240 = "instagram:240"
KEY_VIDEO_QUEUE_REST = "instagram:rest"
PROCESSING_QUEUE: str = "instagram:processing"

PROXY: str = "http://62570d546c329a5d28b4__cr.{COUNTRY}:b59a5a071a414fec@74.81.81.81:823"

PROXY_COUNTRIES_LIST: list[str] = ["de", "be", "fr", "nl", "us", "gb", "ca", "au", "at"]
