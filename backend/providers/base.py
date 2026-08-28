from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass
class ShippingInfo:
    tracking_id: str
    carrier: str
    status: str
    shipped_at: datetime | None
    delivered_at: datetime | None
    delivery_address: str
    signed_by: str | None
    proof_of_delivery_url: str | None


@dataclass
class EmailRecord:
    subject: str
    body_snippet: str
    sent_at: datetime
    direction: str
    sender: str
    recipient: str


class PaymentProvider(ABC):
    @abstractmethod
    async def get_payment(self, payment_id: str) -> dict: ...

    @abstractmethod
    async def get_order(self, order_id: str) -> dict: ...

    @abstractmethod
    async def get_refunds(self, payment_id: str) -> list[dict]: ...

    @abstractmethod
    async def upload_document(self, file_path: str, purpose: str) -> str: ...

    @abstractmethod
    async def contest_dispute(self, dispute_id: str, evidence: dict) -> dict: ...


class ShippingProvider(ABC):
    @abstractmethod
    async def get_delivery_status(self, order_id: str) -> ShippingInfo: ...


class CommunicationProvider(ABC):
    @abstractmethod
    async def get_customer_emails(
        self, customer_email: str, order_id: str
    ) -> list[EmailRecord]: ...


class LLMProvider(ABC):
    @abstractmethod
    async def generate_explanation_letter(
        self,
        reason_code: str,
        letter_focus: str,
        payment_data: dict,
        order_data: dict,
        shipping_info: ShippingInfo | None,
        refund_data: list[dict],
        comms_data: list[EmailRecord],
    ) -> str: ...
