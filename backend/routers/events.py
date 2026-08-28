from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session
from backend.models import EscalationEvent
from backend.services.escalation_engine import fire_escalation_rule, update_evidence_vault

router = APIRouter()


@router.post("/webhooks/shiprocket")
async def shiprocket_webhook(
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> dict:
    payload = await request.json()
    order_id = str(payload.get("order_id") or payload.get("sr_order_id") or "")
    status = str(payload.get("current_status") or payload.get("shipment_status") or "").upper()

    event = EscalationEvent(
        id=str(uuid4()),
        source="shiprocket",
        event_type=f"shipment.{status.lower().replace(' ', '_') or 'unknown'}",
        order_id=order_id or None,
        payload_json=json.dumps(payload),
        received_at=datetime.now(timezone.utc).replace(tzinfo=None),
        processed=0,
    )
    db.add(event)
    await db.flush()

    if status in ("RTO", "RTO INITIATED", "LOST", "CANCELED", "CANCELLED"):
        await fire_escalation_rule(
            db=db,
            rule_id="delivery_overdue",
            event=event,
            order_id=order_id or None,
            signal_detail=(
                f"Shipment {status} — delivery failed via "
                f"{payload.get('courier_name', 'unknown')}"
            ),
            severity="urgent",
        )
    elif "DELIVERED" in status:
        await update_evidence_vault(
            db=db,
            order_id=order_id or None,
            evidence_type="shipping_proof",
            evidence_data={
                "status": "delivered",
                "delivered_at": payload.get("delivered_date"),
                "carrier": payload.get("courier_name"),
                "awb": payload.get("awb_code"),
                "signed_by": payload.get("delivered_to"),
            },
            source="shiprocket_webhook",
        )

    event.processed = 1
    await db.commit()
    return {"status": "ok"}
