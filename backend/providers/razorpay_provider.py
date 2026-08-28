from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import razorpay
import structlog

from backend.config import settings
from backend.providers.base import PaymentProvider

log = structlog.get_logger(__name__)

_API_BASE = "https://api.razorpay.com/v1"


class RazorpayProvider(PaymentProvider):
    def __init__(self) -> None:
        self._key_id = settings.razorpay_key_id
        self._key_secret = settings.razorpay_key_secret
        self._client = razorpay.Client(auth=(self._key_id, self._key_secret))

    async def get_payment(self, payment_id: str) -> dict:
        log.info("razorpay.get_payment", payment_id=payment_id)
        try:
            result = await asyncio.to_thread(self._client.payment.fetch, payment_id)
        except Exception:
            log.exception("razorpay.get_payment_failed", payment_id=payment_id)
            raise
        return dict(result)

    async def get_order(self, order_id: str) -> dict:
        log.info("razorpay.get_order", order_id=order_id)
        try:
            result = await asyncio.to_thread(self._client.order.fetch, order_id)
        except Exception:
            log.exception("razorpay.get_order_failed", order_id=order_id)
            raise
        return dict(result)

    async def get_refunds(self, payment_id: str) -> list[dict]:
        log.info("razorpay.get_refunds", payment_id=payment_id)
        try:
            result = await asyncio.to_thread(self._client.payment.refunds, payment_id)
        except Exception:
            log.exception("razorpay.get_refunds_failed", payment_id=payment_id)
            raise
        if isinstance(result, dict) and "items" in result:
            return list(result["items"])
        if isinstance(result, list):
            return result
        return []

    async def upload_document(self, file_path: str, purpose: str) -> str:
        path = Path(file_path)
        log.info("razorpay.upload_document", file_path=file_path, purpose=purpose)
        try:
            with path.open("rb") as fh:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        f"{_API_BASE}/documents",
                        auth=(self._key_id, self._key_secret),
                        data={"purpose": purpose or "dispute_evidence"},
                        files={"file": (path.name, fh, "application/pdf")},
                    )
            response.raise_for_status()
        except Exception:
            log.exception("razorpay.upload_document_failed", file_path=file_path)
            raise
        doc_id = response.json().get("id")
        if not doc_id:
            raise RuntimeError(f"Document upload returned no id: {response.text}")
        return str(doc_id)

    async def contest_dispute(self, dispute_id: str, evidence: dict) -> dict:
        log.info("razorpay.contest_dispute", dispute_id=dispute_id)
        body = {**evidence, "action": "submit"}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.patch(
                    f"{_API_BASE}/disputes/{dispute_id}/contest",
                    auth=(self._key_id, self._key_secret),
                    json=body,
                )
            response.raise_for_status()
        except Exception:
            log.exception("razorpay.contest_dispute_failed", dispute_id=dispute_id)
            raise
        return dict(response.json())
