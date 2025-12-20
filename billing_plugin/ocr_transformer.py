"""
OCR → Billing Transformer

Input:
- Raw OCR text (string)

Output:
- List of structured line items with confidence scores

This module:
- DOES NOT create invoices
- DOES NOT touch DB
- DOES NOT enforce accounting rules
"""

import re
from typing import List, Dict


COMMON_UNITS = [
    "kg", "kgs", "gm", "g", "ltr", "l", "ml",
    "pcs", "pc", "nos", "no", "units"
]


PRICE_REGEX = re.compile(r"(\d+(?:\.\d{1,2})?)")
QTY_REGEX = re.compile(r"(\d+(?:\.\d+)?)")


def extract_line_items(ocr_text: str) -> List[Dict]:
    """
    Extract probable line items from OCR text.

    Returns list of:
    {
        name: str
        quantity: float | None
        unit_price: float | None
        confidence: float (0–1)
        raw_line: str
    }
    """

    if not ocr_text or not isinstance(ocr_text, str):
        return []

    lines = _clean_lines(ocr_text)
    items = []

    for line in lines:
        item = _parse_line(line)
        if item:
            items.append(item)

    return items


# -------------------------
# Helpers
# -------------------------

def _clean_lines(text: str) -> List[str]:
    """
    Normalize OCR text into candidate lines.
    """
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if len(line) < 4:
            continue
        # ignore headers / totals heuristically
        if any(x in line.lower() for x in ["total", "subtotal", "amount due", "grand total"]):
            continue
        lines.append(line)
    return lines


def _parse_line(line: str) -> Dict | None:
    """
    Attempt to parse a single OCR line.
    """

    confidence = 0.0
    original_line = line

    # Extract prices
    prices = PRICE_REGEX.findall(line)
    price = None

    if prices:
        price = float(prices[-1])  # usually last number is price
        confidence += 0.4
        line = line.replace(prices[-1], "").strip()

    # Extract quantity
    qty = None
    qty_match = QTY_REGEX.search(line)
    if qty_match:
        try:
            qty = float(qty_match.group(1))
            confidence += 0.2
            line = line.replace(qty_match.group(1), "").strip()
        except Exception:
            pass

    # Extract unit
    unit_found = False
    for unit in COMMON_UNITS:
        if re.search(rf"\b{unit}\b", line.lower()):
            confidence += 0.1
            unit_found = True
            line = re.sub(rf"\b{unit}\b", "", line, flags=re.IGNORECASE)
            break

    # Remaining text is name candidate
    name = re.sub(r"[^a-zA-Z0-9\s]", "", line).strip()

    if not name:
        return None

    # Confidence normalization
    confidence = min(round(confidence, 2), 1.0)

    # Weak lines filtered
    if confidence < 0.3:
        return None

    return {
        "name": name,
        "quantity": qty,
        "unit_price": price,
        "confidence": confidence,
        "raw_line": original_line
    }
