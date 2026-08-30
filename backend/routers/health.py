from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session
from backend.services.health_score import compute_health_score

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("/score")
async def health_score(session: AsyncSession = Depends(get_session)) -> dict:
    return await compute_health_score(session)
