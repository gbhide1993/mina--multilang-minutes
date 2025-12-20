"""
Internal Usage Metrics for Billing Plugin

Tracks:
- invoices_created
- ocr_imports
- pdfs_generated

Rules:
- Non-blocking
- Best-effort only
- Uses existing user state / activity log
"""

from typing import Dict
from db import get_user_state, set_user_state, log_user_activity


# -------------------------
# Metric keys
# -------------------------

METRICS_KEY = "billing_metrics"

DEFAULT_METRICS = {
    "invoices_created": 0,
    "ocr_imports": 0,
    "pdfs_generated": 0,
}


# -------------------------
# Public API
# -------------------------

def increment_metric(phone: str, metric: str, amount: int = 1):
    """
    Increment a billing metric safely.

    Never blocks or raises.
    """

    try:
        state, meta = get_user_state(phone)
        meta = meta or {}

        metrics = meta.get(METRICS_KEY, DEFAULT_METRICS.copy())

        if metric not in metrics:
            # Ignore unknown metrics
            return

        metrics[metric] += amount
        meta[METRICS_KEY] = metrics

        # Persist back (state unchanged)
        set_user_state(phone, state, meta)

        # Optional activity log (analytics / debugging)
        _log_metric_event(phone, metric, metrics[metric])

    except Exception:
        # Silent failure by design
        pass


def get_metrics(phone: str) -> Dict:
    """
    Read billing metrics (best-effort).
    """

    try:
        _, meta = get_user_state(phone)
        return meta.get(METRICS_KEY, DEFAULT_METRICS.copy()) if meta else DEFAULT_METRICS.copy()
    except Exception:
        return DEFAULT_METRICS.copy()


# -------------------------
# Internal helpers
# -------------------------

def _log_metric_event(phone: str, metric: str, value: int):
    """
    Log usage event for analytics (optional).
    """
    try:
        log_user_activity(
            phone=phone,
            activity_type="billing_metric",
            activity_data={
                "metric": metric,
                "value": value,
            },
            source="billing_plugin"
        )
    except Exception:
        pass
