import json
import time
import redis
from app.core.config import settings

# Named queues for scaling and separation of concerns.
DEFAULT_QUEUE = "notifications"
QUEUES = {
    "ai_requests": "queue:ai_requests",
    "notifications": "queue:notifications",
    "analytics_events": "queue:analytics_events",
    "dead_letter": "queue:dead_letter",
}

_redis_url = (settings.REDIS_URL or "").strip()
client = redis.Redis.from_url(_redis_url, decode_responses=True) if _redis_url else None


def enqueue(event_name: str, payload: dict, queue: str = DEFAULT_QUEUE, attempt: int = 0):
    key = QUEUES.get(queue, queue)
    if client is None:
        return
    client.rpush(key, json.dumps({"event_name": event_name, "payload": payload, "attempt": attempt}))


def dequeue(queue: str = DEFAULT_QUEUE, block_seconds: int = 5):
    key = QUEUES.get(queue, queue)
    if client is None:
        time.sleep(max(0, min(block_seconds, 5)))
        return None
    item = client.blpop(key, timeout=block_seconds)
    if not item:
        return None
    _, raw = item
    return json.loads(raw)


def dead_letter(event: dict, reason: str):
    event = dict(event)
    event["dead_letter_reason"] = reason
    if client is None:
        return
    client.rpush(QUEUES["dead_letter"], json.dumps(event))

