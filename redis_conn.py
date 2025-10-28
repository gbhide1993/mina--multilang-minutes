# redis_conn.py
"""
Simple Redis + RQ helper (safe for web + worker).
Exports:
  - get_redis_url()
  - get_redis_conn_or_raise()
  - get_queue(name="transcribe")
  - redis_url, redis_conn, queue  (for backward compatibility)
"""

import os
import logging
from redis import from_url, RedisError
from rq import Queue

logger = logging.getLogger(__name__)

def get_redis_url():
    """Return the REDIS_URL env var (None if missing)."""
    url = os.getenv("REDIS_URL")
    return url.strip() if url else None


def get_redis_conn_or_raise():
    """Create and return a verified Redis connection."""
    url = get_redis_url()
    if not url:
        raise RuntimeError("REDIS_URL not set in environment.")
    try:
        r = from_url(url, decode_responses=False)
        r.ping()
        logger.info("✅ Connected to Redis at %s", url)
        return r
    except RedisError as e:
        logger.error("❌ Redis connection failed: %s", e)
        raise


def get_queue(name: str = "default"):
    """Return an RQ Queue bound to a Redis connection."""
    rc = get_redis_conn_or_raise()
    return Queue(name, connection=rc)


# module-level convenience
redis_url = get_redis_url()
redis_conn = None
queue = None
try:
    if redis_url:
        redis_conn = get_redis_conn_or_raise()
        queue = get_queue("default")
except Exception as e:
    logger.warning("Redis initialization deferred: %s", e)
