"""
Docstring for redis_queue_stats
"""
import redis
from dotenv import load_dotenv
import os

load_dotenv()
KEY_TOKENS_AVAILABLE = "tokens:available"
KEY_TOKENS_IN_USE = "tokens:in_use"
KEY_TOKENS_DEAD = "tokens:dead"

# Video Queues by priority
# Redis key names
KEY_VIDEO_QUEUE_40 = "videos:40"
KEY_VIDEO_QUEUE_120 = "videos:120"
KEY_VIDEO_QUEUE_240 = "videos:240"
KEY_VIDEO_QUEUE_REST = "videos:rest"
PROCESSING_QUEUE: str = "videos:processing"

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
        decode_responses=True
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
        (KEY_TOKENS_AVAILABLE, 'Tokens Available'),
        (KEY_TOKENS_IN_USE, 'Tokens In Use'),
        (KEY_TOKENS_DEAD, 'Tokens Dead'),
        (KEY_VIDEO_QUEUE_40, 'Video Queue ≤40'),
        (KEY_VIDEO_QUEUE_120, 'Video Queue ≤120'),
        (KEY_VIDEO_QUEUE_240, 'Video Queue ≤240'),
        (KEY_VIDEO_QUEUE_REST, 'Video Queue Rest'),
        (PROCESSING_QUEUE, 'Processing Queue'),
    ]
    
    print("Redis Queue Stats:")
    for key, label in keys:
        key_type = r.type(key)
        if key_type == 'list':
            count = r.llen(key)
        elif key_type == 'set':
            count = r.scard(key)
        elif key_type == 'zset':
            count = r.zcard(key)
        elif key_type == 'string':
            count = r.get(key) or 0
        else:
            count = 'N/A'
        print(f"{label}: {count}")
    
        # random_video_urlfrom_queue(queue_key=key)

if __name__ == "__main__":
    print_queue_stats()
