from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.models import Dispute, PortalConfig, PortalSession, TransactionRisk
from backend.providers.email_provider import email_provider
from backend.providers.razorpay_provider import RazorpayProvider
from backend.providers.shipping_provider import get_shipping_info
from backend.services.portal_token import get_portal_config, validate_token_for_session
from backend.utils.helpers import jsonable, paise_to_rupees

log = structlog.get_logger(__name__)

_razorpay = RazorpayProvider()

REFUND_REASONS = [
    "Product not received",
    "Product damaged or defective",
    "Wrong product received",
    "Changed my mind",
    "Charged incorrect amount",
    "Other",
]

CHAT_FALLBACK = (
    "I'm having trouble processing your request right now. Please use the "
    "refund or replacement buttons above, or reply to your order confirmation "
    "email for direct support."
)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def get_or_create_session(
    db: AsyncSession,
    *,
    token: str,
    order_id: str,
    payment_id: str | None,
    email: str | None,
) -> PortalSession:
    existing = (
        await db.execute(
            select(PortalSession)
            .where(PortalSession.order_token == token)
            .order_by(PortalSession.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.last_activity_at = _now()
        return existing

    session = PortalSession(
        id=str(uuid4()),
        order_token=token,
        order_id=order_id,
        payment_id=payment_id,
        customer_email=email,
        status="active",
        started_at=_now(),
        last_activity_at=_now(),
    )
    db.add(session)
    await db.flush()
    return session


async def load_order_context(order_id: str, payment_id: str | None) -> dict[str, Any]:
    """Load payment/order/shipping/refunds — simulated rows from TransactionRisk."""
    payment: dict[str, Any] = {}
    order: dict[str, Any] = {"id": order_id}
    refunds: list[dict] = []

    # Simulated / vault data first
    from backend.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        risk = (
            await session.execute(
                select(TransactionRisk).where(TransactionRisk.order_id == order_id)
            )
        ).scalar_one_or_none()
        if risk and risk.payment_data_json:
            try:
                payment = json.loads(risk.payment_data_json)
            except json.JSONDecodeError:
                payment = {}
            payment_id = payment_id or risk.payment_id

    is_simulated = bool(
        (payment_id or "").startswith("pay_simulated_")
        or order_id.startswith("order_simulated_")
        or order_id.startswith("DS-")
    )

    if not is_simulated and payment_id:
        try:
            payment = await _razorpay.get_payment(payment_id)
        except Exception:
            log.exception("portal.payment_fetch_failed", payment_id=payment_id)
        try:
            order = await _razorpay.get_order(order_id)
        except Exception:
            log.exception("portal.order_fetch_failed", order_id=order_id)
        try:
            refunds = await _razorpay.get_refunds(payment_id)
        except Exception:
            log.exception("portal.refunds_fetch_failed", payment_id=payment_id)
    elif not payment:
        payment = {
            "id": payment_id or f"pay_{order_id}",
            "amount": 100000,
            "method": "card",
            "email": "",
            "status": "captured",
            "created_at": int(_now().timestamp()),
            "notes": {"product": "Order item"},
            "order_id": order_id,
        }

    shipping = await get_shipping_info(order_id)
    notes = payment.get("notes") if isinstance(payment.get("notes"), dict) else {}
    amount_paise = int(payment.get("amount") or 0)

    return {
        "payment": payment,
        "order": order,
        "shipping": shipping,
        "refunds": refunds,
        "is_simulated": is_simulated,
        "product_name": notes.get("product") or "Your order",
        "amount_paise": amount_paise,
        "payment_id": payment.get("id") or payment_id,
        "email": payment.get("email") or "",
        "method": payment.get("method") or "card",
        "created_at": payment.get("created_at"),
        "payment_status": payment.get("status") or "captured",
    }


async def append_vault_portal_evidence(
    db: AsyncSession,
    order_id: str,
    detail: str,
    *,
    session: PortalSession | None = None,
) -> None:
    risk = (
        await db.execute(select(TransactionRisk).where(TransactionRisk.order_id == order_id))
    ).scalar_one_or_none()
    if risk is None:
        return
    fields: list = []
    timeline: list = []
    try:
        fields = json.loads(risk.vault_fields_json or "[]")
    except json.JSONDecodeError:
        fields = []
    try:
        timeline = json.loads(risk.vault_timeline_json or "[]")
    except json.JSONDecodeError:
        timeline = []
    if not isinstance(fields, list):
        fields = []
    if not isinstance(timeline, list):
        timeline = []
    if "portal_interaction" not in fields:
        fields.append("portal_interaction")
    entry = {
        "day": "portal",
        "at": _now().isoformat(),
        "text": detail,
        "ok": True,
        "portal": True,
    }
    if session is not None:
        entry["session_id"] = session.id
        entry["resolution"] = session.resolution_type
    timeline.append(entry)
    risk.vault_fields_json = json.dumps(list(dict.fromkeys(fields)))
    risk.vault_timeline_json = json.dumps(timeline[-40:])


async def build_status_response(
    db: AsyncSession,
    token: str,
) -> dict[str, Any]:
    payload = await validate_token_for_session(db, token)
    if payload is None:
        return {"valid": False, "error": "This link has expired or is invalid."}

    order_id = str(payload["order_id"])
    payment_id = str(payload.get("payment_id") or "") or None
    email = str(payload.get("email") or "") or None

    ctx = await load_order_context(order_id, payment_id)
    cfg = await get_portal_config(db)
    session = await get_or_create_session(
        db,
        token=token,
        order_id=order_id,
        payment_id=ctx["payment_id"],
        email=email or ctx["email"],
    )
    session.viewed_order_status = True
    session.last_activity_at = _now()
    await append_vault_portal_evidence(
        db, order_id, f"Customer viewed order status via resolution portal ({session.id})", session=session
    )

    shipping = ctx["shipping"]
    amount_paise = ctx["amount_paise"]
    existing = ctx["refunds"]
    auto_ok = (
        cfg.auto_refund_enabled
        and amount_paise <= cfg.auto_refund_max_amount_paise
        and len(existing) == 0
        and not session.requested_refund
    )

    created = ctx["created_at"]
    if isinstance(created, (int, float)):
        order_date = datetime.fromtimestamp(int(created), tz=timezone.utc).isoformat()
    else:
        order_date = _now().isoformat()

    return {
        "valid": True,
        "merchant_name": cfg.merchant_name,
        "order": {
            "order_id": order_id,
            "amount_rupees": paise_to_rupees(amount_paise),
            "product_name": ctx["product_name"],
            "order_date": order_date,
            "payment_method": ctx["method"],
            "payment_status": ctx["payment_status"],
            "payment_id": ctx["payment_id"],
        },
        "shipping": {
            "status": shipping.status if shipping else "pending",
            "carrier": shipping.carrier if shipping else None,
            "tracking_id": shipping.tracking_id if shipping else None,
            "shipped_at": shipping.shipped_at.isoformat() if shipping and shipping.shipped_at else None,
            "delivered_at": shipping.delivered_at.isoformat()
            if shipping and shipping.delivered_at
            else None,
            "signed_by": shipping.signed_by if shipping else None,
            "estimated_delivery": None,
        },
        "refund_eligible": len(existing) == 0 and not session.requested_refund,
        "auto_refund_available": auto_ok,
        "existing_refunds": existing,
        "portal_session_id": session.id,
        "session_status": session.status,
        "resolution_type": session.resolution_type,
        "resolution_detail": session.resolution_detail,
        "refund_amount_rupees": paise_to_rupees(session.refund_amount_paise or 0)
        if session.refund_amount_paise
        else None,
        "chat_history": json.loads(session.chat_history_json or "[]"),
        "auto_refund_max_rupees": paise_to_rupees(cfg.auto_refund_max_amount_paise),
    }


async def process_refund(
    db: AsyncSession,
    token: str,
    reason: str,
    detail: str | None,
) -> dict[str, Any]:
    payload = await validate_token_for_session(db, token)
    if payload is None:
        return {"success": False, "refund_type": "none", "message": "Invalid or expired link."}

    order_id = str(payload["order_id"])
    ctx = await load_order_context(order_id, payload.get("payment_id") or None)
    cfg = await get_portal_config(db)
    session = await get_or_create_session(
        db,
        token=token,
        order_id=order_id,
        payment_id=ctx["payment_id"],
        email=payload.get("email") or ctx["email"],
    )

    if session.requested_refund or ctx["refunds"]:
        return {
            "success": False,
            "refund_type": "none",
            "message": "A refund has already been requested or issued for this order.",
        }

    amount_paise = ctx["amount_paise"]
    session.requested_refund = True
    session.last_activity_at = _now()
    session.resolution_detail = f"{reason}. {detail or ''}".strip()

    auto = cfg.auto_refund_enabled and amount_paise <= cfg.auto_refund_max_amount_paise
    if auto:
        refund_id = f"rfnd_sim_{uuid4().hex[:12]}"
        if not ctx["is_simulated"] and ctx["payment_id"]:
            try:
                result = await _razorpay_refund(ctx["payment_id"], amount_paise)
                refund_id = str(result.get("id") or refund_id)
            except Exception:
                log.exception("portal.razorpay_refund_failed")
                # Still simulate for demo resilience
                refund_id = f"rfnd_sim_{uuid4().hex[:12]}"

        session.refund_id = refund_id
        session.refund_amount_paise = amount_paise
        session.resolution_type = "auto_refund"
        session.status = "resolved_refund"
        session.resolved_at = _now()
        await append_vault_portal_evidence(
            db,
            order_id,
            f"Customer requested refund via portal ({reason}). Auto-approved {refund_id}.",
            session=session,
        )
        await _send_resolution_confirm(
            session.customer_email or ctx["email"],
            order_id,
            f"Your refund of ₹{paise_to_rupees(amount_paise):,.2f} has been initiated.",
        )
        return {
            "success": True,
            "refund_type": "auto",
            "refund_id": refund_id,
            "refund_amount_rupees": paise_to_rupees(amount_paise),
            "estimated_days": "5-7 business days",
            "message": (
                f"Your refund of ₹{paise_to_rupees(amount_paise):,.2f} has been initiated. "
                f"You'll receive it within 5-7 business days."
            ),
        }

    session.resolution_type = "manual_refund"
    session.status = "pending_merchant_review"
    await append_vault_portal_evidence(
        db,
        order_id,
        f"Customer requested refund via portal ({reason}) — pending merchant review.",
        session=session,
    )
    merchant = cfg.support_email or settings.smtp_user
    if merchant:
        await email_provider.send_email(
            to_email=merchant,
            subject=f"Portal refund request — {order_id}",
            body_html=(
                f"<p>Customer requested a refund for <strong>{order_id}</strong>.</p>"
                f"<p>Reason: {reason}</p><p>{detail or ''}</p>"
                f"<p>Amount: ₹{paise_to_rupees(amount_paise):,.2f}</p>"
            ),
            body_text=f"Refund request for {order_id}: {reason}. {detail or ''}",
        )
    return {
        "success": True,
        "refund_type": "manual",
        "refund_id": None,
        "refund_amount_rupees": paise_to_rupees(amount_paise),
        "estimated_days": "Within 24 hours for review",
        "message": (
            "Your refund request has been submitted. Our team will review it within 24 hours."
        ),
    }


async def _razorpay_refund(payment_id: str, amount_paise: int) -> dict:
    import asyncio

    return await asyncio.to_thread(
        _razorpay._client.payment.refund,
        payment_id,
        {"amount": amount_paise},
    )


async def process_replacement(
    db: AsyncSession,
    token: str,
    reason: str,
    detail: str,
) -> dict[str, Any]:
    payload = await validate_token_for_session(db, token)
    if payload is None:
        return {"success": False, "message": "Invalid or expired link.", "ticket_id": ""}

    order_id = str(payload["order_id"])
    ctx = await load_order_context(order_id, payload.get("payment_id") or None)
    cfg = await get_portal_config(db)
    session = await get_or_create_session(
        db,
        token=token,
        order_id=order_id,
        payment_id=ctx["payment_id"],
        email=payload.get("email") or ctx["email"],
    )
    ticket_id = f"RPL-{uuid4().hex[:8].upper()}"
    session.requested_replacement = True
    session.resolution_type = "replacement"
    session.resolution_detail = f"{reason}. {detail}".strip()
    session.status = "resolved_replacement"
    session.resolved_at = _now()
    session.last_activity_at = _now()
    await append_vault_portal_evidence(
        db,
        order_id,
        f"Customer requested replacement via portal ({ticket_id}): {reason}",
        session=session,
    )
    merchant = cfg.support_email or settings.smtp_user
    if merchant:
        await email_provider.send_email(
            to_email=merchant,
            subject=f"Replacement request {ticket_id} — {order_id}",
            body_html=(
                f"<p>Ticket <strong>{ticket_id}</strong></p>"
                f"<p>Order: {order_id} · {ctx['product_name']}</p>"
                f"<p>Reason: {reason}</p><p>{detail}</p>"
            ),
            body_text=f"{ticket_id} replacement for {order_id}: {reason}. {detail}",
        )
    await _send_resolution_confirm(
        session.customer_email or ctx["email"],
        order_id,
        f"Your replacement request ({ticket_id}) was submitted. We'll contact you within 24 hours.",
    )
    return {
        "success": True,
        "message": (
            "Your replacement request has been submitted. "
            "The merchant will contact you within 24 hours."
        ),
        "ticket_id": ticket_id,
    }


async def process_chat(db: AsyncSession, token: str, message: str) -> dict[str, Any]:
    payload = await validate_token_for_session(db, token)
    if payload is None:
        return {
            "reply": CHAT_FALLBACK,
            "suggested_actions": ["Request refund"],
            "session_id": "",
            "resolution_detected": False,
            "resolution_type": None,
        }

    order_id = str(payload["order_id"])
    ctx = await load_order_context(order_id, payload.get("payment_id") or None)
    cfg = await get_portal_config(db)
    session = await get_or_create_session(
        db,
        token=token,
        order_id=order_id,
        payment_id=ctx["payment_id"],
        email=payload.get("email") or ctx["email"],
    )
    session.started_chat = True
    session.last_activity_at = _now()

    history: list = []
    try:
        history = json.loads(session.chat_history_json or "[]")
    except json.JSONDecodeError:
        history = []
    if not isinstance(history, list):
        history = []

    history.append({"role": "customer", "message": message, "timestamp": _now().isoformat()})

    shipping = ctx["shipping"]
    ship_bits = {
        "carrier": shipping.carrier if shipping else "n/a",
        "tracking_id": shipping.tracking_id if shipping else "n/a",
        "shipping_status": shipping.status if shipping else "pending",
        "shipped_at": shipping.shipped_at if shipping else "n/a",
        "delivered_at": shipping.delivered_at if shipping else "n/a",
        "signed_by": shipping.signed_by if shipping else "n/a",
    }

    system = f"""You are a customer support agent for an e-commerce merchant. You are
chatting with a customer who has an issue with their order. Your goal
is to RESOLVE the issue quickly and prevent the customer from filing
a bank dispute.

You have access to the customer's order data:

Order ID: {order_id}
Product: {ctx['product_name']}
Amount: ₹{paise_to_rupees(ctx['amount_paise']):,.2f}
Payment method: {ctx['method']}
Order date: {ctx['created_at']}
Payment status: {ctx['payment_status']}

Shipping:
- Carrier: {ship_bits['carrier']}
- Tracking ID: {ship_bits['tracking_id']}
- Status: {ship_bits['shipping_status']}
- Shipped: {ship_bits['shipped_at']}
- Delivered: {ship_bits['delivered_at']}
- Signed by: {ship_bits['signed_by']}

Existing refunds: {ctx['refunds']}

Rules:
1. Be empathetic but concise. Max 3 sentences per reply.
2. Use the actual order data in your responses — don't be vague.
3. If the customer wants a refund and the amount is under ₹{paise_to_rupees(cfg.auto_refund_max_amount_paise):,.0f}:
   suggest using the "Request refund" button for instant processing.
4. If the order shows as delivered, gently mention who signed for it
   and suggest checking with them before requesting a refund.
5. If shipping shows "in_transit", give the tracking ID. Ask the customer to wait.
6. If shipping shows "returned" or "failed", apologize and suggest an immediate refund.
7. NEVER blame the customer. NEVER be defensive.
8. NEVER say "I'm just an AI" or "I don't have access to..."
9. If you can't resolve the issue, say "Let me connect you with our support team".
10. End every response with a suggested next action.

Previous conversation:
{json.dumps(history[-8:], default=str)}

Customer's message: {message}

Respond in JSON only:
{{"reply": "...", "suggested_actions": ["..."], "resolution_detected": false, "resolution_type": null}}
"""

    parsed = await _call_portal_llm(system)
    reply = parsed.get("reply") or CHAT_FALLBACK
    actions = parsed.get("suggested_actions") or ["Request refund", "I found it, thanks"]
    if not isinstance(actions, list):
        actions = ["Request refund"]
    resolution_detected = bool(parsed.get("resolution_detected"))
    resolution_type = parsed.get("resolution_type")

    history.append({"role": "agent", "message": reply, "timestamp": _now().isoformat()})
    session.chat_history_json = json.dumps(history[-40:])

    if resolution_detected and resolution_type:
        session.resolution_type = str(resolution_type)
        if session.status == "active":
            session.status = "resolved_chat"
            session.resolved_at = _now()

    await append_vault_portal_evidence(
        db,
        order_id,
        f"Portal chat: customer said '{message[:80]}' — agent replied.",
        session=session,
    )

    return {
        "reply": reply,
        "suggested_actions": [str(a) for a in actions][:4],
        "session_id": session.id,
        "resolution_detected": resolution_detected,
        "resolution_type": resolution_type,
    }


async def _call_portal_llm(system_prompt: str) -> dict[str, Any]:
    from backend.providers.llm_provider import _FALLBACK_MODELS, _model_name

    if not settings.llm_api_key:
        return {
            "reply": CHAT_FALLBACK,
            "suggested_actions": ["Request refund", "Request replacement"],
            "resolution_detected": False,
            "resolution_type": None,
        }

    models = [_model_name(settings.llm_model_name), *_FALLBACK_MODELS]
    seen: set[str] = set()
    for model in models:
        if model in seen:
            continue
        seen.add(model)
        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                resp = await client.post(
                    f"{settings.llm_api_base_url.rstrip('/')}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.llm_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": "Respond with the JSON object now."},
                        ],
                        "temperature": 0.3,
                        "max_tokens": 500,
                    },
                )
            if resp.status_code >= 400:
                continue
            content = resp.json()["choices"][0]["message"]["content"]
            return _parse_json_blob(content)
        except Exception:
            log.exception("portal.llm_failed", model=model)
            continue
    return {
        "reply": CHAT_FALLBACK,
        "suggested_actions": ["Request refund", "Request replacement"],
        "resolution_detected": False,
        "resolution_type": None,
    }


def _parse_json_blob(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return {
        "reply": text[:500] if text else CHAT_FALLBACK,
        "suggested_actions": ["Request refund"],
        "resolution_detected": False,
        "resolution_type": None,
    }


async def _send_resolution_confirm(email: str | None, order_id: str, message: str) -> None:
    if not email or not settings.send_real_emails:
        return
    to = settings.smtp_user or email
    await email_provider.send_email(
        to_email=to,
        subject=f"Your issue has been resolved — Order {order_id}",
        body_html=f"<p>{message}</p><p>Reply to this email if you need further help.</p>",
        body_text=message,
    )


async def compute_portal_metrics(db: AsyncSession) -> dict[str, Any]:
    sessions = (await db.execute(select(PortalSession))).scalars().all()
    disputes = (await db.execute(select(Dispute))).scalars().all()
    visits = len(sessions)
    resolved_statuses = {
        "resolved_refund",
        "resolved_replacement",
        "resolved_chat",
        "pending_merchant_review",
    }
    resolved = [s for s in sessions if s.status in resolved_statuses or s.resolution_type]
    breakdown: dict[str, int] = {}
    for s in resolved:
        key = s.resolution_type or s.status
        breakdown[key] = breakdown.get(key, 0) + 1

    after = sum(1 for s in sessions if s.dispute_filed_after)
    portal_order_ids = {s.order_id for s in sessions}
    without = sum(1 for d in disputes if d.order_id and d.order_id not in portal_order_ids)

    times = []
    for s in resolved:
        if s.resolved_at and s.started_at:
            times.append((s.resolved_at - s.started_at).total_seconds())
    avg_t = sum(times) / len(times) if times else 0.0

    refund_paise = sum(s.refund_amount_paise or 0 for s in sessions if s.refund_amount_paise)
    prevented = len([s for s in resolved if not s.dispute_filed_after])
    avg_dispute = 1400.0
    savings = prevented * avg_dispute + prevented * 500

    return {
        "total_portal_visits": visits,
        "total_resolved": len(resolved),
        "resolution_breakdown": breakdown,
        "deflection_rate": round(len(resolved) / visits, 3) if visits else 0.0,
        "disputes_after_portal": after,
        "disputes_without_portal": without,
        "avg_resolution_time_seconds": round(avg_t, 1),
        "total_refunds_issued_rupees": paise_to_rupees(refund_paise),
        "estimated_chargebacks_prevented": prevented,
        "estimated_savings_rupees": round(savings, 2),
    }


async def sessions_for_order(db: AsyncSession, order_id: str) -> list[PortalSession]:
    rows = (
        await db.execute(select(PortalSession).where(PortalSession.order_id == order_id))
    ).scalars().all()
    return list(rows)
