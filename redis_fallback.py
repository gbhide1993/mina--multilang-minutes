#!/usr/bin/env python3
"""
Redis fallback handler for when Redis is in read-only mode
"""

import os
import time
from redis.exceptions import ReadOnlyError, ConnectionError

def handle_redis_readonly_error(func, *args, **kwargs):
    """
    Wrapper to handle Redis read-only errors with fallback
    """
    max_retries = 3
    retry_delay = 5  # seconds
    
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except ReadOnlyError:
            print(f"⚠️ Redis is read-only (attempt {attempt + 1}/{max_retries})")
            if attempt < max_retries - 1:
                print(f"🔄 Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
            else:
                print("❌ Redis still read-only, processing without queue")
                return None
        except ConnectionError as e:
            print(f"⚠️ Redis connection error: {e}")
            return None
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
            raise

def safe_enqueue(queue, job_func, *args, **kwargs):
    """
    Safely enqueue a job with fallback handling
    """
    def _enqueue():
        return queue.enqueue(job_func, *args, **kwargs)
    
    return handle_redis_readonly_error(_enqueue)