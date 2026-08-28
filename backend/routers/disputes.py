from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session
from backend.models import Dispute, DisputeListResponse, DisputeResponse
from backend.services.dispute_service import accept_dispute, force_submit_dispute, process_dispute

router = APIRouter(prefix="/api")


@router.get("/disputes", response_model=DisputeListResponse)
async def list_disputes(
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> DisputeListResponse:
    stmt = select(Dispute).order_by(Dispute.created_at.desc()).limit(limit)
    if status_filter:
        stmt = stmt.where(Dispute.status == status_filter)
    rows = (await session.execute(stmt)).scalars().all()
    return DisputeListResponse(
        disputes=[row.to_response() for row in rows],
        total=len(rows),
    )


@router.get("/disputes/{dispute_id}", response_model=DisputeResponse)
async def get_dispute(
    dispute_id: str,
    session: AsyncSession = Depends(get_session),
) -> DisputeResponse:
    dispute = await session.get(Dispute, dispute_id)
    if dispute is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dispute not found")
    return dispute.to_response()


@router.post("/disputes/{dispute_id}/retry")
async def retry_dispute(
    dispute_id: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> dict:
    dispute = await session.get(Dispute, dispute_id)
    if dispute is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dispute not found")
    if dispute.status != "error":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Retry is only allowed when status is error",
        )
    background_tasks.add_task(process_dispute, dispute_id)
    return {"status": "retrying", "id": dispute_id}


@router.post("/disputes/{dispute_id}/force-submit")
async def force_submit(
    dispute_id: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> dict:
    dispute = await session.get(Dispute, dispute_id)
    if dispute is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dispute not found")
    if dispute.status not in {"review", "accepted"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Force submit only for review or accepted disputes",
        )
    background_tasks.add_task(force_submit_dispute, dispute_id)
    return {"status": "submitting", "id": dispute_id}


@router.post("/disputes/{dispute_id}/accept")
async def accept(
    dispute_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    dispute = await session.get(Dispute, dispute_id)
    if dispute is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dispute not found")
    try:
        await accept_dispute(dispute_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"status": "accepted", "id": dispute_id}
