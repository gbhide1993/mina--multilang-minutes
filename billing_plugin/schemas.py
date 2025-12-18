"""
Schemas and data contracts for billing plugin
"""

# TODO: convert to Pydantic models if validation layer is added

INVOICE_OCR_OUTPUT = {
    "vendor_name": None,
    "invoice_number": None,
    "invoice_date": None,
    "total_amount": None,
    "tax_amount": None,
    "currency": None,
    "line_items": [],
    "raw_text": None
}

BILLING_CONTEXT_KEYS = [
    "phone",
    "message_id",
    "media_url",
    "source",
    "timestamp"
]
