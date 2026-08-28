from __future__ import annotations

import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session
from backend.models import Dispute, WebhookPayload
from backend.services.dispute_service import process_dispute
from backend.utils.helpers import unix_to_naive

router = APIRouter()


@router.post("/webhooks/razorpay", status_code=status.HTTP_200_OK)
async def razorpay_webhook(
    body: WebhookPayload,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> dict:
    dispute_entity = body.payload.get("dispute", {}).get("entity") or {}
    payment_entity = body.payload.get("payment", {}).get("entity") or {}

    dispute_id = dispute_entity.get("id")
    payment_id = dispute_entity.get("payment_id") or payment_entity.get("id")
    amount = dispute_entity.get("amount")
    reason_code = dispute_entity.get("reason_code")
    phase = dispute_entity.get("phase")
    respond_by_ts = dispute_entity.get("respond_by")

    if not all([dispute_id, payment_id, amount is not None, reason_code, phase, respond_by_ts]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook payload missing required dispute fields",
        )

    existing = await session.get(Dispute, dispute_id)
    if existing is not None:
        return {"status": "ok", "id": dispute_id}

    dispute = Dispute(
        id=dispute_id,
        payment_id=payment_id,
        order_id=payment_entity.get("order_id") or dispute_entity.get("order_id"),
        amount_paise=int(amount),
        currency=dispute_entity.get("currency") or payment_entity.get("currency") or "INR",
        reason_code=reason_code,
        phase=phase,
        respond_by=unix_to_naive(int(respond_by_ts)),
        status="received",
        payment_data_json=json.dumps(payment_entity) if payment_entity else None,
    )
    session.add(dispute)
    await session.commit()
    background_tasks.add_task(process_dispute, dispute_id)
    return {"status": "ok", "id": dispute_id}
