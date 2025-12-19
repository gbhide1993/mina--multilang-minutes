"""
Invoice Confirmation Response Builder

- Formats draft invoice for user confirmation
- Returns structured message objects only
- No side effects (no sending, no DB)
"""

from typing import Dict, List, Any


def build_invoice_confirmation_response(draft_invoice: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build confirmation response for a draft invoice.

    Args:
        draft_invoice (dict): invoice dict (from Invoice.to_dict())

    Returns:
        dict: structured confirmation message
    """

    line_items = draft_invoice.get("line_items", []) or []
    currency = draft_invoice.get("currency", "INR")

    formatted_items, subtotal = _format_items(line_items, currency)

    tax_amount = draft_invoice.get("tax_amount") or 0
    total = round(subtotal + tax_amount, 2)

    header = "🧾 *Invoice Preview*"

    body_lines = []
    if formatted_items:
        body_lines.extend(formatted_items)
    else:
        body_lines.append("_No items added yet_")

    body_lines.append("")
    body_lines.append(f"*Subtotal:* {currency} {subtotal:.2f}")

    if tax_amount:
        body_lines.append(f"*Tax:* {currency} {tax_amount:.2f}")

    body_lines.append(f"*Total:* {currency} {total:.2f}")

    footer = "Please confirm or edit the invoice."

    return {
        "type": "invoice_confirmation",
        "header": header,
        "body": "\n".join(body_lines),
        "footer": footer,
        "options": [
            {
                "id": "confirm",
                "label": "1️⃣ Confirm invoice"
            },
            {
                "id": "edit",
                "label": "2️⃣ Edit invoice"
            }
        ],
        "meta": {
            "subtotal": subtotal,
            "tax_amount": tax_amount,
            "total": total,
            "currency": currency,
        }
    }


# -------------------------
# Helpers
# -------------------------

def _format_items(items: List[Dict[str, Any]], currency: str):
    """
    Format line items into readable lines and compute subtotal.
    """

    lines = []
    subtotal = 0.0

    for idx, item in enumerate(items, start=1):
        name = item.get("name", "Item")
        qty = item.get("quantity")
        price = item.get("unit_price")

        line_total = None
        if qty is not None and price is not None:
            try:
                line_total = float(qty) * float(price)
                subtotal += line_total
            except Exception:
                pass

        if qty is not None and price is not None and line_total is not None:
            line = f"{idx}. {name} — {qty} × {currency} {price:.2f} = {currency} {line_total:.2f}"
        elif price is not None:
            line = f"{idx}. {name} — {currency} {price:.2f}"
        else:
            line = f"{idx}. {name}"

        lines.append(line)

    return lines, round(subtotal, 2)
