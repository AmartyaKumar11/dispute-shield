from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

import httpx
import structlog

from backend.config import settings
from backend.providers.base import ShippingInfo
from backend.providers.llm_provider import _FALLBACK_MODELS, _model_name
from backend.utils.helpers import paise_to_rupees

log = structlog.get_logger(__name__)

_TIER2_3_MARKERS = (
    "pune",
    "hyderabad",
    "jaipur",
    "lucknow",
    "indore",
    "nagpur",
    "coimbatore",
    "411",
    "500",
    "302",
    "226",
)
_HIGH_RETURN = (
    "headphone",
    "earbud",
    "laptop",
    "phone",
    "charger",
    "cable",
    "shoe",
    "t-shirt",
    "fashion",
    "speaker",
    "watch",
    "usb",
)


@dataclass
class RiskFactor:
    factor: str
    signal: str
    weight: float


@dataclass
class RiskAssessment:
    risk_score: float
    risk_level: str
    risk_factors: list[RiskFactor] = field(default_factory=list)
    recommended_actions: list[str] = field(default_factory=list)
    predicted_dispute_type: str | None = None
    used_fallback: bool = False
    ml_model_used: str | None = None
    ml_probability: float | None = None

    def to_dict(self) -> dict:
        return {
            "risk_score": self.risk_score,
            "risk_level": self.risk_level,
            "risk_factors": [asdict(f) for f in self.risk_factors],
            "recommended_actions": self.recommended_actions,
            "predicted_dispute_type": self.predicted_dispute_type,
            "used_fallback": self.used_fallback,
            "ml_model_used": self.ml_model_used,
            "ml_probability": self.ml_probability,
        }


def _level(score: float) -> str:
    if score >= 75:
        return "critical"
    if score >= 50:
        return "high"
    if score >= 25:
        return "medium"
    return "low"


def _actions_for_level(level: str) -> list[str]:
    if level == "low":
        return ["No action needed"]
    if level == "medium":
        return ["Send delivery confirmation with tracking link to customer"]
    if level == "high":
        return [
            "Request signature on delivery.",
            "Send proactive 'did you receive your order?' email 2 days after estimated delivery.",
        ]
    return [
        "Flag for manual review before shipping.",
        "Consider requiring prepaid payment or reaching out to verify order.",
    ]


def _rule_score(
    payment_data: dict,
    order_data: dict,
    shipping_info: ShippingInfo | None,
    known_emails: set[str] | None = None,
) -> tuple[float, list[RiskFactor], str | None]:
    factors: list[RiskFactor] = []
    score = 0.0
    known = known_emails or set()
    amount_paise = int(payment_data.get("amount") or 0)
    amount_r = paise_to_rupees(amount_paise)
    email = (payment_data.get("email") or "").lower()
    method = (payment_data.get("method") or "card").lower()
    notes = payment_data.get("notes") if isinstance(payment_data.get("notes"), dict) else {}
    product = str(notes.get("product") or order_data.get("receipt") or "").lower()
    address = (shipping_info.delivery_address if shipping_info else "") or str(
        notes.get("shipping_address") or ""
    )
    created = payment_data.get("created_at")
    hour = None
    if isinstance(created, (int, float)):
        hour = datetime.utcfromtimestamp(int(created)).hour
    elif notes.get("hour") is not None:
        hour = int(notes["hour"])

    if amount_r > 5000 and email and email not in known:
        factors.append(
            RiskFactor(
                "high_value_new_customer",
                f"Order ₹{amount_r:,.0f} from first-time email {email}",
                20,
            )
        )
        score += 20
    if method == "card":
        factors.append(
            RiskFactor("card_payment", "Card payment (higher dispute rate vs UPI in India)", 10)
        )
        score += 10
    elif method in {"cod", "cash_on_delivery"}:
        factors.append(RiskFactor("cod_order", "Cash on delivery order", 15))
        score += 15
    addr_l = address.lower()
    if any(m in addr_l for m in _TIER2_3_MARKERS) or notes.get("city_tier") in {2, 3, "2", "3"}:
        factors.append(
            RiskFactor("tier2_3_shipping", f"Shipping address suggests tier-2/3 city: {address[:60]}", 10)
        )
        score += 10
    if any(k in product for k in _HIGH_RETURN):
        factors.append(
            RiskFactor("high_return_category", f"Product category often returned: {product or 'n/a'}", 10)
        )
        score += 10
    if hour is not None and (hour >= 23 or hour < 5):
        factors.append(RiskFactor("odd_hours_order", f"Order placed at unusual hour ({hour}:00 UTC)", 5))
        score += 5
    if notes.get("orders_last_24h", 0) and int(notes["orders_last_24h"]) >= 2:
        factors.append(
            RiskFactor(
                "burst_orders",
                f"Multiple orders from same email in last 24h ({notes['orders_last_24h']})",
                15,
            )
        )
        score += 15

    predicted = None
    if amount_r > 5000 and method == "card":
        predicted = "fraud"
    elif any(k in product for k in ("headphone", "shoe", "t-shirt", "cable")):
        predicted = "product_not_as_described"
    elif shipping_info and shipping_info.status in {"returned", "in_transit"}:
        predicted = "product_not_received"
    else:
        predicted = "chargeback"

    return min(100.0, score), factors, predicted


async def score_transaction_risk(
    payment_data: dict,
    order_data: dict,
    shipping_info: ShippingInfo | None,
    known_emails: set[str] | None = None,
    use_llm: bool = True,
) -> RiskAssessment:
    from backend.ml.predictor import predictor

    method = (payment_data.get("method") or "card").lower()
    if method == "upi":
        ml_result = predictor.predict_upi_risk(payment_data)
    else:
        ml_result = predictor.predict_card_risk(payment_data)
    ml_score = float(ml_result.get("risk_score") or 50)

    rule_score, factors, predicted = _rule_score(
        payment_data, order_data, shipping_info, known_emails
    )

    # Trust ML more when held-out precision is solid
    model_precision = float(ml_result.get("model_precision") or 0)
    if model_precision >= 0.5:
        ml_weight, rule_weight = 0.6, 0.4
    else:
        ml_weight, rule_weight = 0.3, 0.7

    final = int(round(ml_score * ml_weight + min(rule_score, 100.0) * rule_weight))
    final = max(0, min(100, final))
    level = _level(float(final))

    prec = ml_result.get("model_precision")
    rec = ml_result.get("model_recall")
    thr = ml_result.get("threshold", 0.5)
    train_n = ml_result.get("training_data_size", "N/A")
    prec_s = f"{float(prec):.3f}" if isinstance(prec, (int, float)) else "N/A"
    rec_s = f"{float(rec):.3f}" if isinstance(rec, (int, float)) else "N/A"
    thr_s = f"{float(thr):.3f}" if isinstance(thr, (int, float)) else "N/A"
    factors.insert(
        0,
        RiskFactor(
            factor="ml_model_prediction",
            signal=(
                f"{ml_result.get('model')} predicted {float(ml_result.get('probability') or 0):.1%} "
                f"dispute probability "
                f"(P={prec_s}, R={rec_s}, threshold={thr_s}, "
                f"trained on {train_n} transactions)"
            ),
            weight=round(ml_score * ml_weight, 1),
        ),
    )

    actions = _actions_for_level(level)
    used_fallback = ml_result.get("model") == "fallback"

    # Optional LLM polish for actions / predicted type (never blocks scoring)
    if use_llm:
        try:
            _, llm_factors, llm_actions, llm_predicted = await _llm_risk(
                payment_data, order_data, shipping_info, float(final)
            )
            for f in llm_factors:
                if f.factor not in {x.factor for x in factors}:
                    factors.append(f)
            if llm_actions:
                actions = llm_actions
            if llm_predicted:
                predicted = llm_predicted
        except Exception:
            log.exception("risk_scorer.llm_failed")

    if method == "upi" and predicted in {None, "chargeback", "fraud"}:
        predicted = "upi_unauthorized" if final >= 60 else "upi_goods_not_provided"

    return RiskAssessment(
        risk_score=float(final),
        risk_level=level,
        risk_factors=factors,
        recommended_actions=actions,
        predicted_dispute_type=predicted,
        used_fallback=used_fallback,
        ml_model_used=str(ml_result.get("model") or "fallback"),
        ml_probability=float(ml_result.get("probability") or 0.5),
    )


async def _llm_risk(
    payment_data: dict,
    order_data: dict,
    shipping_info: ShippingInfo | None,
    rule_score: float,
) -> tuple[float, list[RiskFactor], list[str], str | None]:
    import json
    import re

    amount = paise_to_rupees(int(payment_data.get("amount") or 0))
    ship = "n/a"
    if shipping_info:
        ship = f"{shipping_info.carrier}/{shipping_info.status}/{shipping_info.delivery_address}"
    prompt = f"""Given this transaction, rate the dispute risk 0-100 and list the top
risk factors. Also suggest 2-3 preventive actions the merchant can take.
Also predict the most likely dispute reason_code if one is filed.

Transaction:
- amount: Rs.{amount:.2f}
- method: {payment_data.get('method')}
- email: {payment_data.get('email')}
- order: {order_data.get('id') or payment_data.get('order_id')}
- notes: {payment_data.get('notes')}
- shipping: {ship}
- rule_based_score_hint: {rule_score}

Respond ONLY JSON:
{{"risk_score": 0, "risk_factors": [{{"factor":"","signal":"","weight":0}}],
 "recommended_actions": ["..."], "predicted_dispute_type": "fraud|product_not_received|..."}}"""

    url = settings.llm_api_base_url.rstrip("/") + "/chat/completions"
    models = [_model_name(), *_FALLBACK_MODELS]
    seen: set[str] = set()
    async with httpx.AsyncClient(timeout=12.0) as client:
        for model in models:
            if model in seen:
                continue
            seen.add(model)
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
                                "content": "You are a payment risk analyst. Reply with JSON only.",
                            },
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.2,
                        "max_tokens": 800,
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
                score = float(data.get("risk_score", rule_score))
                factors = [
                    RiskFactor(
                        str(x.get("factor") or "llm_factor"),
                        str(x.get("signal") or ""),
                        float(x.get("weight") or 0),
                    )
                    for x in (data.get("risk_factors") or [])[:6]
                    if isinstance(x, dict)
                ]
                actions = [str(a) for a in (data.get("recommended_actions") or [])][:4]
                predicted = data.get("predicted_dispute_type")
                return max(0.0, min(100.0, score)), factors, actions, str(predicted) if predicted else None
            except Exception as exc:
                log.warning("risk_scorer.model_failed", model=model, error=str(exc)[:160])
    raise RuntimeError("risk LLM failed")
