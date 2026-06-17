"""
Docstring for redis_queue_stats
"""

import os

from dotenv import load_dotenv

import redis

load_dotenv()
KEY_TOKENS_AVAILABLE = "cookies:available"
KEY_TOKENS_IN_USE = "cookies:in_use"
KEY_TOKENS_DEAD = "cookies:dead"

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
        (KEY_TOKENS_AVAILABLE, "Cookies Available"),
        (KEY_TOKENS_IN_USE, "Cookies In Use"),
        (KEY_TOKENS_DEAD, "Cookies Dead"),
        (KEY_VIDEO_QUEUE_40, "Instagram Queue ≤40"),
        (KEY_VIDEO_QUEUE_120, "Instagram Queue ≤120"),
        (KEY_VIDEO_QUEUE_240, "Instagram Queue ≤240"),
        (KEY_VIDEO_QUEUE_REST, "Instagram Queue Rest"),
        (PROCESSING_QUEUE, "Instagram Processing Queue"),
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
