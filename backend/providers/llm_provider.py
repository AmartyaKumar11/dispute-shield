from __future__ import annotations

import structlog
import httpx

from backend.config import settings
from backend.providers.base import EmailRecord, LLMProvider, ShippingInfo
from backend.utils.helpers import paise_to_rupees

log = structlog.get_logger(__name__)

_MODEL_ALIASES = {
    "kimi": "moonshotai/kimi-k3",
    "kimi-k2": "moonshotai/kimi-k2.6",
    "kimi-k2.6": "moonshotai/kimi-k2.6",
    "kimi-k3": "moonshotai/kimi-k3",
}
_FALLBACK_MODELS = ("moonshotai/kimi-k3", "moonshotai/kimi-k2.6")

SYSTEM_PROMPT = """You are a payment dispute resolution specialist working for
an Indian e-commerce merchant. Your job is to write compelling, professional
explanation letters that contest chargeback disputes.

Your letters should be:
- Formal and professional in tone
- Structured with clear paragraphs
- Specific to the dispute reason code
- Backed by concrete evidence (dates, amounts, tracking numbers)
- 500-800 words
- Addressed to "Dear Dispute Resolution Team"
- Signed as "Merchant Dispute Resolution Team"

Do NOT:
- Be aggressive or accusatory toward the customer
- Make claims not supported by the evidence provided
- Use legal jargon excessively
- Exceed 800 words"""

USER_PROMPT_TEMPLATE = """Write an explanation letter to contest this chargeback dispute.

## Dispute Details
- Reason Code: {reason_code}
- Dispute Phase: {phase}
- Amount: Rs.{amount_rupees}
- Currency: {currency}
- Dispute Created: {dispute_created_at}
- Response Deadline: {respond_by}

## Payment Information
- Payment ID: {payment_id}
- Payment Method: {payment_method}
- Payment Date: {payment_date}
- Customer Email: {customer_email}
- Customer Contact: {customer_contact}

## Order Information
- Order ID: {order_id}
- Order Items: {order_items}
- Order Date: {order_date}

## Shipping Information
{shipping_section}

## Refund History
{refund_section}

## Customer Communication History
{comms_section}

## Letter Focus
{letter_focus}

## Evidence Gaps
{evidence_gaps}

Write the explanation letter now. Address the specific reason for the dispute
and reference the concrete evidence provided above."""


def _model_name() -> str:
    raw = (settings.llm_model_name or "kimi").strip()
    return _MODEL_ALIASES.get(raw.lower(), raw)


class KimiLLMProvider(LLMProvider):
    async def generate_explanation_letter(
        self,
        reason_code: str,
        letter_focus: str,
        payment_data: dict,
        order_data: dict,
        shipping_info: ShippingInfo | None,
        refund_data: list[dict],
        comms_data: list[EmailRecord],
    ) -> tuple[str, bool]:
        user_prompt = _build_user_prompt(
            reason_code,
            letter_focus,
            payment_data,
            order_data,
            shipping_info,
            refund_data,
            comms_data,
        )
        url = settings.llm_api_base_url.rstrip("/") + "/chat/completions"
        models = [_model_name()]
        for extra in _FALLBACK_MODELS:
            if extra not in models:
                models.append(extra)
        last_error: Exception | None = None
        try:
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
                                    {"role": "system", "content": SYSTEM_PROMPT},
                                    {"role": "user", "content": user_prompt},
                                ],
                                "temperature": 0.3,
                                "max_tokens": 2000,
                            },
                        )
                        response.raise_for_status()
                        payload = response.json()
                    except Exception as exc:
                        last_error = exc
                        log.warning("llm.model_failed", model=model, error=str(exc)[:200])
                        continue
                    message = payload.get("choices", [{}])[0].get("message", {}) or {}
                    content = (message.get("content") or "").strip()
                    if content:
                        log.info("llm.letter_generated", model=model, chars=len(content))
                        return content, False
                    last_error = RuntimeError(f"LLM {model} returned empty content")
            raise last_error or RuntimeError("LLM returned empty content")
        except Exception:
            log.exception("llm.fallback_letter")
            return (
                _fallback_letter(
                    reason_code, letter_focus, payment_data, order_data, shipping_info
                ),
                True,
            )


def _build_user_prompt(
    reason_code: str,
    letter_focus: str,
    payment_data: dict,
    order_data: dict,
    shipping_info: ShippingInfo | None,
    refund_data: list[dict],
    comms_data: list[EmailRecord],
) -> str:
    meta = payment_data.get("_meta") or {}
    amount_paise = payment_data.get("amount") or meta.get("amount_paise") or 0
    if shipping_info is None:
        shipping_section = (
            "Shipping proof is not available. Focus the explanation on other "
            "evidence such as billing proof and transaction legitimacy."
        )
        gaps = "shipping_proof"
    else:
        shipping_section = (
            f"Carrier: {shipping_info.carrier}; Tracking: {shipping_info.tracking_id}; "
            f"Status: {shipping_info.status}; Address: {shipping_info.delivery_address}; "
            f"Shipped: {shipping_info.shipped_at}; Delivered: {shipping_info.delivered_at}; "
            f"Signed by: {shipping_info.signed_by}"
        )
        gaps = meta.get("evidence_gaps") or "None"
        if isinstance(gaps, list):
            gaps = ", ".join(gaps) if gaps else "None"

    notes = payment_data.get("notes") or {}
    product = notes.get("product") if isinstance(notes, dict) else None
    items = order_data.get("notes", {}).get("product") if isinstance(order_data.get("notes"), dict) else None
    order_items = product or items or order_data.get("receipt") or "See order record"

    if refund_data:
        refund_section = "; ".join(
            f"id={r.get('id')} amount={r.get('amount')} status={r.get('status')}" for r in refund_data
        )
    else:
        refund_section = "No refunds recorded for this payment."

    if comms_data:
        comms_section = "\n".join(
            f"- [{e.direction}] {e.sent_at}: {e.subject} — {e.body_snippet}" for e in comms_data
        )
    else:
        comms_section = "No customer communication records available."

    return USER_PROMPT_TEMPLATE.format(
        reason_code=reason_code,
        phase=meta.get("phase") or "chargeback",
        amount_rupees=f"{paise_to_rupees(int(amount_paise)):.2f}",
        currency=payment_data.get("currency") or meta.get("currency") or "INR",
        dispute_created_at=meta.get("dispute_created_at") or "",
        respond_by=meta.get("respond_by") or "",
        payment_id=payment_data.get("id") or meta.get("payment_id") or "",
        payment_method=payment_data.get("method") or "card",
        payment_date=payment_data.get("created_at") or "",
        customer_email=payment_data.get("email") or "",
        customer_contact=payment_data.get("contact") or "",
        order_id=order_data.get("id") or payment_data.get("order_id") or "",
        order_items=order_items,
        order_date=order_data.get("created_at") or "",
        shipping_section=shipping_section,
        refund_section=refund_section,
        comms_section=comms_section,
        letter_focus=letter_focus,
        evidence_gaps=gaps,
    )


def _fallback_letter(
    reason_code: str,
    letter_focus: str,
    payment_data: dict,
    order_data: dict,
    shipping_info: ShippingInfo | None,
) -> str:
    meta = payment_data.get("_meta") or {}
    amount = paise_to_rupees(int(payment_data.get("amount") or meta.get("amount_paise") or 0))
    payment_id = payment_data.get("id") or meta.get("payment_id") or "unknown"
    order_id = order_data.get("id") or payment_data.get("order_id") or "unknown"
    email = payment_data.get("email") or "the customer"
    shipping_line = (
        "Shipping records were not available for this order, so this contest relies on "
        "billing records and transaction legitimacy."
        if shipping_info is None
        else (
            f"The shipment was handled by {shipping_info.carrier} under tracking ID "
            f"{shipping_info.tracking_id}, last known status {shipping_info.status}, "
            f"delivered to {shipping_info.delivery_address}."
        )
    )
    return (
        "Dear Dispute Resolution Team,\n\n"
        f"We write to contest the {reason_code} dispute raised against payment {payment_id} "
        f"for order {order_id}, amounting to Rs.{amount:.2f}. The transaction was authorised "
        f"by {email} using the payment method on file, and the corresponding order was created "
        "in the ordinary course of our e-commerce operations.\n\n"
        f"{letter_focus}\n\n"
        f"{shipping_line}\n\n"
        "Billing proof generated from Razorpay payment records is enclosed. Where customer "
        "communication exists, those emails show that we engaged with the customer in good faith. "
        "We request that this dispute be decided in the merchant's favour based on the enclosed "
        "evidence.\n\n"
        "Yours faithfully,\n"
        "Merchant Dispute Resolution Team"
    )
