"""
Script to clear all items from a specified Redis queue.
"""
import sys
import redis
from dotenv import load_dotenv
import os

load_dotenv()

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)
REDIS_DB = int(os.getenv("REDIS_DB", "0"))


def clear_queue(queue_key: str):
    r = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD,
        db=REDIS_DB,
        decode_responses=True
    )
    r.delete(queue_key)
    print(f"Cleared all items from queue: {queue_key}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python clear_redis_queue.py <queue_key>")
        sys.exit(1)
    queue_key = sys.argv[1]
    clear_queue(queue_key)
