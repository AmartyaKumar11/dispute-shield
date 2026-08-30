from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.models import Dispute, EscalationAlert, EscalationEvent, TransactionRisk
from backend.providers.email_provider import email_provider

log = structlog.get_logger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def append_state_history(alert: EscalationAlert, state: str, note: str) -> None:
    history: list = []
    try:
        history = json.loads(alert.state_history_json or "[]")
    except json.JSONDecodeError:
        history = []
    if not isinstance(history, list):
        history = []
    history.append({"state": state, "note": note, "at": _now().isoformat()})
    alert.state_history_json = json.dumps(history[-40:])


async def update_evidence_vault(
    db: AsyncSession,
    order_id: str | None,
    evidence_type: str,
    evidence_data: dict,
    source: str,
) -> None:
    if not order_id:
        return
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
    if evidence_type not in fields:
        fields.append(evidence_type)
    timeline.append(
        {
            "day": "live",
            "at": _now().isoformat(),
            "text": (
                f"Shiprocket — {evidence_type}: {evidence_data.get('status', 'updated')} "
                f"via {evidence_data.get('carrier', 'courier')} ({source})"
            ),
            "ok": True,
        }
    )
    risk.vault_fields_json = json.dumps(list(dict.fromkeys(fields)))
    risk.vault_timeline_json = json.dumps(timeline[-30:])
    log.info("vault.updated", order_id=order_id, evidence_type=evidence_type, source=source)


async def fire_escalation_rule(
    db: AsyncSession,
    *,
    rule_id: str,
    event: EscalationEvent,
    order_id: str | None,
    signal_detail: str,
    severity: str = "high",
) -> EscalationAlert:
    risk = None
    if order_id:
        risk = (
            await db.execute(select(TransactionRisk).where(TransactionRisk.order_id == order_id))
        ).scalar_one_or_none()

    customer_email = None
    amount = 0
    product = "Your order"
    if risk and risk.payment_data_json:
        try:
            payment = json.loads(risk.payment_data_json)
            customer_email = payment.get("email")
            amount = int(payment.get("amount") or risk.amount_paise or 0)
            notes = payment.get("notes") or {}
            product = notes.get("product") or product
        except json.JSONDecodeError:
            pass

    intervention = (
        f"We noticed a delivery issue on your order ({signal_detail}). "
        f"We're already working with the courier and can help with a replacement "
        f"or refund — just reply to this email."
    )

    alert = EscalationAlert(
        id=str(uuid4()),
        rule_id=rule_id,
        event_id=event.id,
        order_id=order_id,
        payment_id=risk.payment_id if risk else None,
        customer_email=customer_email,
        transaction_amount=amount,
        product_name=product,
        severity=severity,
        signal_detail=signal_detail,
        intervention_message=intervention,
        state="OPEN",
        state_history_json=json.dumps(
            [{"state": "OPEN", "note": signal_detail, "at": _now().isoformat()}]
        ),
        created_at=_now(),
    )
    db.add(alert)
    await db.flush()
    await execute_intervention(alert, db)
    return alert


async def execute_intervention(alert: EscalationAlert, db: AsyncSession) -> bool:
    """Send intervention email when configured; otherwise log dry-run."""
    if not alert.intervention_message:
        return False

    to_email = alert.customer_email
    if settings.send_real_emails and settings.smtp_user:
        to_email = settings.smtp_user

    if not to_email:
        append_state_history(alert, alert.state, "No customer email — skipped")
        return False

    can_send = bool(
        settings.send_real_emails and settings.smtp_user and settings.smtp_password
    )
    if not can_send:
        log.info("email.dry_run", to=to_email, order_id=alert.order_id, kind="intervention")
        alert.intervention_email_status = "dry_run"
        append_state_history(alert, alert.state, f"Would have sent email to {to_email}")
        if alert.payment_id:
            risk_row = (
                await db.execute(
                    select(TransactionRisk).where(TransactionRisk.payment_id == alert.payment_id)
                )
            ).scalar_one_or_none()
            if risk_row is not None:
                risk_row.intervention_email_status = "dry_run"
                risk_row.intervention_message = alert.intervention_message
                risk_row.customer_email = to_email
        return False

    portal_url = None
    if alert.order_id:
        try:
            from backend.services.portal_token import generate_token_for_session

            token = await generate_token_for_session(
                db, alert.order_id, alert.payment_id, to_email
            )
            portal_url = f"{settings.frontend_url.rstrip('/')}/resolve/{token}"
        except Exception:
            log.exception("portal.link_for_email_failed")

    success = await email_provider.send_intervention_email(
        to_email=to_email,
        customer_name=(to_email.split("@")[0] if to_email else "Customer"),
        order_id=alert.order_id or "N/A",
        intervention_message=alert.intervention_message,
        product_name=alert.product_name or "Your order",
        amount=(alert.transaction_amount or 0) / 100,
        portal_url=portal_url,
    )

    risk_row = None
    if alert.payment_id:
        risk_row = (
            await db.execute(
                select(TransactionRisk).where(TransactionRisk.payment_id == alert.payment_id)
            )
        ).scalar_one_or_none()

    if success:
        alert.intervention_sent_at = _now()
        alert.intervention_email_status = "sent"
        alert.state = "INTERVENING"
        append_state_history(alert, "INTERVENING", "Intervention email sent successfully")
        if risk_row is not None:
            risk_row.intervention_sent_at = alert.intervention_sent_at
            risk_row.intervention_email_status = "sent"
            risk_row.intervention_message = alert.intervention_message
            risk_row.customer_email = to_email
    else:
        alert.intervention_email_status = "failed"
        append_state_history(alert, alert.state, "Email send failed — will retry")
        if risk_row is not None:
            risk_row.intervention_email_status = "failed"
            risk_row.intervention_message = alert.intervention_message
            risk_row.customer_email = to_email
    return success


async def send_resolution_offer(
    dispute: Dispute,
    resolution_message: str,
    db: AsyncSession,
) -> bool:
    customer_email = None
    product = "Your order"
    if dispute.payment_data_json:
        try:
            payment_data = json.loads(dispute.payment_data_json)
            customer_email = payment_data.get("email")
            notes = payment_data.get("notes") or {}
            product = notes.get("product") or product
        except json.JSONDecodeError:
            customer_email = None

    if settings.send_real_emails and settings.smtp_user:
        customer_email = settings.smtp_user

    if not customer_email:
        dispute.resolution_offer_status = "no_email"
        return False

    can_send = bool(
        settings.send_real_emails and settings.smtp_user and settings.smtp_password
    )
    if not can_send:
        log.info("email.dry_run", to=customer_email, dispute_id=dispute.id, kind="resolution")
        dispute.resolution_message = resolution_message
        dispute.resolution_offer_status = "dry_run"
        return False

    subject = f"Regarding your recent dispute — Order {dispute.order_id or dispute.id}"
    body_html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
        <div style="background: #fff3e0; padding: 20px; border-radius: 8px; margin-bottom: 20px;">
            <h2 style="color: #e65100; margin: 0 0 10px 0;">We want to make this right</h2>
            <p style="color: #666; margin: 0; font-size: 14px;">
                Dispute for ₹{dispute.amount_paise / 100:,.2f} · {product}
            </p>
        </div>
        <div style="padding: 0 10px; line-height: 1.6; color: #333;">
            {resolution_message.replace(chr(10), '<br/>')}
        </div>
        <div style="margin-top: 30px; padding: 15px; background: #e3f2fd; border-radius: 8px; text-align: center;">
            <p style="margin: 0; color: #1565c0; font-size: 14px;">
                <strong>Reply YES</strong> to accept this offer, or reply with any questions.
                We'll respond within 24 hours.
            </p>
        </div>
        <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #eee; color: #999; font-size: 12px; text-align: center;">
            Sent by DisputeShield on behalf of the merchant
        </div>
    </div>
    """
    success = await email_provider.send_email(
        to_email=customer_email,
        subject=subject,
        body_html=body_html,
        body_text=resolution_message,
    )
    dispute.resolution_message = resolution_message
    if success:
        dispute.resolution_offer_sent_at = _now()
        dispute.resolution_offer_status = "sent"
        dispute.resolution_offer_email = customer_email
    else:
        dispute.resolution_offer_status = "failed"
        dispute.resolution_offer_email = customer_email
    return success


async def create_seed_intervention(
    db: AsyncSession,
    *,
    risk: TransactionRisk,
    message: str,
) -> EscalationAlert:
    event = EscalationEvent(
        id=str(uuid4()),
        source="seed",
        event_type="seed.intervention",
        order_id=risk.order_id,
        payload_json=json.dumps({"payment_id": risk.payment_id}),
        received_at=_now(),
        processed=1,
    )
    db.add(event)
    await db.flush()

    email = None
    product = "Your order"
    if risk.payment_data_json:
        try:
            payment = json.loads(risk.payment_data_json)
            email = payment.get("email")
            product = (payment.get("notes") or {}).get("product") or product
        except json.JSONDecodeError:
            pass

    alert = EscalationAlert(
        id=str(uuid4()),
        rule_id="seed_high_risk",
        event_id=event.id,
        order_id=risk.order_id,
        payment_id=risk.payment_id,
        customer_email=email,
        transaction_amount=risk.amount_paise,
        product_name=product,
        severity="high" if risk.risk_score >= 50 else "medium",
        signal_detail=f"High risk score {risk.risk_score:.0f}",
        intervention_message=message,
        state="OPEN",
        state_history_json=json.dumps(
            [{"state": "OPEN", "note": "Seed intervention", "at": _now().isoformat()}]
        ),
        created_at=_now(),
    )
    db.add(alert)
    await db.flush()
    await execute_intervention(alert, db)
    return alert
