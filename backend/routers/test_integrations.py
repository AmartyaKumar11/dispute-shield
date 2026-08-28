from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.database import get_session
from backend.models import Dispute
from backend.providers.email_provider import email_provider
from backend.providers.shiprocket_provider import shiprocket
from backend.services.escalation_engine import send_resolution_offer
from backend.utils.helpers import paise_to_rupees

router = APIRouter(prefix="/api/test", tags=["test"])


class SendEmailBody(BaseModel):
    to_email: str
    subject: str = "DisputeShield Test"
    message: str = "This is a test intervention message."


class ShiprocketOrderBody(BaseModel):
    product_name: str = "Wireless Headphones"
    amount: float = 1200
    customer_name: str = "Test Customer"
    customer_email: str
    customer_phone: str = "9876543210"
    delivery_pincode: str = "122413"
    billing_city: str = "Gurugram"
    billing_state: str = "Haryana"
    billing_address: str = "Test Address, Sector 1"


class ResolutionBody(BaseModel):
    message: str | None = None


@router.post("/send-email")
async def test_send_email(body: SendEmailBody) -> dict:
    if not settings.smtp_user or not settings.smtp_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SMTP not configured - set SMTP_USER and SMTP_PASSWORD in .env",
        )
    ok = await email_provider.send_intervention_email(
        to_email=body.to_email,
        customer_name=body.to_email.split("@")[0],
        order_id="TEST-ORDER",
        intervention_message=body.message,
        product_name="Demo Product",
        amount=1200.0,
    )
    if not ok:
        # Fallback plain send with custom subject
        ok = await email_provider.send_email(
            to_email=body.to_email,
            subject=body.subject,
            body_html=f"<p>{body.message}</p>",
            body_text=body.message,
        )
    return {"sent": ok, "to": body.to_email, "subject": body.subject}


@router.post("/create-shiprocket-order")
async def test_create_shiprocket_order(body: ShiprocketOrderBody) -> dict:
    if not settings.shiprocket_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Shiprocket disabled (SHIPROCKET_ENABLED=false) — unlock account then re-enable",
        )
    if not settings.shiprocket_email or not settings.shiprocket_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Shiprocket not configured - set SHIPROCKET_EMAIL and SHIPROCKET_PASSWORD",
        )
    order_id = f"DS-{int(datetime.now(timezone.utc).timestamp())}"
    order_date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    payload = {
        "order_id": order_id,
        "order_date": order_date,
        "pickup_location": "Primary",
        "billing_customer_name": body.customer_name,
        "billing_last_name": "",
        "billing_address": body.billing_address,
        "billing_city": body.billing_city,
        "billing_pincode": body.delivery_pincode,
        "billing_state": body.billing_state,
        "billing_country": "India",
        "billing_email": body.customer_email,
        "billing_phone": body.customer_phone,
        "shipping_is_billing": True,
        "order_items": [
            {
                "name": body.product_name,
                "sku": f"SKU-{order_id[-6:]}",
                "units": 1,
                "selling_price": body.amount,
            }
        ],
        "payment_method": "Prepaid",
        "sub_total": body.amount,
        "length": 15,
        "breadth": 15,
        "height": 15,
        "weight": 0.5,
    }
    try:
        result = await shiprocket.create_order(payload)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Shiprocket create order failed: {exc}",
        ) from exc
    return {
        "local_order_id": order_id,
        "shiprocket": result,
        "order_id": result.get("order_id") or order_id,
        "shipment_id": result.get("shipment_id"),
    }


@router.post("/disputes/{dispute_id}/send-resolution-offer")
async def test_send_resolution(
    dispute_id: str,
    body: ResolutionBody | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    dispute = await session.get(Dispute, dispute_id)
    if dispute is None:
        raise HTTPException(status_code=404, detail="Dispute not found")
    msg = (body.message if body and body.message else None) or (
        f"We want to resolve your dispute on order {dispute.order_id or dispute.id} "
        f"for ₹{paise_to_rupees(dispute.amount_paise):,.2f}. "
        f"Reply YES to accept a full refund, or tell us how we can help."
    )
    ok = await send_resolution_offer(dispute, msg, session)
    await session.commit()
    return {
        "sent": ok,
        "status": dispute.resolution_offer_status,
        "sent_at": dispute.resolution_offer_sent_at,
        "email": dispute.resolution_offer_email,
    }
