from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from backend.providers.base import CommunicationProvider, EmailRecord

_MERCHANT = "support@shopkart.in"


def _seed(order_id: str) -> int:
    return int(hashlib.md5(order_id.encode()).hexdigest(), 16)


class MockCommunicationProvider(CommunicationProvider):
    async def get_customer_emails(self, customer_email: str, order_id: str) -> list[EmailRecord]:
        seed = _seed(order_id)
        n = 2 + (seed % 3)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        t0 = now - timedelta(days=12 + (seed % 5))
        emails: list[EmailRecord] = []

        emails.append(
            EmailRecord(
                subject=f"Order confirmed - {order_id}",
                body_snippet=(
                    f"Hi, your order {order_id} has been confirmed and will be shipped within "
                    "1-2 business days. Thank you for shopping with ShopKart."
                )[:200],
                sent_at=t0,
                direction="outbound",
                sender=_MERCHANT,
                recipient=customer_email,
            )
        )
        if n >= 3:
            emails.append(
                EmailRecord(
                    subject=f"Where is my order {order_id}?",
                    body_snippet=(
                        "Hi, I placed this order several days ago and have not received it yet. "
                        "Please share the tracking details."
                    )[:200],
                    sent_at=t0 + timedelta(days=3, hours=2),
                    direction="inbound",
                    sender=customer_email,
                    recipient=_MERCHANT,
                )
            )
            emails.append(
                EmailRecord(
                    subject=f"Re: Where is my order {order_id}?",
                    body_snippet=(
                        f"Please find the tracking link for {order_id}. Your shipment is on the way "
                        "via our courier partner. Typical delivery is 2-7 business days."
                    )[:200],
                    sent_at=t0 + timedelta(days=3, hours=5),
                    direction="outbound",
                    sender=_MERCHANT,
                    recipient=customer_email,
                )
            )
        if n == 2:
            emails.append(
                EmailRecord(
                    subject=f"Your order {order_id} has been delivered",
                    body_snippet=(
                        "Good news — your order has been delivered. If anything is missing or damaged, "
                        "reply to this email within 7 days."
                    )[:200],
                    sent_at=t0 + timedelta(days=5),
                    direction="outbound",
                    sender=_MERCHANT,
                    recipient=customer_email,
                )
            )
        if n == 4:
            emails.append(
                EmailRecord(
                    subject=f"I want a refund for {order_id}",
                    body_snippet=(
                        "I am not satisfied with this purchase and want a full refund. Please process "
                        "it against the original payment method."
                    )[:200],
                    sent_at=t0 + timedelta(days=7),
                    direction="inbound",
                    sender=customer_email,
                    recipient=_MERCHANT,
                )
            )
        emails.sort(key=lambda e: e.sent_at)
        return emails
