from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field

import httpx
import structlog

from backend.config import settings
from backend.providers.base import EmailRecord, ShippingInfo
from backend.providers.llm_provider import _FALLBACK_MODELS, _model_name
from backend.utils.helpers import paise_to_rupees

log = structlog.get_logger(__name__)

ANALYSIS_SYSTEM = """You are a chargeback dispute analyst for an Indian e-commerce merchant.
Respond ONLY with valid JSON. No markdown fences, no commentary."""


@dataclass
class EvidenceAnalysis:
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    letter_recommendations: list[str] = field(default_factory=list)
    overall_strength: str = "moderate"
    confidence_notes: str = ""
    llm_win_probability: float | None = None
    llm_win_reasoning: str | None = None
    used_fallback: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class WinPrediction:
    win_probability: float
    reasoning: str


async def analyze_evidence_strength(
    reason_code: str,
    payment_data: dict,
    order_data: dict,
    shipping_info: ShippingInfo | None,
    comms_data: list[EmailRecord],
    refund_data: list[dict],
    evidence_gaps: list[str],
    evidence_coverage: float = 0.0,
) -> EvidenceAnalysis:
    """Single LLM call: strengths/weaknesses + win probability. Falls back to rules."""
    prompt = _analysis_prompt(
        reason_code,
        payment_data,
        order_data,
        shipping_info,
        comms_data,
        refund_data,
        evidence_gaps,
        evidence_coverage,
    )
    try:
        raw = await _chat_completion(ANALYSIS_SYSTEM, prompt, max_tokens=1200)
        parsed = _parse_analysis_json(raw)
        if parsed is None:
            raise RuntimeError("Could not parse evidence analysis JSON")
        return parsed
    except Exception:
        log.exception("evidence_analysis.llm_failed")
        return _rule_based_analysis(
            reason_code, shipping_info, refund_data, evidence_gaps, evidence_coverage
        )


async def predict_win_probability(
    reason_code: str,
    evidence_analysis: EvidenceAnalysis,
    evidence_coverage: float,
    evidence_gaps: list[str],
    shipping_info: ShippingInfo | None = None,
    has_billing: bool = True,
    has_comms: bool = False,
    has_refund: bool = False,
    has_access_log: bool = False,
) -> WinPrediction:
    rule_score = _rule_win_score(
        reason_code,
        evidence_gaps,
        evidence_coverage,
        shipping_info,
        has_billing,
        has_comms,
        has_refund,
        has_access_log,
    )
    llm_score = evidence_analysis.llm_win_probability
    if llm_score is None:
        final = rule_score
        reasoning = (
            evidence_analysis.llm_win_reasoning
            or evidence_analysis.confidence_notes
            or f"Rule-based estimate from {evidence_analysis.overall_strength} evidence package."
        )
    else:
        final = (rule_score + float(llm_score)) / 2.0
        reasoning = (
            evidence_analysis.llm_win_reasoning
            or evidence_analysis.confidence_notes
            or "Hybrid of rule-based and model-estimated contest odds."
        )
    final = max(0.0, min(100.0, round(final, 1)))
    if llm_score is None:
        reasoning = (
            evidence_analysis.confidence_notes
            or f"Rule-based estimate ({final:.0f}%) from {evidence_analysis.overall_strength} evidence."
        )
    else:
        reasoning = (
            evidence_analysis.llm_win_reasoning
            or evidence_analysis.confidence_notes
            or "Hybrid of rule-based and model-estimated contest odds."
        )
        if evidence_analysis.used_fallback:
            reasoning = f"Hybrid score {final:.0f}% (rules {rule_score:.0f}% × model {float(llm_score):.0f}%). {reasoning}"
        elif "Hybrid" not in reasoning and final != llm_score:
            reasoning = f"{reasoning} (hybrid {final:.0f}% with rules {rule_score:.0f}%)."
    return WinPrediction(win_probability=final, reasoning=reasoning)


def _rule_win_score(
    reason_code: str,
    evidence_gaps: list[str],
    evidence_coverage: float,
    shipping_info: ShippingInfo | None,
    has_billing: bool,
    has_comms: bool,
    has_refund: bool,
    has_access_log: bool,
) -> float:
    score = 50.0
    if shipping_info is not None and shipping_info.status == "delivered":
        score += 15.0
    if has_billing:
        score += 10.0
    if has_comms:
        score += 10.0
    if has_refund and reason_code == "credit_not_processed":
        score += 20.0
    if evidence_coverage > 0.90:
        score += 5.0
    score -= 10.0 * len(evidence_gaps)
    if reason_code == "fraud" and not has_access_log:
        score -= 15.0
    return max(0.0, min(100.0, score))


def _rule_based_analysis(
    reason_code: str,
    shipping_info: ShippingInfo | None,
    refund_data: list[dict],
    evidence_gaps: list[str],
    evidence_coverage: float,
) -> EvidenceAnalysis:
    strengths: list[str] = []
    weaknesses: list[str] = []
    recommendations: list[str] = []

    if shipping_info is not None and shipping_info.status == "delivered":
        strengths.append(
            f"Shipping proof shows delivered via {shipping_info.carrier} "
            f"(tracking {shipping_info.tracking_id})."
        )
        recommendations.append("Lead with delivery confirmation and tracking details.")
    if "shipping_proof" in evidence_gaps or shipping_info is None:
        weaknesses.append("Shipping proof is missing or unavailable (RTO/returned).")
        recommendations.append(
            "Acknowledge the shipping gap and pivot to billing legitimacy and order records."
        )
    if refund_data and reason_code == "credit_not_processed":
        strengths.append("Refund history exists for this payment.")
        recommendations.append("Cite refund IDs, amounts, and timestamps explicitly.")
    if evidence_coverage > 0.90:
        overall = "strong"
    elif evidence_coverage > 0.80:
        overall = "moderate"
    else:
        overall = "weak"
        weaknesses.append(f"Evidence coverage is only {evidence_coverage:.0%}.")

    if not strengths:
        strengths.append("Authorised payment record and billing proof are available.")
    if not recommendations:
        recommendations.append("Structure the letter around the reason-code strategy focus.")

    llm_win = _rule_win_score(
        reason_code,
        evidence_gaps,
        evidence_coverage,
        shipping_info,
        True,
        False,
        bool(refund_data),
        reason_code != "fraud",  # assume access log built later for fraud
    )
    # For fraud fallback: access log is generated in pipeline, so don't over-penalize
    if reason_code == "fraud":
        llm_win = min(100.0, llm_win + 15.0)

    return EvidenceAnalysis(
        strengths=strengths,
        weaknesses=weaknesses,
        letter_recommendations=recommendations,
        overall_strength=overall,
        confidence_notes=f"Rule-based analysis: {overall} package at {evidence_coverage:.0%} coverage.",
        llm_win_probability=llm_win,
        llm_win_reasoning=f"Rule-based win estimate {llm_win:.0f}% given coverage and gaps.",
        used_fallback=True,
    )


def _analysis_prompt(
    reason_code: str,
    payment_data: dict,
    order_data: dict,
    shipping_info: ShippingInfo | None,
    comms_data: list[EmailRecord],
    refund_data: list[dict],
    evidence_gaps: list[str],
    evidence_coverage: float,
) -> str:
    meta = payment_data.get("_meta") or {}
    amount = paise_to_rupees(int(payment_data.get("amount") or meta.get("amount_paise") or 0))
    if shipping_info is None:
        shipping_blob = "Unavailable / gap"
    else:
        shipping_blob = (
            f"carrier={shipping_info.carrier}; tracking={shipping_info.tracking_id}; "
            f"status={shipping_info.status}; address={shipping_info.delivery_address}; "
            f"delivered_at={shipping_info.delivered_at}; signed_by={shipping_info.signed_by}"
        )
    refunds = (
        "; ".join(f"{r.get('id')}:{r.get('status')}:{r.get('amount')}" for r in refund_data)
        if refund_data
        else "none"
    )
    comms = (
        " | ".join(f"[{e.direction}] {e.subject}" for e in comms_data[:5])
        if comms_data
        else "none"
    )
    return f"""You are a chargeback dispute analyst. Analyze the following evidence
package for a {reason_code} dispute and identify:
1. Key strengths (evidence that supports our case)
2. Key weaknesses (gaps or contradictions that hurt our case)
3. Specific points to emphasize in the explanation letter
4. Overall evidence strength: strong / moderate / weak
5. Also predict a win probability (0-100) for this dispute contest and give a one-sentence justification.

## Evidence package
- Payment ID: {payment_data.get('id') or meta.get('payment_id')}
- Amount: Rs.{amount:.2f}
- Order ID: {order_data.get('id') or payment_data.get('order_id')}
- Shipping: {shipping_blob}
- Refunds: {refunds}
- Customer emails: {comms}
- Evidence gaps: {', '.join(evidence_gaps) if evidence_gaps else 'none'}
- Evidence coverage: {evidence_coverage:.0%}

Respond in JSON format:
{{
  "strengths": ["list of strength observations"],
  "weaknesses": ["list of weakness observations"],
  "letter_recommendations": ["specific points to include in the letter"],
  "overall_strength": "strong|moderate|weak",
  "confidence_notes": "one sentence summary",
  "win_probability": 0,
  "win_probability_reasoning": "one sentence justification"
}}"""


def _parse_analysis_json(raw: str) -> EvidenceAnalysis | None:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    strength = str(data.get("overall_strength") or "moderate").lower()
    if strength not in {"strong", "moderate", "weak"}:
        strength = "moderate"
    win = data.get("win_probability")
    try:
        win_f = float(win) if win is not None else None
        if win_f is not None:
            win_f = max(0.0, min(100.0, win_f))
    except (TypeError, ValueError):
        win_f = None
    return EvidenceAnalysis(
        strengths=[str(x) for x in (data.get("strengths") or [])][:8],
        weaknesses=[str(x) for x in (data.get("weaknesses") or [])][:8],
        letter_recommendations=[str(x) for x in (data.get("letter_recommendations") or [])][:8],
        overall_strength=strength,
        confidence_notes=str(data.get("confidence_notes") or "")[:500],
        llm_win_probability=win_f,
        llm_win_reasoning=str(data.get("win_probability_reasoning") or "")[:500] or None,
        used_fallback=False,
    )


async def _chat_completion(system: str, user: str, max_tokens: int = 1200) -> str:
    url = settings.llm_api_base_url.rstrip("/") + "/chat/completions"
    models = [_model_name()]
    for extra in _FALLBACK_MODELS:
        if extra not in models:
            models.append(extra)
    last_error: Exception | None = None
    async with httpx.AsyncClient(timeout=90.0) as client:
        for model in models:
            try:
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {settings.llm_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        "temperature": 0.2,
                        "max_tokens": max_tokens,
                    },
                )
                response.raise_for_status()
                payload = response.json()
                content = (
                    (payload.get("choices", [{}])[0].get("message", {}) or {}).get("content") or ""
                ).strip()
                if content:
                    log.info("evidence_analysis.llm_ok", model=model, chars=len(content))
                    return content
                last_error = RuntimeError(f"empty content from {model}")
            except Exception as exc:
                last_error = exc
                log.warning("evidence_analysis.model_failed", model=model, error=str(exc)[:200])
    raise last_error or RuntimeError("LLM analysis failed")
