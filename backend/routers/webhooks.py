from __future__ import annotations

import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session
from backend.models import Dispute, WebhookPayload
from backend.services.dispute_service import process_dispute
from backend.utils.helpers import unix_to_naive

router = APIRouter()


@router.post("/webhooks/razorpay", status_code=status.HTTP_200_OK)
async def razorpay_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> dict:
    try:
        raw = await request.json()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Malformed webhook body: {exc}",
        ) from exc

    try:
        body = WebhookPayload.model_validate(raw)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid webhook payload: {exc.errors()[0].get('msg', 'validation error')}",
        ) from exc

    if not isinstance(body.payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook payload.payload must be an object",
        )

    dispute_entity = (body.payload.get("dispute") or {}).get("entity") or {}
    payment_entity = (body.payload.get("payment") or {}).get("entity") or {}
    if not isinstance(dispute_entity, dict) or not isinstance(payment_entity, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook dispute/payment entity must be objects",
        )

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
        return {"status": "ok", "id": dispute_id, "duplicate": True}

    try:
        amount_paise = int(amount)
        respond_by = unix_to_naive(int(respond_by_ts))
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid amount or respond_by: {exc}",
        ) from exc

    dispute = Dispute(
        id=str(dispute_id),
        payment_id=str(payment_id),
        order_id=payment_entity.get("order_id") or dispute_entity.get("order_id"),
        amount_paise=amount_paise,
        currency=dispute_entity.get("currency") or payment_entity.get("currency") or "INR",
        reason_code=str(reason_code),
        phase=str(phase),
        respond_by=respond_by,
        status="received",
        payment_data_json=json.dumps(payment_entity) if payment_entity else None,
    )
    session.add(dispute)
    await session.commit()
    background_tasks.add_task(process_dispute, dispute.id)
    return {"status": "ok", "id": dispute.id}
