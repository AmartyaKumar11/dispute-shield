from __future__ import annotations

from dataclasses import dataclass

from backend.providers.base import ShippingInfo


@dataclass
class EvidenceStrategy:
    reason_code: str
    display_name: str
    description: str
    required_evidence: list[str]
    recommended_evidence: list[str]
    letter_focus: str


EVIDENCE_STRATEGIES: dict[str, EvidenceStrategy] = {
    "chargeback": EvidenceStrategy(
        reason_code="chargeback",
        display_name="General Chargeback",
        description="Customer disputes the transaction validity",
        required_evidence=["billing_proof", "explanation_letter"],
        recommended_evidence=["shipping_proof", "customer_communication", "proof_of_service"],
        letter_focus=(
            "Emphasize that the transaction was legitimate, authorized, and the "
            "product/service was delivered as described."
        ),
    ),
    "fraud": EvidenceStrategy(
        reason_code="fraud",
        display_name="Fraud Dispute",
        description="Bank suspects fraudulent transaction",
        required_evidence=["access_activity_log", "billing_proof", "explanation_letter"],
        recommended_evidence=["shipping_proof", "customer_communication"],
        letter_focus=(
            "Present IP address, device info, and transaction patterns showing this was "
            "the legitimate cardholder. Highlight any 3DS/OTP verification that occurred."
        ),
    ),
    "product_not_received": EvidenceStrategy(
        reason_code="product_not_received",
        display_name="Product Not Received",
        description="Customer claims they did not receive the product",
        required_evidence=["shipping_proof", "explanation_letter"],
        recommended_evidence=["customer_communication", "billing_proof"],
        letter_focus=(
            "Present delivery confirmation, tracking details, and proof of delivery signature. "
            "If delivered to correct address, emphasize address match with billing."
        ),
    ),
    "product_not_as_described": EvidenceStrategy(
        reason_code="product_not_as_described",
        display_name="Product Not as Described",
        description="Customer claims product differs from description",
        required_evidence=["proof_of_service", "explanation_letter", "term_and_conditions"],
        recommended_evidence=["customer_communication", "billing_proof"],
        letter_focus=(
            "Present product description, order confirmation showing what was ordered, and "
            "evidence that delivered product matches. Include refund/return policy."
        ),
    ),
    "credit_not_processed": EvidenceStrategy(
        reason_code="credit_not_processed",
        display_name="Credit Not Processed",
        description="Customer claims a refund was promised but not issued",
        required_evidence=["refund_confirmation", "explanation_letter"],
        recommended_evidence=["customer_communication", "refund_cancellation_policy"],
        letter_focus=(
            "If refund was issued, present the refund receipt with ARN. If refund was not "
            "applicable, explain why per the return/refund policy with supporting evidence."
        ),
    ),
    "subscription_canceled": EvidenceStrategy(
        reason_code="subscription_canceled",
        display_name="Subscription Canceled",
        description="Customer claims they canceled but were still charged",
        required_evidence=["proof_of_service", "term_and_conditions", "explanation_letter"],
        recommended_evidence=["customer_communication", "billing_proof"],
        letter_focus=(
            "Present cancellation policy, evidence of service usage after alleged cancellation "
            "date, or proof that cancellation was not received before the billing cycle."
        ),
    ),
    "general": EvidenceStrategy(
        reason_code="general",
        display_name="General Dispute",
        description="Dispute does not fit specific categories",
        required_evidence=["explanation_letter", "billing_proof"],
        recommended_evidence=["shipping_proof", "customer_communication", "proof_of_service"],
        letter_focus=(
            "Build a comprehensive case covering transaction legitimacy, product/service "
            "delivery, and customer authorization."
        ),
    ),
}

_REQ_WEIGHT = 2.0
_REC_WEIGHT = 1.0


def get_strategy(reason_code: str) -> EvidenceStrategy:
    return EVIDENCE_STRATEGIES.get(reason_code, EVIDENCE_STRATEGIES["general"])


def evaluate_evidence_coverage(
    strategy: EvidenceStrategy,
    gathered_evidence: set[str] | dict | list[str],
) -> float:
    if isinstance(gathered_evidence, dict):
        gathered = {k for k, v in gathered_evidence.items() if v}
    else:
        gathered = set(gathered_evidence)
    total = len(strategy.required_evidence) * _REQ_WEIGHT + len(strategy.recommended_evidence) * _REC_WEIGHT
    if total == 0:
        return 1.0
    score = sum(_REQ_WEIGHT for item in strategy.required_evidence if item in gathered)
    score += sum(_REC_WEIGHT for item in strategy.recommended_evidence if item in gathered)
    return score / total


def shipping_is_gap(shipping_info: ShippingInfo | None) -> bool:
    if shipping_info is None:
        return True
    return shipping_info.status in {"returned"}
