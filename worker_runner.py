#!/usr/bin/env python3
"""
worker_runner.py

Start an RQ worker programmatically and listen for jobs enqueued by your webhook/backend.

Requirements:
  - redis and rq installed (pip install redis rq)
  - WORKER_MODULE environment must be importable (default: worker_multilang_production_fixed_clean)
  - REDIS_URL must point to your Redis instance
  - The worker functions referenced by the queue jobs (e.g. process_audio_job) must be present in the importable module.

Usage:
  python worker_runner.py
"""

import os
import sys
import time
import signal
import logging
from redis import Redis
from rq import Worker, Queue, Connection

# Configure logging
LOG_LEVEL = os.getenv("WORKER_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("mina.worker_runner")

# Config
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
QUEUES = os.getenv("WORKER_QUEUES", "default").split(",")  # e.g. "high,default,low"
WORKER_MODULE = os.getenv("WORKER_MODULE", "worker_multilang_production_fixed_clean")
WORKER_NAME = os.getenv("WORKER_NAME", None)  # optional

# Optional: Number of concurrent threads/workers used by RQ is controlled by RQ per process.
# RQ runs job functions sequentially in each worker process. To run parallel jobs, launch multiple worker processes.
# You can run multiple instances of this script to get concurrency.
SHUTDOWN_TIMEOUT = int(os.getenv("WORKER_SHUTDOWN_TIMEOUT", "10"))

def validate_env():
    missing = []
    if not REDIS_URL:
        missing.append("REDIS_URL")
    if missing:
        log.error("Missing required env vars: %s", ", ".join(missing))
        sys.exit(2)

def import_worker_module():
    # Import the module so worker knows where callables live.
    try:
        __import__(WORKER_MODULE)
        log.info("Imported worker module: %s", WORKER_MODULE)
    except Exception as e:
        log.exception("Failed to import worker module '%s': %s", WORKER_MODULE, e)
        raise

def run_worker():
    validate_env()
    import_worker_module()

    redis_conn = Redis.from_url(REDIS_URL)
    queues = [q.strip() for q in QUEUES if q.strip()]

    log.info("Connecting to Redis: %s", REDIS_URL)
    log.info("Listening on queues: %s", queues)

    # Create worker
    with Connection(redis_conn):
        worker = Worker(map(Queue, queues), name=WORKER_NAME)
        # Setup graceful shutdown via signals
        def _shutdown(signum, frame):
            log.info("Received shutdown signal %s — stopping worker gracefully...", signum)
            # stop listening for new jobs and allow running job to finish within timeout
            worker.request_stop()
        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)

        try:
            log.info("Starting RQ worker. Press Ctrl+C to stop.")
            worker.work(logging_level=logging.getLevelName(LOG_LEVEL))
        except Exception:
            log.exception("Worker crashed unexpectedly")
            raise
        finally:
            log.info("Worker stopped. Waiting %s sec for cleanup.", SHUTDOWN_TIMEOUT)
            time.sleep(SHUTDOWN_TIMEOUT)

if __name__ == "__main__":
    run_worker()
