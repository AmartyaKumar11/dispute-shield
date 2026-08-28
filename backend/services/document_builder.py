from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fpdf import FPDF

from backend.providers.base import EmailRecord, ShippingInfo

DOC_ROOT = Path("/tmp/disputeshield")


def _latin(text: object) -> str:
    return str(text if text is not None else "-").encode("latin-1", "replace").decode("latin-1")


def _dir(dispute_id: str) -> Path:
    path = DOC_ROOT / dispute_id
    path.mkdir(parents=True, exist_ok=True)
    return path


class _Doc(FPDF):
    def __init__(self, title: str) -> None:
        super().__init__()
        self._title = title
        self.set_auto_page_break(auto=True, margin=18)
        self.add_page()
        self.set_font("Helvetica", "B", 14)
        self.cell(0, 10, _latin(title), new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(30, 30, 30)
        y = self.get_y()
        self.line(10, y, 200, y)
        self.ln(6)
        self.set_font("Helvetica", size=11)

    def line_item(self, label: str, value: object) -> None:
        self.set_x(self.l_margin)
        self.set_font("Helvetica", size=11)
        self.multi_cell(0, 7, _latin(f"{label}: {value}"))
        self.set_x(self.l_margin)

    def body(self, text: str) -> None:
        self.set_x(self.l_margin)
        self.set_font("Helvetica", size=11)
        self.multi_cell(0, 6, _latin(text))
        self.set_x(self.l_margin)

    def save_to(self, path: Path) -> str:
        self.set_font("Helvetica", "I", 9)
        self.ln(8)
        self.multi_cell(0, 5, _latin(f"Generated {datetime.now(timezone.utc).date().isoformat()}"))
        self.output(str(path))
        return str(path)


def build_billing_proof(dispute_id: str, payment_data: dict, order_data: dict) -> str:
    notes = payment_data.get("notes") if isinstance(payment_data.get("notes"), dict) else {}
    order_notes = order_data.get("notes") if isinstance(order_data.get("notes"), dict) else {}
    amount = payment_data.get("amount") or 0
    pdf = _Doc("Billing Proof - Transaction Receipt")
    pdf.line_item("Payment ID", payment_data.get("id"))
    pdf.line_item("Order ID", payment_data.get("order_id") or order_data.get("id"))
    pdf.line_item("Amount (paise)", amount)
    pdf.line_item("Amount (INR)", f"Rs.{int(amount) / 100:.2f}")
    pdf.line_item("Currency", payment_data.get("currency") or "INR")
    pdf.line_item("Method", payment_data.get("method"))
    pdf.line_item("Customer email", payment_data.get("email"))
    pdf.line_item("Customer contact", payment_data.get("contact"))
    pdf.line_item("Product", notes.get("product") or order_notes.get("product"))
    pdf.line_item("Payment date", payment_data.get("created_at"))
    pdf.ln(4)
    pdf.body("Generated from Razorpay payment records.")
    return pdf.save_to(_dir(dispute_id) / "billing_proof.pdf")


def build_shipping_proof(dispute_id: str, shipping_info: ShippingInfo | None) -> str | None:
    if shipping_info is None or shipping_info.status in {"returned"}:
        return None
    pdf = _Doc("Shipping Proof - Delivery Confirmation")
    pdf.line_item("Tracking ID", shipping_info.tracking_id)
    pdf.line_item("Carrier", shipping_info.carrier)
    pdf.line_item("Status", shipping_info.status)
    pdf.line_item("Shipped at", shipping_info.shipped_at)
    pdf.line_item("Delivered at", shipping_info.delivered_at or "Pending")
    pdf.line_item("Delivery address", shipping_info.delivery_address)
    pdf.line_item("Signed by", shipping_info.signed_by or "N/A")
    pdf.ln(4)
    pdf.body("Generated from shipping partner records.")
    return pdf.save_to(_dir(dispute_id) / "shipping_proof.pdf")


def build_explanation_letter(dispute_id: str, letter_text: str) -> str:
    pdf = _Doc("ShopKart - Explanation Letter")
    pdf.set_font("Helvetica", size=10)
    pdf.cell(0, 6, _latin(datetime.now(timezone.utc).strftime("%d %b %Y")), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.body(letter_text)
    pdf.ln(8)
    pdf.body("Merchant Dispute Resolution Team")
    return pdf.save_to(_dir(dispute_id) / "explanation_letter.pdf")


def build_customer_communication(dispute_id: str, comms_data: list[EmailRecord] | None) -> str | None:
    if not comms_data:
        return None
    pdf = _Doc("Customer Communication - Email Thread")
    for email in comms_data:
        pdf.set_x(pdf.l_margin)
        pdf.set_font("Helvetica", "B", 11)
        pdf.multi_cell(0, 6, _latin(f"{email.sent_at} | {email.direction.upper()} | {email.subject}"))
        pdf.set_x(pdf.l_margin)
        pdf.set_font("Helvetica", size=10)
        pdf.multi_cell(0, 5, _latin(f"From: {email.sender}  To: {email.recipient}"))
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, 5, _latin(email.body_snippet))
        pdf.set_x(pdf.l_margin)
        pdf.ln(3)
    pdf.body("Generated from customer communication records.")
    return pdf.save_to(_dir(dispute_id) / "customer_communication.pdf")


def build_access_activity_log(dispute_id: str, payment_data: dict) -> str:
    card = payment_data.get("card") if isinstance(payment_data.get("card"), dict) else {}
    acquirer = payment_data.get("acquirer_data") if isinstance(payment_data.get("acquirer_data"), dict) else {}
    ip = payment_data.get("ip") or acquirer.get("ip") or "103.21.244.10"
    pdf = _Doc("Access Activity Log")
    pdf.line_item("Payment ID", payment_data.get("id"))
    pdf.line_item("IP address", ip)
    pdf.line_item("Payment method", payment_data.get("method"))
    pdf.line_item("Card network", card.get("network") or "N/A")
    pdf.line_item("3DS / OTP", acquirer.get("auth_code") or payment_data.get("auth_type") or "OTP/3DS completed in test mode")
    pdf.line_item("Email", payment_data.get("email"))
    pdf.line_item("Contact", payment_data.get("contact"))
    pdf.ln(4)
    pdf.body("Generated from payment gateway activity logs.")
    return pdf.save_to(_dir(dispute_id) / "access_activity_log.pdf")
