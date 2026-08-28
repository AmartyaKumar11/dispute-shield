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
    "upi_goods_not_provided": EvidenceStrategy(
        reason_code="upi_goods_not_provided",
        display_name="UPI — Goods/Services Not Provided",
        description="Customer claims goods or services were not delivered (UPI)",
        required_evidence=["shipping_proof", "explanation_letter"],
        recommended_evidence=["billing_proof", "customer_communication"],
        letter_focus=(
            "Present UPI transaction reference, delivery confirmation with tracking details, "
            "and proof of service completion. Reference the VPA and bank reference number to "
            "establish transaction legitimacy."
        ),
    ),
    "upi_duplicate_transaction": EvidenceStrategy(
        reason_code="upi_duplicate_transaction",
        display_name="UPI — Duplicate Transaction",
        description="Customer charged twice for the same order (UPI)",
        required_evidence=["billing_proof", "explanation_letter"],
        recommended_evidence=["refund_confirmation", "access_activity_log"],
        letter_focus=(
            "Show that each transaction corresponds to a separate order with distinct order IDs "
            "and items. If a duplicate did occur, present the refund confirmation with UTR number."
        ),
    ),
    "upi_incorrect_amount": EvidenceStrategy(
        reason_code="upi_incorrect_amount",
        display_name="UPI — Incorrect Amount Charged",
        description="Customer claims they were charged a different amount (UPI)",
        required_evidence=["billing_proof", "explanation_letter", "proof_of_service"],
        recommended_evidence=["customer_communication"],
        letter_focus=(
            "Present the order confirmation showing the agreed amount, the checkout page consent, "
            "and the UPI collect/pay request showing the exact amount the customer approved."
        ),
    ),
    "upi_unauthorized": EvidenceStrategy(
        reason_code="upi_unauthorized",
        display_name="UPI — Unauthorized Transaction",
        description="Customer claims they did not authorize the UPI payment",
        required_evidence=["access_activity_log", "billing_proof", "explanation_letter"],
        recommended_evidence=["customer_communication", "proof_of_service"],
        letter_focus=(
            "UPI payments require the customer to enter their PIN on their own device. Present the "
            "UPI transaction ID, VPA used, device metadata, and timestamp. Emphasize that UPI "
            "PIN-based authorization means the customer actively approved the payment."
        ),
    ),
    "upi_beneficiary_claim": EvidenceStrategy(
        reason_code="upi_beneficiary_claim",
        display_name="UPI — Beneficiary Credit Not Received",
        description="Merchant claims payment was made but not credited",
        required_evidence=["billing_proof", "explanation_letter"],
        recommended_evidence=["access_activity_log"],
        letter_focus=(
            "Present the Razorpay settlement report showing the payment was received and credited. "
            "Include the UTR number and settlement ID as proof of credit."
        ),
    ),
}

_REQ_WEIGHT = 1.0
_REC_WEIGHT = 1.0


def get_strategy(reason_code: str) -> EvidenceStrategy:
    return EVIDENCE_STRATEGIES.get(reason_code, EVIDENCE_STRATEGIES["general"])


def evaluate_evidence_coverage(
    strategy: EvidenceStrategy,
    gathered_evidence: set[str] | dict | list[str],
) -> float:
    """Flat coverage: gathered(required∪recommended) / |required∪recommended|."""
    if isinstance(gathered_evidence, dict):
        gathered = {k for k, v in gathered_evidence.items() if v}
    else:
        gathered = set(gathered_evidence)
    fields = list(dict.fromkeys([*strategy.required_evidence, *strategy.recommended_evidence]))
    if not fields:
        return 1.0
    return sum(1 for item in fields if item in gathered) / len(fields)


def shipping_is_gap(shipping_info: ShippingInfo | None) -> bool:
    if shipping_info is None:
        return True
    return shipping_info.status in {"returned"}
