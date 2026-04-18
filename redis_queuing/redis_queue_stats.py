"""
Docstring for redis_queue_stats
"""

import os

import redis
from dotenv import load_dotenv

load_dotenv()
KEY_COOKIES_AVAILABLE = "cookies:available"
KEY_COOKIES_IN_USE = "cookies:in_use"
KEY_COOKIES_DEAD = "cookies:dead"
TASK_STATE_PREFIX: str = "instagram:task_state"
# Video Queues by priority
# Redis key names
KEY_VIDEO_QUEUE_40 = "instagram:40"
KEY_VIDEO_QUEUE_120 = "instagram:120"
KEY_VIDEO_QUEUE_240 = "instagram:240"
KEY_VIDEO_QUEUE_REST = "instagram:rest"
PROCESSING_QUEUE: str = "instagram:processing"

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)
REDIS_DB = int(os.getenv("REDIS_DB", "0"))


def get_redis_connection():
    return redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD,
        db=REDIS_DB,
        decode_responses=True,
    )


def random_video_urlfrom_queue(queue_key: str = KEY_VIDEO_QUEUE_40) -> None:
    """
    Docstring for random_video_urlfrom_queue

    :param queue_key: Description
    :type queue_key: str
    """
    r = get_redis_connection()
    video_url = r.lpop(queue_key)
    print(f"Popped video URL from {queue_key}: {video_url}")


def print_queue_stats():
    r = get_redis_connection()
    keys = [
        (KEY_COOKIES_AVAILABLE, "Cookies Available"),
        (KEY_COOKIES_IN_USE, "Cookies In Use"),
        (KEY_COOKIES_DEAD, "Cookies Dead"),
        (KEY_VIDEO_QUEUE_40, "Video Queue ≤40"),
        (KEY_VIDEO_QUEUE_120, "Video Queue ≤120"),
        (KEY_VIDEO_QUEUE_240, "Video Queue ≤240"),
        (KEY_VIDEO_QUEUE_REST, "Video Queue Rest"),
        (PROCESSING_QUEUE, "Processing Queue"),
        (TASK_STATE_PREFIX + "*", "Task States"),
    ]

    print("Redis Queue Stats:")
    for key, label in keys:
        key_type = r.type(key)
        if key_type == "list":
            count = r.llen(key)
        elif key_type == "set":
            count = r.scard(key)
        elif key_type == "zset":
            count = r.zcard(key)
        elif key_type == "string":
            count = r.get(key) or 0
        else:
            count = "N/A"
        print(f"{label}: {count}")

        # random_video_urlfrom_queue(queue_key=key)


if __name__ == "__main__":
    print_queue_stats()
