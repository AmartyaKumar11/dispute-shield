from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import structlog

from backend.database import AsyncSessionLocal
from backend.models import Dispute, TransactionRisk
from backend.providers.comms_provider import MockCommunicationProvider
from backend.providers.llm_provider import KimiLLMProvider
from backend.providers.razorpay_provider import RazorpayProvider
from backend.providers.shipping_provider import MockShippingProvider
from backend.services import document_builder
from backend.services.evidence_analyzer import (
    analyze_evidence_strength,
    predict_win_probability,
)
from backend.services.evidence_strategy import (
    evaluate_evidence_coverage,
    get_strategy,
    shipping_is_gap,
)
from backend.services.triage import clamp_demo_win, decide_triage
from backend.utils.helpers import jsonable, paise_to_rupees
from sqlalchemy import select

log = structlog.get_logger(__name__)

_pipeline_lock = asyncio.Lock()
_razorpay = RazorpayProvider()
_shipping = MockShippingProvider()
_comms = MockCommunicationProvider()
_llm = KimiLLMProvider()

_GAP_FOCUS = (
    "Note: shipping proof is not available. Focus the explanation on other "
    "evidence such as billing proof and transaction legitimacy."
)
_AUTH_MSG = "Authentication failed — check API keys"


def _is_auth_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(
        token in text
        for token in (
            "401",
            "authentication failed",
            "unauthorized",
            "invalid api key",
            "invalid key_id",
            "bad_request_error\",\"description\":\"authentication",
        )
    )


async def process_dispute(dispute_id: str) -> None:
    async with _pipeline_lock:
        await _run(dispute_id)


async def _run(dispute_id: str) -> None:
    async with AsyncSessionLocal() as session:
        dispute = await session.get(Dispute, dispute_id)
        if dispute is None:
            log.error("pipeline.dispute_not_found", dispute_id=dispute_id)
            return

        started = datetime.now(timezone.utc).replace(tzinfo=None)
        dispute.status = "gathering"
        # Wall-clock from received → submitted uses created_at as start.
        dispute.processing_started_at = dispute.created_at or started
        dispute.error_message = None
        await session.commit()

        try:
            strategy = get_strategy(dispute.reason_code)
            payment = await _load_payment(dispute)
            order = await _load_order(dispute)
            refunds = await _load_refunds(dispute)

            shipping = None
            shipping_record = None
            gaps: list[str] = []
            try:
                if dispute.order_id:
                    shipping_record = await _shipping.get_delivery_status(dispute.order_id)
            except Exception:
                log.exception("pipeline.shipping_failed", order_id=dispute.order_id)
            if shipping_is_gap(shipping_record):
                log.warning(
                    "pipeline.shipping_gap",
                    order_id=dispute.order_id,
                    detail=f"Shipping proof unavailable for order {dispute.order_id}",
                )
                gaps.append("shipping_proof")
                shipping = None
            else:
                shipping = shipping_record

            email = (payment.get("email") if isinstance(payment, dict) else None) or "customer@example.com"
            comms = []
            try:
                comms = await _comms.get_customer_emails(email, dispute.order_id or dispute.id)
            except Exception:
                log.exception("pipeline.comms_failed", dispute_id=dispute_id)

            payment["_meta"] = {
                "phase": dispute.phase,
                "amount_paise": dispute.amount_paise,
                "currency": dispute.currency,
                "payment_id": dispute.payment_id,
                "respond_by": dispute.respond_by.isoformat() if dispute.respond_by else "",
                "dispute_created_at": dispute.created_at.isoformat() if dispute.created_at else "",
                "evidence_gaps": gaps,
            }

            dispute.payment_data_json = json.dumps(jsonable(payment))
            dispute.order_data_json = json.dumps(jsonable(order))
            dispute.shipping_data_json = (
                json.dumps(jsonable(shipping_record)) if shipping_record else None
            )
            dispute.comms_data_json = json.dumps(jsonable(comms)) if comms else None
            dispute.refund_data_json = json.dumps(jsonable(refunds)) if refunds else None
            dispute.status = "assembled"
            await session.commit()

            provisional = _provisional_gathered(strategy, gaps, shipping, comms)
            coverage = evaluate_evidence_coverage(strategy, provisional)
            missing_required = [
                f for f in strategy.required_evidence if f not in provisional and f not in gaps
            ]
            # Gaps that are also required count as missing required
            missing_required = list(
                dict.fromkeys(
                    [
                        *missing_required,
                        *[f for f in strategy.required_evidence if f in gaps],
                    ]
                )
            )
            analysis = await analyze_evidence_strength(
                dispute.reason_code,
                payment,
                order,
                shipping,
                comms,
                refunds,
                gaps,
                coverage,
            )
            win = await predict_win_probability(
                dispute.reason_code,
                analysis,
                coverage,
                gaps,
                shipping_info=shipping,
                has_billing=True,
                has_comms=bool(comms),
                has_refund=bool(refunds),
                has_access_log="access_activity_log" in provisional,
                missing_required=missing_required,
                amount_paise=dispute.amount_paise,
            )
            win_score = clamp_demo_win(payment, win.win_probability)
            triage = decide_triage(win_score, win.reasoning)
            dispute.evidence_analysis_json = json.dumps(analysis.to_dict())
            dispute.win_probability = win_score
            dispute.win_probability_reasoning = win.reasoning
            dispute.triage_action = triage.action
            dispute.review_reason = triage.review_reason
            await session.commit()
            log.info(
                "pipeline.evidence_analyzed",
                dispute_id=dispute_id,
                strength=analysis.overall_strength,
                win=win_score,
                triage=triage.action,
                analysis_fallback=analysis.used_fallback,
            )

            await _mark_risk_dispute_filed(session, dispute.payment_id)

            if triage.action == "accept":
                dispute.status = "accepted"
                dispute.summary_text = (
                    f"Accepted {strategy.display_name} — win probability {win_score:.0f}%. "
                    f"{triage.review_reason}"
                )[:1000]
                dispute.evidence_strategy = json.dumps(
                    {
                        "reason_code": strategy.reason_code,
                        "display_name": strategy.display_name,
                        "description": strategy.description,
                        "required_evidence": strategy.required_evidence,
                        "recommended_evidence": strategy.recommended_evidence,
                        "letter_focus": strategy.letter_focus,
                        "evidence_gaps": gaps,
                        "coverage": coverage,
                        "letter_fallback": None,
                        "triage_action": "accept",
                    }
                )
                dispute.processing_completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
                await session.commit()
                log.info("pipeline.accepted", dispute_id=dispute_id, win=win_score)
                return

            letter_focus = strategy.letter_focus
            if "shipping_proof" in gaps:
                letter_focus = f"{letter_focus} {_GAP_FOCUS}"
            letter, used_fallback = await _llm.generate_explanation_letter(
                dispute.reason_code,
                letter_focus,
                payment,
                order,
                shipping,
                refunds,
                comms,
                analysis,
            )
            dispute.explanation_letter = letter

            docs, evidence_fields, coverage, used_fallback = await _build_docs(
                dispute,
                strategy,
                payment,
                order,
                shipping,
                comms,
                letter,
                gaps,
                used_fallback,
            )
            dispute.documents_uploaded = json.dumps(docs)
            dispute.evidence_strategy = json.dumps(
                {
                    "reason_code": strategy.reason_code,
                    "display_name": strategy.display_name,
                    "description": strategy.description,
                    "required_evidence": strategy.required_evidence,
                    "recommended_evidence": strategy.recommended_evidence,
                    "letter_focus": strategy.letter_focus,
                    "evidence_gaps": gaps,
                    "coverage": coverage,
                    "letter_fallback": used_fallback,
                    "triage_action": triage.action,
                }
            )
            summary = (
                f"Contesting {strategy.display_name} on payment {dispute.payment_id} "
                f"for Rs.{paise_to_rupees(dispute.amount_paise):.2f}. "
                f"{strategy.letter_focus} "
                f"Evidence: {', '.join(sorted(evidence_fields))}."
            )
            if gaps:
                summary += f" Gaps: {', '.join(gaps)}."
            dispute.summary_text = summary[:1000]
            evidence_payload = {**evidence_fields, "summary": dispute.summary_text}

            if triage.action == "review":
                dispute.status = "review"
                dispute.processing_completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
                await session.commit()
                log.info("pipeline.review", dispute_id=dispute_id, win=win_score)
                return

            dispute.status = "submitting"
            await session.commit()
            simulate = dispute.id.startswith("disp_simulated_") or dispute.payment_id.startswith(
                "pay_simulated_"
            )
            contest = await _contest(dispute.id, evidence_payload, simulate)
            dispute.contest_response_json = json.dumps(jsonable(contest))
            dispute.status = "submitted"
            dispute.processing_completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            await session.commit()
            log.info(
                "pipeline.submitted",
                dispute_id=dispute_id,
                gaps=gaps,
                docs=list(docs),
                letter_fallback=used_fallback,
            )
        except Exception as exc:
            log.exception("pipeline.failed", dispute_id=dispute_id)
            dispute.status = "error"
            if _is_auth_error(exc):
                dispute.error_message = _AUTH_MSG
            else:
                dispute.error_message = str(exc)[:1000]
            dispute.processing_completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            await session.commit()


async def _load_payment(dispute: Dispute) -> dict:
    if dispute.payment_id.startswith("pay_simulated_"):
        if dispute.payment_data_json:
            return json.loads(dispute.payment_data_json)
        return {"id": dispute.payment_id, "amount": dispute.amount_paise, "currency": dispute.currency}
    try:
        return await _razorpay.get_payment(dispute.payment_id)
    except Exception as exc:
        if _is_auth_error(exc):
            log.error("pipeline.payment_auth_failed", payment_id=dispute.payment_id)
            raise RuntimeError(_AUTH_MSG) from exc
        log.warning("pipeline.payment_fallback", payment_id=dispute.payment_id)
        return json.loads(dispute.payment_data_json or "{}") or {
            "id": dispute.payment_id,
            "amount": dispute.amount_paise,
        }


async def _load_order(dispute: Dispute) -> dict:
    if not dispute.order_id:
        return {}
    if dispute.order_id.startswith("order_simulated_"):
        return {"id": dispute.order_id}
    try:
        return await _razorpay.get_order(dispute.order_id)
    except Exception as exc:
        if _is_auth_error(exc):
            log.error("pipeline.order_auth_failed", order_id=dispute.order_id)
            raise RuntimeError(_AUTH_MSG) from exc
        log.warning("pipeline.order_fallback", order_id=dispute.order_id)
        return {"id": dispute.order_id}


async def _load_refunds(dispute: Dispute) -> list[dict]:
    if dispute.payment_id.startswith("pay_simulated_"):
        return []
    try:
        return await _razorpay.get_refunds(dispute.payment_id)
    except Exception as exc:
        if _is_auth_error(exc):
            log.error("pipeline.refunds_auth_failed", payment_id=dispute.payment_id)
            raise RuntimeError(_AUTH_MSG) from exc
        log.warning("pipeline.refunds_fallback", payment_id=dispute.payment_id)
        return []


async def _upload(file_path: str, purpose: str, simulate: bool) -> str:
    if simulate:
        doc_id = f"doc_sim_{Path(file_path).stem}"
        log.info("pipeline.upload_simulated", purpose=purpose, doc_id=doc_id, path=file_path)
        return doc_id
    try:
        return await _razorpay.upload_document(file_path, "dispute_evidence")
    except Exception as exc:
        if _is_auth_error(exc):
            raise RuntimeError(_AUTH_MSG) from exc
        doc_id = f"doc_sim_{Path(file_path).stem}"
        log.warning("pipeline.upload_fallback", purpose=purpose, doc_id=doc_id)
        return doc_id


async def _contest(dispute_id: str, evidence: dict, simulate: bool) -> dict:
    if simulate:
        log.info("pipeline.contest_simulated", dispute_id=dispute_id, evidence_keys=list(evidence))
        return {"id": dispute_id, "status": "under_review", "simulated": True, "evidence": evidence}
    try:
        return await _razorpay.contest_dispute(dispute_id, evidence)
    except Exception as exc:
        log.exception("pipeline.contest_failed", dispute_id=dispute_id)
        if _is_auth_error(exc):
            raise RuntimeError(_AUTH_MSG) from exc
        raise RuntimeError(f"Contest submission failed: {exc}") from exc


def _provisional_gathered(strategy, gaps: list[str], shipping, comms) -> set[str]:
    """Estimate evidence fields we will attach before PDF/upload (for analysis)."""
    gathered = {
        "billing_proof",
        "explanation_letter",
        "proof_of_service",
        "term_and_conditions",
        "refund_confirmation",
        "refund_cancellation_policy",
    }
    if "shipping_proof" not in gaps and shipping is not None:
        gathered.add("shipping_proof")
    if comms:
        gathered.add("customer_communication")
    if (
        "access_activity_log" in strategy.required_evidence
        or "access_activity_log" in strategy.recommended_evidence
    ):
        gathered.add("access_activity_log")
    return gathered


async def _mark_risk_dispute_filed(session, payment_id: str) -> None:
    row = (
        await session.execute(select(TransactionRisk).where(TransactionRisk.payment_id == payment_id))
    ).scalar_one_or_none()
    if row is not None and row.alert_status != "dispute_filed":
        row.alert_status = "dispute_filed"
        await session.commit()


async def _build_docs(
    dispute: Dispute,
    strategy,
    payment: dict,
    order: dict,
    shipping,
    comms,
    letter: str,
    gaps: list[str],
    used_fallback: bool,
) -> tuple[dict[str, str], dict[str, list[str]], float, bool]:
    docs: dict[str, str] = {}
    evidence_fields: dict[str, list[str]] = {}
    simulate = dispute.id.startswith("disp_simulated_") or dispute.payment_id.startswith(
        "pay_simulated_"
    )
    pdf_billing = document_builder.build_billing_proof(dispute.id, payment, order)
    docs["billing_proof"] = await _upload(pdf_billing, "billing_proof", simulate)
    evidence_fields["billing_proof"] = [docs["billing_proof"]]
    evidence_fields["proof_of_service"] = [docs["billing_proof"]]
    evidence_fields["term_and_conditions"] = [docs["billing_proof"]]
    evidence_fields["refund_confirmation"] = [docs["billing_proof"]]
    evidence_fields["refund_cancellation_policy"] = [docs["billing_proof"]]

    pdf_ship = document_builder.build_shipping_proof(dispute.id, shipping)
    if pdf_ship:
        docs["shipping_proof"] = await _upload(pdf_ship, "shipping_proof", simulate)
        evidence_fields["shipping_proof"] = [docs["shipping_proof"]]

    pdf_letter = document_builder.build_explanation_letter(dispute.id, letter)
    docs["explanation_letter"] = await _upload(pdf_letter, "explanation_letter", simulate)
    evidence_fields["explanation_letter"] = [docs["explanation_letter"]]

    pdf_comms = document_builder.build_customer_communication(dispute.id, comms)
    if pdf_comms:
        docs["customer_communication"] = await _upload(
            pdf_comms, "customer_communication", simulate
        )
        evidence_fields["customer_communication"] = [docs["customer_communication"]]

    if (
        "access_activity_log" in strategy.required_evidence
        or "access_activity_log" in strategy.recommended_evidence
    ):
        pdf_log = document_builder.build_access_activity_log(dispute.id, payment)
        docs["access_activity_log"] = await _upload(pdf_log, "access_activity_log", simulate)
        evidence_fields["access_activity_log"] = [docs["access_activity_log"]]

    coverage = evaluate_evidence_coverage(strategy, set(evidence_fields))
    return docs, evidence_fields, coverage, used_fallback


async def force_submit_dispute(dispute_id: str) -> None:
    """Submit a review/accepted dispute (uses existing package when available)."""
    async with _pipeline_lock:
        rebuild = False
        async with AsyncSessionLocal() as session:
            dispute = await session.get(Dispute, dispute_id)
            if dispute is None:
                raise ValueError("Dispute not found")
            if dispute.status not in {"review", "accepted"}:
                raise ValueError("Force submit only allowed for review or accepted disputes")

            docs = json.loads(dispute.documents_uploaded or "{}")
            if dispute.explanation_letter and docs:
                evidence_payload: dict = {
                    "summary": dispute.summary_text or "Merchant contest",
                }
                for key, doc_id in docs.items():
                    evidence_payload[key] = [doc_id] if isinstance(doc_id, str) else doc_id
                dispute.status = "submitting"
                dispute.triage_action = "auto_submit"
                await session.commit()
                simulate = dispute.id.startswith("disp_simulated_") or dispute.payment_id.startswith(
                    "pay_simulated_"
                )
                contest = await _contest(dispute.id, evidence_payload, simulate)
                dispute.contest_response_json = json.dumps(jsonable(contest))
                dispute.status = "submitted"
                dispute.processing_completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
                await session.commit()
                return

            payment = json.loads(dispute.payment_data_json or "{}")
            notes = payment.get("notes") if isinstance(payment.get("notes"), dict) else {}
            notes = {**notes, "demo_triage": "auto_submit"}
            payment["notes"] = notes
            dispute.payment_data_json = json.dumps(payment)
            dispute.status = "received"
            dispute.triage_action = None
            dispute.review_reason = None
            await session.commit()
            rebuild = True

        if rebuild:
            await _run(dispute_id)


async def accept_dispute(dispute_id: str) -> None:
    async with AsyncSessionLocal() as session:
        dispute = await session.get(Dispute, dispute_id)
        if dispute is None:
            raise ValueError("Dispute not found")
        if dispute.status not in {"review", "assembled", "received", "gathering"}:
            raise ValueError("Accept only allowed for open/review disputes")
        dispute.status = "accepted"
        dispute.triage_action = "accept"
        dispute.review_reason = dispute.review_reason or "Manually accepted by merchant"
        dispute.processing_completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await session.commit()

