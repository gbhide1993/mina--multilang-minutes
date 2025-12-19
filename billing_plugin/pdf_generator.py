"""
Simple Invoice PDF Generator

- Large fonts
- Clean layout
- No external sending
- Returns file path or buffer
"""

from typing import Dict, Any, List, Optional
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Table,
    TableStyle,
    Spacer,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib import colors


def generate_invoice_pdf(
    invoice: Dict[str, Any],
    shop_name: str,
    shop_phone: str,
    upi_note: Optional[str] = None,
    output_path: Optional[str] = None,
):
    """
    Generate invoice PDF.

    Args:
        invoice (dict): Invoice dict (from Invoice.to_dict())
        shop_name (str): Shop / business name
        shop_phone (str): Contact phone
        upi_note (str, optional): UPI / payment note
        output_path (str, optional): If provided, saves PDF to path

    Returns:
        BytesIO or str: PDF buffer or file path
    """

    buffer = BytesIO() if not output_path else output_path

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36,
    )

    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        name="TitleLarge",
        fontSize=20,
        alignment=TA_CENTER,
        spaceAfter=12,
    ))

    styles.add(ParagraphStyle(
        name="SubTitle",
        fontSize=12,
        alignment=TA_CENTER,
        spaceAfter=20,
    ))

    styles.add(ParagraphStyle(
        name="NormalLarge",
        fontSize=11,
        spaceAfter=8,
    ))

    styles.add(ParagraphStyle(
        name="TotalAmount",
        fontSize=14,
        alignment=TA_RIGHT,
        spaceBefore=12,
        spaceAfter=12,
    ))

    elements: List[Any] = []

    # -------------------------
    # Header
    # -------------------------

    elements.append(Paragraph(shop_name, styles["TitleLarge"]))
    elements.append(Paragraph(f"Phone: {shop_phone}", styles["SubTitle"]))

    elements.append(Spacer(1, 12))

    # -------------------------
    # Item Table
    # -------------------------

    table_data = [
        ["#", "Item", "Qty", "Price", "Amount"]
    ]

    subtotal = 0.0
    items = invoice.get("line_items", []) or []

    for idx, item in enumerate(items, start=1):
        name = item.get("name", "")
        qty = item.get("quantity", "")
        price = item.get("unit_price", "")

        amount = ""
        try:
            if qty is not None and price is not None:
                amount_val = float(qty) * float(price)
                amount = f"{amount_val:.2f}"
                subtotal += amount_val
        except Exception:
            pass

        table_data.append([
            str(idx),
            name,
            str(qty) if qty is not None else "",
            f"{price:.2f}" if isinstance(price, (int, float)) else "",
            amount
        ])

    table = Table(
        table_data,
        colWidths=[30, 200, 50, 70, 80]
    )

    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
    ]))

    elements.append(table)

    # -------------------------
    # Totals
    # -------------------------

    currency = invoice.get("currency", "INR")
    tax_amount = invoice.get("tax_amount") or 0.0
    total = round(subtotal + tax_amount, 2)

    elements.append(Spacer(1, 12))
    elements.append(Paragraph(
        f"<b>Total: {currency} {total:.2f}</b>",
        styles["TotalAmount"]
    ))

    # -------------------------
    # Optional UPI Note
    # -------------------------

    if upi_note:
        elements.append(Spacer(1, 20))
        elements.append(Paragraph(
            f"<b>Payment:</b> {upi_note}",
            styles["NormalLarge"]
        ))

    # -------------------------
    # Build PDF
    # -------------------------

    doc.build(elements)

    if output_path:
        return output_path

    buffer.seek(0)
    return buffer
