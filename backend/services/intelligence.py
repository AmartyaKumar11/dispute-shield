from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field

import httpx
import structlog

from backend.config import settings
from backend.models import Dispute, TransactionRisk
from backend.providers.llm_provider import _FALLBACK_MODELS, _model_name
from backend.services.evidence_strategy import get_strategy
from backend.utils.helpers import paise_to_rupees

log = structlog.get_logger(__name__)


@dataclass
class ReasonCodeBreakdown:
    reason_code: str
    display_name: str
    count: int
    percentage: float
    avg_amount: float
    win_rate: float


@dataclass
class Hotspot:
    dimension: str
    value: str
    dispute_count: int
    dispute_rate: float
    comparison: str


@dataclass
class Recommendation:
    priority: str
    title: str
    description: str
    estimated_impact: str
    action_type: str


@dataclass
class MerchantInsights:
    total_disputes: int
    total_amount_at_risk: float
    dispute_rate_trend: str
    top_reason_codes: list[ReasonCodeBreakdown] = field(default_factory=list)
    risk_hotspots: list[Hotspot] = field(default_factory=list)
    prevention_recommendations: list[Recommendation] = field(default_factory=list)
    estimated_preventable_disputes: int = 0
    estimated_savings_if_prevented: float = 0.0
    used_fallback: bool = True

    def to_dict(self) -> dict:
        return {
            "total_disputes": self.total_disputes,
            "total_amount_at_risk": self.total_amount_at_risk,
            "dispute_rate_trend": self.dispute_rate_trend,
            "top_reason_codes": [asdict(x) for x in self.top_reason_codes],
            "risk_hotspots": [asdict(x) for x in self.risk_hotspots],
            "prevention_recommendations": [asdict(x) for x in self.prevention_recommendations],
            "estimated_preventable_disputes": self.estimated_preventable_disputes,
            "estimated_savings_if_prevented": self.estimated_savings_if_prevented,
            "used_fallback": self.used_fallback,
        }


async def generate_dispute_insights(
    disputes: list[Dispute],
    risks: list[TransactionRisk],
) -> MerchantInsights:
    base = _rule_insights(disputes, risks)
    try:
        enriched = await _llm_insights(disputes, risks, base)
        if enriched is not None:
            enriched.used_fallback = False
            return enriched
    except Exception:
        log.exception("intelligence.llm_failed")
    return base


def _rule_insights(disputes: list[Dispute], risks: list[TransactionRisk]) -> MerchantInsights:
    total = len(disputes)
    amount = sum(paise_to_rupees(d.amount_paise) for d in disputes)
    by_reason: dict[str, list[Dispute]] = defaultdict(list)
    for d in disputes:
        by_reason[d.reason_code].append(d)

    breakdown: list[ReasonCodeBreakdown] = []
    for code, rows in sorted(by_reason.items(), key=lambda x: -len(x[1])):
        contested = [r for r in rows if r.status in {"submitted", "won", "lost", "review"}]
        won = [r for r in rows if r.status == "won"]
        # proxy win_rate: high win_probability submitted counts as likely wins for demo
        likely = [
            r
            for r in contested
            if (r.win_probability or 0) >= 70 or r.status == "won"
        ]
        win_rate = (len(likely) / len(contested)) if contested else 0.0
        breakdown.append(
            ReasonCodeBreakdown(
                reason_code=code,
                display_name=get_strategy(code).display_name,
                count=len(rows),
                percentage=(len(rows) / total * 100) if total else 0.0,
                avg_amount=sum(paise_to_rupees(r.amount_paise) for r in rows) / len(rows),
                win_rate=round(win_rate * 100, 1),
            )
        )

    txn_total = max(len(risks), 1)
    avg_rate = total / txn_total
    hotspots: list[Hotspot] = []

    carriers: Counter[str] = Counter()
    for d in disputes:
        if d.shipping_data_json:
            try:
                ship = json.loads(d.shipping_data_json)
                carriers[str(ship.get("carrier") or "Unknown")] += 1
            except json.JSONDecodeError:
                pass
    for carrier, count in carriers.most_common(3):
        rate = count / txn_total
        mult = (rate / avg_rate) if avg_rate else 1.0
        hotspots.append(
            Hotspot(
                dimension="carrier",
                value=carrier,
                dispute_count=count,
                dispute_rate=round(rate * 100, 1),
                comparison=f"{mult:.1f}x higher than average" if mult >= 1 else f"{mult:.1f}x of average",
            )
        )

    high_amt = sum(1 for d in disputes if d.amount_paise > 500_000)
    if high_amt:
        rate = high_amt / txn_total
        mult = (rate / avg_rate) if avg_rate else 1.0
        hotspots.append(
            Hotspot(
                dimension="amount_range",
                value="₹5,000+",
                dispute_count=high_amt,
                dispute_rate=round(rate * 100, 1),
                comparison=f"{mult:.1f}x higher than average",
            )
        )

    card_risks = [r for r in risks if _payment_method(r) == "card"]
    card_disputed = sum(1 for r in card_risks if r.alert_status == "dispute_filed")
    if card_risks:
        rate = card_disputed / len(card_risks)
        mult = (rate / avg_rate) if avg_rate else 1.0
        hotspots.append(
            Hotspot(
                dimension="payment_method",
                value="card",
                dispute_count=card_disputed,
                dispute_rate=round(rate * 100, 1),
                comparison=f"{mult:.1f}x vs portfolio average",
            )
        )

    high_risk_became = sum(1 for r in risks if r.risk_level in {"high", "critical"} and r.alert_status == "dispute_filed")
    preventable = max(high_risk_became, len([r for r in risks if r.risk_level == "critical"]))
    savings = amount * 0.35 if total else 0.0

    recs = [
        Recommendation(
            priority="high",
            title="Tighten delivery confirmation on high-value card orders",
            description="Require signature POD for card orders above ₹5,000 and email tracking within 1 hour of dispatch.",
            estimated_impact=f"Could prevent ~{max(2, preventable // 2)} disputes/month",
            action_type="shipping",
        ),
        Recommendation(
            priority="high",
            title="Proactive post-delivery outreach",
            description="Auto-send 'Did you receive your order?' for medium/high risk scores 48h after ETA.",
            estimated_impact="Could prevent ~3 disputes/month",
            action_type="communication",
        ),
        Recommendation(
            priority="medium",
            title="Clear refund SLA for credit_not_processed",
            description="Publish 5–7 day refund timelines and attach ARN in customer emails to cut credit disputes.",
            estimated_impact="Could prevent ~2 disputes/month",
            action_type="policy",
        ),
        Recommendation(
            priority="low",
            title="Verify burst orders from new emails",
            description="Hold fulfilment 30 minutes when the same new email places 2+ orders in 24h.",
            estimated_impact="Could prevent ~1 fraud dispute/month",
            action_type="verification",
        ),
    ]

    trend = "stable"
    if total >= 8:
        trend = "increasing"
    elif total <= 3:
        trend = "decreasing"

    return MerchantInsights(
        total_disputes=total,
        total_amount_at_risk=round(amount, 2),
        dispute_rate_trend=trend,
        top_reason_codes=breakdown,
        risk_hotspots=hotspots,
        prevention_recommendations=recs,
        estimated_preventable_disputes=preventable,
        estimated_savings_if_prevented=round(savings, 2),
        used_fallback=True,
    )


def _payment_method(risk: TransactionRisk) -> str:
    # method not stored on risk — infer from factors JSON
    try:
        factors = json.loads(risk.risk_factors_json or "[]")
        for f in factors:
            if f.get("factor") == "card_payment":
                return "card"
            if f.get("factor") == "cod_order":
                return "cod"
    except json.JSONDecodeError:
        pass
    return "unknown"


async def _llm_insights(
    disputes: list[Dispute],
    risks: list[TransactionRisk],
    base: MerchantInsights,
) -> MerchantInsights | None:
    summary = {
        "disputes": [
            {
                "id": d.id,
                "reason": d.reason_code,
                "amount": paise_to_rupees(d.amount_paise),
                "status": d.status,
                "win_probability": d.win_probability,
                "triage": getattr(d, "triage_action", None),
            }
            for d in disputes[:30]
        ],
        "risks": [
            {
                "payment_id": r.payment_id,
                "score": r.risk_score,
                "level": r.risk_level,
                "alert": r.alert_status,
                "predicted": r.predicted_dispute_type,
            }
            for r in risks[:40]
        ],
        "baseline": base.to_dict(),
    }
    prompt = f"""Analyze this merchant's dispute history and risk profile. Identify:
1. Top patterns (products, carriers, segments, payment methods)
2. Root causes
3. Specific prevention recommendations ranked by impact
4. Estimated savings if recommendations are implemented

Data:
{json.dumps(summary)[:6000]}

Respond ONLY JSON matching:
{{"dispute_rate_trend":"increasing|stable|decreasing",
 "prevention_recommendations":[{{"priority":"high","title":"","description":"","estimated_impact":"","action_type":"shipping"}}],
 "estimated_preventable_disputes":0,
 "estimated_savings_if_prevented":0,
 "risk_hotspots":[{{"dimension":"","value":"","dispute_count":0,"dispute_rate":0,"comparison":""}}]}}"""

    url = settings.llm_api_base_url.rstrip("/") + "/chat/completions"
    async with httpx.AsyncClient(timeout=20.0) as client:
        for model in [_model_name(), *_FALLBACK_MODELS]:
            try:
                resp = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {settings.llm_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "messages": [
                            {
                                "role": "system",
                                "content": "You are a merchant dispute intelligence analyst. JSON only.",
                            },
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.3,
                        "max_tokens": 1500,
                    },
                )
                resp.raise_for_status()
                content = (
                    (resp.json().get("choices", [{}])[0].get("message", {}) or {}).get("content")
                    or ""
                ).strip()
                fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
                if fence:
                    content = fence.group(1).strip()
                start, end = content.find("{"), content.rfind("}")
                data = json.loads(content[start : end + 1])
                recs = [
                    Recommendation(
                        priority=str(x.get("priority") or "medium"),
                        title=str(x.get("title") or "Recommendation"),
                        description=str(x.get("description") or ""),
                        estimated_impact=str(x.get("estimated_impact") or ""),
                        action_type=str(x.get("action_type") or "policy"),
                    )
                    for x in (data.get("prevention_recommendations") or [])[:6]
                    if isinstance(x, dict)
                ]
                spots = [
                    Hotspot(
                        dimension=str(x.get("dimension") or "pattern"),
                        value=str(x.get("value") or ""),
                        dispute_count=int(x.get("dispute_count") or 0),
                        dispute_rate=float(x.get("dispute_rate") or 0),
                        comparison=str(x.get("comparison") or ""),
                    )
                    for x in (data.get("risk_hotspots") or [])[:6]
                    if isinstance(x, dict)
                ]
                return MerchantInsights(
                    total_disputes=base.total_disputes,
                    total_amount_at_risk=base.total_amount_at_risk,
                    dispute_rate_trend=str(data.get("dispute_rate_trend") or base.dispute_rate_trend),
                    top_reason_codes=base.top_reason_codes,
                    risk_hotspots=spots or base.risk_hotspots,
                    prevention_recommendations=recs or base.prevention_recommendations,
                    estimated_preventable_disputes=int(
                        data.get("estimated_preventable_disputes")
                        or base.estimated_preventable_disputes
                    ),
                    estimated_savings_if_prevented=float(
                        data.get("estimated_savings_if_prevented")
                        or base.estimated_savings_if_prevented
                    ),
                    used_fallback=False,
                )
            except Exception as exc:
                log.warning("intelligence.model_failed", model=model, error=str(exc)[:160])
    return None
