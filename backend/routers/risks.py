from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session
from backend.models import (
    Dispute,
    RiskListResponse,
    RiskResponse,
    RiskSummary,
    TransactionRisk,
)

router = APIRouter(prefix="/api/risks", tags=["risks"])


@router.get("/summary", response_model=RiskSummary)
async def risks_summary(session: AsyncSession = Depends(get_session)) -> RiskSummary:
    rows = (await session.execute(select(TransactionRisk))).scalars().all()
    by_level: dict[str, int] = {}
    for r in rows:
        by_level[r.risk_level] = by_level.get(r.risk_level, 0) + 1
    high = by_level.get("high", 0) + by_level.get("critical", 0)
    became = sum(1 for r in rows if r.alert_status == "dispute_filed")
    # Accuracy: high/critical that became disputes / all dispute_filed (or high-risk flagged)
    flagged = [r for r in rows if r.risk_level in {"high", "critical"}]
    true_pos = sum(1 for r in flagged if r.alert_status == "dispute_filed")
    accuracy = (true_pos / len(flagged)) if flagged else 0.0
    avg = (sum(r.risk_score for r in rows) / len(rows)) if rows else 0.0
    return RiskSummary(
        total_transactions=len(rows),
        by_level=by_level,
        high_risk_count=high,
        alerts_that_became_disputes=became,
        prediction_accuracy=round(accuracy, 3),
        avg_risk_score=round(avg, 2),
    )


@router.get("", response_model=RiskListResponse)
async def list_risks(session: AsyncSession = Depends(get_session)) -> RiskListResponse:
    rows = (
        await session.execute(select(TransactionRisk).order_by(TransactionRisk.risk_score.desc()))
    ).scalars().all()
    disputes = (await session.execute(select(Dispute))).scalars().all()
    by_pay = {d.payment_id: d.id for d in disputes}
    return RiskListResponse(
        risks=[r.to_response(dispute_id=by_pay.get(r.payment_id)) for r in rows],
        total=len(rows),
    )


@router.get("/{payment_id}", response_model=RiskResponse)
async def get_risk(
    payment_id: str,
    session: AsyncSession = Depends(get_session),
) -> RiskResponse:
    row = (
        await session.execute(select(TransactionRisk).where(TransactionRisk.payment_id == payment_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Risk not found")
    dispute = (
        await session.execute(select(Dispute).where(Dispute.payment_id == payment_id))
    ).scalar_one_or_none()
    return row.to_response(dispute_id=dispute.id if dispute else None)
