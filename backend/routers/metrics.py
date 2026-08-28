from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session
from backend.models import Dispute, MetricsSummary
from backend.utils.helpers import paise_to_rupees

router = APIRouter(prefix="/api")

_EVIDENCE_FIELDS = (
    "payment_data_json",
    "order_data_json",
    "shipping_data_json",
    "comms_data_json",
    "refund_data_json",
    "explanation_letter",
)
_SUBMITTED_STATUSES = frozenset({"submitted", "won", "lost"})


@router.get("/metrics/summary", response_model=MetricsSummary)
async def metrics_summary(session: AsyncSession = Depends(get_session)) -> MetricsSummary:
    rows = (await session.execute(select(Dispute))).scalars().all()
    total = len(rows)
    if total == 0:
        return MetricsSummary(
            total_disputes=0,
            by_status={},
            by_reason_code={},
            avg_processing_time_seconds=0.0,
            evidence_coverage_rate=0.0,
            submission_rate=0.0,
            total_amount_disputed_rupees=0.0,
            total_amount_contested_rupees=0.0,
        )

    by_status = dict(Counter(d.status for d in rows))
    by_reason_code = dict(Counter(d.reason_code for d in rows))

    times = [
        (d.processing_completed_at - d.processing_started_at).total_seconds()
        for d in rows
        if d.processing_started_at and d.processing_completed_at
    ]
    avg_time = sum(times) / len(times) if times else 0.0

    filled = 0
    possible = total * len(_EVIDENCE_FIELDS)
    for d in rows:
        for field in _EVIDENCE_FIELDS:
            if getattr(d, field):
                filled += 1
    coverage = filled / possible if possible else 0.0

    submitted = [d for d in rows if d.status in _SUBMITTED_STATUSES]
    submission_rate = len(submitted) / total
    disputed = paise_to_rupees(sum(d.amount_paise for d in rows))
    contested = paise_to_rupees(sum(d.amount_paise for d in submitted))

    return MetricsSummary(
        total_disputes=total,
        by_status=by_status,
        by_reason_code=by_reason_code,
        avg_processing_time_seconds=avg_time,
        evidence_coverage_rate=coverage,
        submission_rate=submission_rate,
        total_amount_disputed_rupees=disputed,
        total_amount_contested_rupees=contested,
    )
