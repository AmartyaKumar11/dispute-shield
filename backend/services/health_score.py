from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Dispute, PortalSession, TransactionRisk
from backend.services.portal_service import compute_portal_metrics


def _portal_self_service_score(deflection_rate: float, visits: int) -> float:
    if visits <= 0:
        return 0.0
    if deflection_rate > 0.6:
        return 100.0
    if deflection_rate > 0.4:
        return 80.0
    if deflection_rate > 0.2:
        return 50.0
    return 20.0


async def compute_health_score(db: AsyncSession) -> dict[str, Any]:
    risks = (await db.execute(select(TransactionRisk))).scalars().all()
    disputes = (await db.execute(select(Dispute))).scalars().all()
    portal = await compute_portal_metrics(db)

    flagged = [r for r in risks if r.risk_score >= 50]
    tp = sum(1 for r in flagged if r.alert_status == "dispute_filed")
    precision = (tp / len(flagged)) if flagged else 0.0
    risk_score = round(precision * 100, 1)

    contested = sum(1 for d in disputes if d.status in {"submitted", "won", "lost", "under_review"})
    sub_rate = (contested / len(disputes)) if disputes else 0.0
    submission_score = round(sub_rate * 100, 1)

    vault_counts = []
    for r in risks:
        try:
            import json

            fields = json.loads(r.vault_fields_json or "[]")
            if isinstance(fields, list):
                vault_counts.append(min(len(fields) / 5.0, 1.0))
        except Exception:
            pass
    vault_avg = sum(vault_counts) / len(vault_counts) if vault_counts else 0.0
    vault_score = round(vault_avg * 100, 1)

    auto = sum(1 for d in disputes if d.triage_action == "auto_submit")
    triage_score = round((auto / len(disputes)) * 100, 1) if disputes else 50.0

    self_service = _portal_self_service_score(
        float(portal.get("deflection_rate") or 0),
        int(portal.get("total_portal_visits") or 0),
    )

    win_probs = [d.win_probability for d in disputes if d.win_probability is not None]
    win_score = round(sum(win_probs) / len(win_probs), 1) if win_probs else 50.0

    components = [
        {"id": "vault_coverage", "label": "Evidence vault coverage", "score": vault_score, "weight": 0.25},
        {"id": "risk_precision", "label": "Risk prediction precision", "score": risk_score, "weight": 0.20},
        {"id": "submission_rate", "label": "Contest submission rate", "score": submission_score, "weight": 0.20},
        {"id": "triage_efficiency", "label": "Auto-triage efficiency", "score": triage_score, "weight": 0.15},
        {
            "id": "customer_self_service",
            "label": "Customer self-service",
            "score": self_service,
            "weight": 0.10,
            "detail": {
                "deflection_rate": portal.get("deflection_rate"),
                "portal_visits": portal.get("total_portal_visits"),
            },
        },
        {"id": "win_outlook", "label": "Avg win probability", "score": win_score, "weight": 0.10},
    ]
    overall = round(sum(c["score"] * c["weight"] for c in components), 1)
    return {
        "overall_score": overall,
        "components": components,
        "portal_sessions": len((await db.execute(select(PortalSession))).scalars().all()),
    }
