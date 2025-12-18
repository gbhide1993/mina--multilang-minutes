"""
Invoice data model for Billing Plugin

- In-memory representation only
- No DB coupling
- Designed to sit between OCR → workflows
"""

from typing import List, Dict, Optional
from datetime import datetime


class Invoice:
    """
    Minimal, extensible Invoice model.

    This model is intentionally:
    - schema-light
    - validation-soft (non-blocking)
    - storage-agnostic
    """

    def __init__(
        self,
        vendor_name: Optional[str] = None,
        invoice_number: Optional[str] = None,
        invoice_date: Optional[str] = None,
        currency: str = "INR",
        line_items: Optional[List[Dict]] = None,
        subtotal: Optional[float] = None,
        tax_amount: Optional[float] = None,
        total_amount: Optional[float] = None,
        raw_text: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ):
        self.vendor_name = vendor_name
        self.invoice_number = invoice_number
        self.invoice_date = invoice_date
        self.currency = currency

        self.line_items = line_items or []
        self.subtotal = subtotal
        self.tax_amount = tax_amount
        self.total_amount = total_amount

        self.raw_text = raw_text
        self.metadata = metadata or {}

        # Non-blocking validation
        self.validation_warnings = []
        self._validate()

    # -------------------------
    # Validation (soft)
    # -------------------------

    def _validate(self):
        """
        Collect warnings but DO NOT raise exceptions.
        """

        if not self.vendor_name:
            self.validation_warnings.append("Missing vendor_name")

        if not self.invoice_number:
            self.validation_warnings.append("Missing invoice_number")

        if self.invoice_date:
            if not self._is_valid_date(self.invoice_date):
                self.validation_warnings.append("invoice_date format invalid")

        if self.line_items and not isinstance(self.line_items, list):
            self.validation_warnings.append("line_items should be a list")

        if self.total_amount is not None and self.total_amount < 0:
            self.validation_warnings.append("total_amount cannot be negative")

    @staticmethod
    def _is_valid_date(value: str) -> bool:
        """
        Accepts YYYY-MM-DD or DD/MM/YYYY (loose check).
        """
        for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
            try:
                datetime.strptime(value, fmt)
                return True
            except Exception:
                continue
        return False

    # -------------------------
    # Helpers
    # -------------------------

    def calculate_total(self) -> float:
        """
        Calculate total from line items + tax (if available).

        Does NOT enforce GST or tax rules.
        """
        total = 0.0

        for item in self.line_items:
            try:
                qty = float(item.get("quantity", 1))
                price = float(item.get("unit_price", 0))
                total += qty * price
            except Exception:
                # Skip malformed line items
                continue

        if self.tax_amount:
            try:
                total += float(self.tax_amount)
            except Exception:
                pass

        return round(total, 2)

    def is_complete(self) -> bool:
        """
        Basic completeness check (heuristic).
        """
        return bool(
            self.vendor_name
            and self.invoice_number
            and (self.total_amount or self.line_items)
        )

    # -------------------------
    # Serialization helpers
    # -------------------------

    def to_dict(self) -> Dict:
        """
        Convert invoice to plain dict (safe for JSON / DB storage).
        """
        return {
            "vendor_name": self.vendor_name,
            "invoice_number": self.invoice_number,
            "invoice_date": self.invoice_date,
            "currency": self.currency,
            "line_items": self.line_items,
            "subtotal": self.subtotal,
            "tax_amount": self.tax_amount,
            "total_amount": self.total_amount,
            "raw_text": self.raw_text,
            "metadata": self.metadata,
            "validation_warnings": self.validation_warnings,
        }

    @classmethod
    def from_dict(cls, data: Dict):
        """
        Create Invoice from dict (OCR output, API payload, etc.)
        """
        return cls(
            vendor_name=data.get("vendor_name"),
            invoice_number=data.get("invoice_number"),
            invoice_date=data.get("invoice_date"),
            currency=data.get("currency", "INR"),
            line_items=data.get("line_items"),
            subtotal=data.get("subtotal"),
            tax_amount=data.get("tax_amount"),
            total_amount=data.get("total_amount"),
            raw_text=data.get("raw_text"),
            metadata=data.get("metadata"),
        )
