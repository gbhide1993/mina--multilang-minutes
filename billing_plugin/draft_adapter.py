"""
Intent + Entities → Billing Draft Adapter

Purpose:
- Convert MinA intent payload into a draft invoice state
- Handle partial / missing information gracefully
- NEVER persist or finalize invoices
"""

from typing import Dict, List, Any
from billing_plugin.invoice import Invoice


SUPPORTED_BILLING_INTENTS = {
    "create_invoice",
    "edit_invoice",
    "view_invoice",
}


def build_billing_draft(
    intent: str,
    entities: Dict[str, Any],
    context: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    Build a billing draft from intent + entities.

    Returns:
    {
        status: "draft",
        invoice: dict,
        missing_fields: list[str],
        confidence: float
    }
    """

    context = context or {}
    entities = entities or {}

    missing_fields: List[str] = []
    confidence_signals = 0
    confidence_total = 6  # number of signals we care about

    if intent not in SUPPORTED_BILLING_INTENTS:
        return {
            "status": "ignored",
            "reason": "unsupported_intent",
            "missing_fields": [],
        }

    # -------------------------
    # Core fields
    # -------------------------

    vendor_name = entities.get("vendor") or entities.get("seller")
    if vendor_name:
        confidence_signals += 1
    else:
        missing_fields.append("vendor_name")

    customer_name = entities.get("customer") or entities.get("buyer")
    if customer_name:
        confidence_signals += 1
    else:
        missing_fields.append("customer")

    invoice_number = entities.get("invoice_number")
    if invoice_number:
        confidence_signals += 1

    invoice_date = entities.get("date")
    if invoice_date:
        confidence_signals += 1

    # -------------------------
    # Line items (partial OK)
    # -------------------------

    line_items = []
    raw_items = entities.get("line_items") or []

    if raw_items:
        for item in raw_items:
            name = item.get("name")
            qty = item.get("quantity")
            price = item.get("unit_price")

            if not name:
                continue

            line_items.append({
                "name": name,
                "quantity": qty,
                "unit_price": price,
                "confidence": item.get("confidence", 0.5),
            })

        confidence_signals += 1
    else:
        missing_fields.append("line_items")

    # -------------------------
    # Price completeness check
    # -------------------------

    incomplete_items = []
    for li in line_items:
        if li.get("quantity") is None or li.get("unit_price") is None:
            incomplete_items.append(li.get("name"))

    if incomplete_items:
        missing_fields.append("price_or_quantity")

    # -------------------------
    # Build Invoice (still draft)
    # -------------------------

    invoice = Invoice(
        vendor_name=vendor_name,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        line_items=line_items,
        metadata={
            "customer": customer_name,
            "source_intent": intent,
            "context": context,
        },
    )

    # -------------------------
    # Confidence score
    # -------------------------

    confidence = round(confidence_signals / confidence_total, 2)

    return {
        "status": "draft",
        "invoice": invoice.to_dict(),
        "missing_fields": sorted(set(missing_fields)),
        "confidence": confidence,
    }
