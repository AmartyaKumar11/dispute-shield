from __future__ import annotations

import json
from collections import Counter

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session
from backend.models import Dispute, MetricsSummary
from backend.services.evidence_strategy import evaluate_evidence_coverage, get_strategy
from backend.utils.helpers import paise_to_rupees

router = APIRouter(prefix="/api")

_SUBMITTED_STATUSES = frozenset({"submitted", "won", "lost"})


def _parse_strategy(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _dispute_coverage(dispute: Dispute) -> float:
    strategy_data = _parse_strategy(dispute.evidence_strategy)
    if "coverage" in strategy_data and isinstance(strategy_data["coverage"], (int, float)):
        return float(strategy_data["coverage"])
    strategy = get_strategy(dispute.reason_code)
    gathered: set[str] = set()
    if dispute.explanation_letter:
        gathered.add("explanation_letter")
    if dispute.documents_uploaded:
        try:
            docs = json.loads(dispute.documents_uploaded)
            if isinstance(docs, dict):
                gathered.update(docs.keys())
        except json.JSONDecodeError:
            pass
    gaps = set(strategy_data.get("evidence_gaps") or [])
    for field in [*strategy.required_evidence, *strategy.recommended_evidence]:
        if field in gaps:
            continue
        if dispute.status in {"assembled", "submitting", "submitted", "won", "lost"}:
            gathered.add(field)
    return evaluate_evidence_coverage(strategy, gathered)


def _processing_seconds(dispute: Dispute) -> float | None:
    if not dispute.processing_completed_at:
        return None
    start = dispute.created_at or dispute.processing_started_at
    if not start:
        return None
    return (dispute.processing_completed_at - start).total_seconds()


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

    times = [t for d in rows if (t := _processing_seconds(d)) is not None]
    avg_time = sum(times) / len(times) if times else 0.0

    coverages = [_dispute_coverage(d) for d in rows]
    coverage = sum(coverages) / len(coverages) if coverages else 0.0

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
