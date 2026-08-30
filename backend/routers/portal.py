from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.database import get_session
from backend.models import (
    ChatRequest,
    ChatResponse,
    GenerateLinkRequest,
    GenerateLinkResponse,
    PortalMetricsResponse,
    RefundRequest,
    RefundResponse,
    ReplacementRequest,
    ReplacementResponse,
    TransactionRisk,
)
from backend.services.portal_service import (
    build_status_response,
    compute_portal_metrics,
    process_chat,
    process_refund,
    process_replacement,
    sessions_for_order,
)
from backend.services.portal_token import generate_token_for_session

router = APIRouter(prefix="/api/portal", tags=["portal"])


@router.post("/generate-link", response_model=GenerateLinkResponse)
async def generate_link(
    body: GenerateLinkRequest,
    session: AsyncSession = Depends(get_session),
) -> GenerateLinkResponse:
    token = await generate_token_for_session(
        session,
        body.order_id,
        body.payment_id,
        body.customer_email,
    )
    await session.commit()
    base = settings.frontend_url.rstrip("/")
    return GenerateLinkResponse(portal_url=f"{base}/resolve/{token}", token=token)


@router.get("/metrics", response_model=PortalMetricsResponse)
async def portal_metrics(session: AsyncSession = Depends(get_session)) -> PortalMetricsResponse:
    data = await compute_portal_metrics(session)
    return PortalMetricsResponse(**data)


@router.post("/generate-links-batch")
async def generate_links_batch(session: AsyncSession = Depends(get_session)) -> dict:
    risks = (await session.execute(select(TransactionRisk))).scalars().all()
    links: list[dict] = []
    for risk in risks:
        if not risk.order_id:
            continue
        email = None
        if risk.payment_data_json:
            import json

            try:
                email = json.loads(risk.payment_data_json).get("email")
            except json.JSONDecodeError:
                email = None
        token = await generate_token_for_session(
            session, risk.order_id, risk.payment_id, email or risk.customer_email
        )
        links.append(
            {
                "order_id": risk.order_id,
                "payment_id": risk.payment_id,
                "portal_url": f"{settings.frontend_url.rstrip('/')}/resolve/{token}",
                "token": token,
            }
        )
    await session.commit()
    return {"count": len(links), "links": links}


@router.get("/order/{order_id}/sessions")
async def order_sessions(order_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    rows = await sessions_for_order(session, order_id)
    return {
        "order_id": order_id,
        "sessions": [
            {
                "id": s.id,
                "status": s.status,
                "viewed_order_status": s.viewed_order_status,
                "requested_refund": s.requested_refund,
                "requested_replacement": s.requested_replacement,
                "started_chat": s.started_chat,
                "resolution_type": s.resolution_type,
                "resolution_detail": s.resolution_detail,
                "chat_history": __import__("json").loads(s.chat_history_json or "[]"),
                "dispute_filed_after": s.dispute_filed_after,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "resolved_at": s.resolved_at.isoformat() if s.resolved_at else None,
            }
            for s in rows
        ],
    }


@router.get("/{order_token}/status")
async def portal_status(order_token: str, session: AsyncSession = Depends(get_session)) -> dict:
    data = await build_status_response(session, order_token)
    await session.commit()
    return data


@router.post("/{order_token}/refund", response_model=RefundResponse)
async def portal_refund(
    order_token: str,
    body: RefundRequest,
    session: AsyncSession = Depends(get_session),
) -> RefundResponse:
    result = await process_refund(session, order_token, body.reason, body.detail)
    await session.commit()
    if not result.get("success") and result.get("refund_type") == "none":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.get("message"))
    return RefundResponse(**result)


@router.post("/{order_token}/replacement", response_model=ReplacementResponse)
async def portal_replacement(
    order_token: str,
    body: ReplacementRequest,
    session: AsyncSession = Depends(get_session),
) -> ReplacementResponse:
    if len((body.detail or "").strip()) < 20:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please provide at least 20 characters describing the issue",
        )
    result = await process_replacement(session, order_token, body.reason, body.detail)
    await session.commit()
    return ReplacementResponse(**result)


@router.post("/{order_token}/chat", response_model=ChatResponse)
async def portal_chat(
    order_token: str,
    body: ChatRequest,
    session: AsyncSession = Depends(get_session),
) -> ChatResponse:
    if not (body.message or "").strip():
        raise HTTPException(status_code=400, detail="Message required")
    result = await process_chat(session, order_token, body.message.strip())
    await session.commit()
    return ChatResponse(**result)
