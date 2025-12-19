"""
Invoice Creation Workflow (State Machine)

- One active invoice flow per user
- Fully resumable via DB-backed session memory
- No invoice persistence until CONFIRMATION
"""

from typing import Dict, Any, Optional
from db import set_user_state, get_user_state

# -------------------------
# Constants
# -------------------------

FLOW_NAME = "billing_invoice_flow"

STATES = {
    "INIT",
    "ITEMS_EXTRACTED",
    "CUSTOMER_PENDING",
    "PAYMENT_PENDING",
    "CONFIRMATION",
    "COMPLETED",
}


# -------------------------
# Public API
# -------------------------

def start_or_resume_flow(
    phone: str,
    initial_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Start a new invoice flow OR resume existing one.
    """

    state, meta = get_user_state(phone)

    # Resume existing billing flow
    if state and state.startswith(FLOW_NAME):
        return _resume_flow(phone, state, meta)

    # Block parallel invoice flows
    if state and state.startswith("billing_") and not state.startswith(FLOW_NAME):
        return {
            "status": "blocked",
            "reason": "another_billing_flow_active",
            "current_state": state,
        }

    # Start fresh
    meta = {
        "items": [],
        "customer": None,
        "payment": None,
        "draft_invoice": None,
    }

    if initial_payload:
        meta.update(initial_payload)

    set_user_state(phone, f"{FLOW_NAME}:INIT", meta)

    return {
        "status": "started",
        "state": "INIT",
        "next_action": "extract_items",
    }


def advance_flow(
    phone: str,
    updates: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Advance the invoice flow based on provided updates.
    """

    state, meta = get_user_state(phone)

    if not state or not state.startswith(FLOW_NAME):
        return {
            "status": "error",
            "reason": "no_active_invoice_flow",
        }

    current = state.split(":")[1]

    if current not in STATES:
        return {
            "status": "error",
            "reason": "invalid_state",
            "state": current,
        }

    # Merge updates
    meta.update(updates)

    # -------------------------
    # State transitions
    # -------------------------

    if current == "INIT":
        if meta.get("items"):
            return _transition(phone, "ITEMS_EXTRACTED", meta)

        return _stay(current, meta, "await_items")

    if current == "ITEMS_EXTRACTED":
        if meta.get("customer"):
            return _transition(phone, "PAYMENT_PENDING", meta)

        return _transition(phone, "CUSTOMER_PENDING", meta)

    if current == "CUSTOMER_PENDING":
        if meta.get("customer"):
            return _transition(phone, "PAYMENT_PENDING", meta)

        return _stay(current, meta, "await_customer")

    if current == "PAYMENT_PENDING":
        if meta.get("payment"):
            return _transition(phone, "CONFIRMATION", meta)

        return _stay(current, meta, "await_payment_details")

    if current == "CONFIRMATION":
        if updates.get("confirm") is True:
            return _transition(phone, "COMPLETED", meta)

        return _stay(current, meta, "await_confirmation")

    if current == "COMPLETED":
        return {
            "status": "done",
            "state": "COMPLETED",
        }

    return {
        "status": "error",
        "reason": "unhandled_state",
        "state": current,
    }


def cancel_flow(phone: str) -> Dict[str, Any]:
    """
    Cancel active invoice flow.
    """
    state, _ = get_user_state(phone)

    if state and state.startswith(FLOW_NAME):
        set_user_state(phone, None, {})
        return {"status": "cancelled"}

    return {"status": "no_active_flow"}


# -------------------------
# Internal helpers
# -------------------------

def _resume_flow(phone: str, state: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    current = state.split(":")[1]

    return {
        "status": "resumed",
        "state": current,
        "meta": meta,
        "next_action": _next_action_for_state(current, meta),
    }


def _transition(phone: str, new_state: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    set_user_state(phone, f"{FLOW_NAME}:{new_state}", meta)

    return {
        "status": "advanced",
        "state": new_state,
        "next_action": _next_action_for_state(new_state, meta),
    }


def _stay(state: str, meta: Dict[str, Any], action: str) -> Dict[str, Any]:
    return {
        "status": "waiting",
        "state": state,
        "next_action": action,
        "meta": meta,
    }


def _next_action_for_state(state: str, meta: Dict[str, Any]) -> str:
    return {
        "INIT": "extract_items",
        "ITEMS_EXTRACTED": "request_customer",
        "CUSTOMER_PENDING": "request_customer",
        "PAYMENT_PENDING": "request_payment",
        "CONFIRMATION": "request_confirmation",
        "COMPLETED": "none",
    }.get(state, "unknown")
