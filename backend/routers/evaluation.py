from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session
from backend.models import Dispute, TransactionRisk
from backend.services.evaluation import compute_evaluation_metrics

router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])


@router.get("/report")
async def evaluation_report(session: AsyncSession = Depends(get_session)) -> dict:
    disputes = (await session.execute(select(Dispute))).scalars().all()
    risks = (await session.execute(select(TransactionRisk))).scalars().all()
    report = await compute_evaluation_metrics(list(risks), list(disputes))
    return report.to_dict()
