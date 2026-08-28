from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session
from backend.models import Dispute, TransactionRisk
from backend.services.intelligence import generate_dispute_insights

router = APIRouter(prefix="/api/intelligence", tags=["intelligence"])


@router.get("/insights")
async def get_insights(session: AsyncSession = Depends(get_session)) -> dict:
    disputes = (await session.execute(select(Dispute))).scalars().all()
    risks = (await session.execute(select(TransactionRisk))).scalars().all()
    insights = await generate_dispute_insights(list(disputes), list(risks))
    return insights.to_dict()
