"""
Post Invoice Creation Orchestration

Responsibilities:
- Set payment status
- Notify ledger module (if available)
- Trigger reminder via existing system (if DUE)

This module:
- Does NOT create invoices
- Does NOT implement reminders
- Does NOT send messages
"""

from typing import Dict, Any, Optional
from datetime import datetime, timedelta


# -------------------------
# Public API
# -------------------------

def handle_invoice_created(
    invoice: Dict[str, Any],
    payment_status: str,
    user_phone: str,
):
    """
    Handle side-effects AFTER invoice is created.

    Args:
        invoice (dict): Finalized invoice dict
        payment_status (str): PAID or DUE
        user_phone (str): Invoice owner phone
    """

    payment_status = payment_status.upper()
    if payment_status not in {"PAID", "DUE"}:
        return {
            "status": "ignored",
            "reason": "invalid_payment_status"
        }

    invoice["payment_status"] = payment_status

    results = {
        "payment_status": payment_status,
        "ledger_notified": False,
        "reminder_triggered": False,
    }

    # -------------------------
    # Notify ledger (if exists)
    # -------------------------

    results["ledger_notified"] = _notify_ledger_if_exists(
        invoice=invoice,
        user_phone=user_phone,
    )

    # -------------------------
    # Trigger reminder (DUE only)
    # -------------------------

    if payment_status == "DUE":
        results["reminder_triggered"] = _trigger_due_payment_reminder(
            invoice=invoice,
            user_phone=user_phone,
        )

    return {
        "status": "processed",
        "results": results,
    }


# -------------------------
# Internal helpers
# -------------------------

def _notify_ledger_if_exists(
    invoice: Dict[str, Any],
    user_phone: str,
) -> bool:
    """
    Notify ledger module if present.
    Soft dependency — safe if missing.
    """

    try:
        # Ledger module may or may not exist
        from ledger_plugin import record_invoice  # type: ignore

        record_invoice(
            invoice=invoice,
            user_phone=user_phone,
        )
        return True

    except ImportError:
        # Ledger not installed — silently skip
        return False

    except Exception as e:
        # Ledger exists but failed — log upstream
        print("Ledger notification failed:", e)
        return False


def _trigger_due_payment_reminder(
    invoice: Dict[str, Any],
    user_phone: str,
) -> bool:
    """
    Trigger reminder via existing task/reminder system.
    DOES NOT implement reminder logic.
    """

    try:
        # Use existing task creation mechanism
        from db import create_task

        due_date = _extract_due_date(invoice)

        create_task(
            phone_or_user_id=user_phone,
            title="Invoice payment due",
            description=_build_due_description(invoice),
            due_at=due_date,
            source="billing_invoice",
            metadata={
                "invoice_id": invoice.get("invoice_number"),
                "type": "invoice_payment",
            }
        )
        return True

    except Exception as e:
        print("Failed to trigger due payment reminder:", e)
        return False


def _extract_due_date(invoice: Dict[str, Any]):
    """
    Determine reminder due date.
    Uses invoice date + default offset if missing.
    """

    invoice_date = invoice.get("invoice_date")
    try:
        if invoice_date:
            base = datetime.fromisoformat(invoice_date)
        else:
            base = datetime.utcnow()
    except Exception:
        base = datetime.utcnow()

    # Default: 7 days after invoice date
    return base + timedelta(days=7)


def _build_due_description(invoice: Dict[str, Any]) -> str:
    """
    Human-readable reminder description.
    """

    total = invoice.get("total_amount")
    currency = invoice.get("currency", "INR")
    customer = invoice.get("metadata", {}).get("customer")

    parts = ["Invoice payment due"]
    if customer:
        parts.append(f"from {customer}")
    if total:
        parts.append(f"({currency} {total})")

    return " ".join(parts)
