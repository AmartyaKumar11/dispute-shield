from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import structlog

from backend.config import settings
from backend.providers.razorpay_provider import RazorpayProvider

log = structlog.get_logger(__name__)

TEST_SCENARIOS: list[dict] = [
    {"amount": 120000, "reason": "product_not_received", "product": "Wireless Headphones"},
    {"amount": 340000, "reason": "fraud", "product": "Laptop Stand"},
    {"amount": 89000, "reason": "credit_not_processed", "product": "Phone Case"},
    {"amount": 250000, "reason": "chargeback", "product": "Running Shoes"},
    {"amount": 45000, "reason": "product_not_as_described", "product": "USB Cable"},
    {"amount": 780000, "reason": "subscription_canceled", "product": "Annual SaaS Plan"},
    {"amount": 150000, "reason": "general", "product": "Bluetooth Speaker"},
    {"amount": 210000, "reason": "product_not_received", "product": "Watch Strap"},
    {"amount": 67000, "reason": "fraud", "product": "Earbuds"},
    {"amount": 430000, "reason": "chargeback", "product": "Backpack"},
    {"amount": 95000, "reason": "credit_not_processed", "product": "Charger"},
    {"amount": 185000, "reason": "product_not_as_described", "product": "T-Shirt"},
]

CUSTOMERS: list[tuple[str, str, str]] = [
    ("Priya Sharma", "priya.sharma@example.com", "+919876543210"),
    ("Rahul Verma", "rahul.verma@example.com", "+919820112233"),
    ("Ananya Iyer", "ananya.iyer@example.com", "+919611445566"),
    ("Vikram Singh", "vikram.singh@example.com", "+919999888777"),
    ("Sneha Patel", "sneha.patel@example.com", "+918888777666"),
    ("Arjun Reddy", "arjun.reddy@example.com", "+917777666555"),
    ("Meera Nair", "meera.nair@example.com", "+916666555444"),
    ("Karan Malhotra", "karan.malhotra@example.com", "+915555444333"),
    ("Divya Krishnan", "divya.krishnan@example.com", "+914444333222"),
    ("Amit Joshi", "amit.joshi@example.com", "+913333222111"),
    ("Pooja Gupta", "pooja.gupta@example.com", "+912222111000"),
    ("Rohan Desai", "rohan.desai@example.com", "+911234567890"),
]


def _webhook_payload(
    index: int,
    order_id: str,
    created_at: int,
    respond_by: int,
) -> dict:
    scenario = TEST_SCENARIOS[index]
    name, email, contact = CUSTOMERS[index]
    n = index + 1
    payment_id = f"pay_simulated_{n}"
    dispute_id = f"disp_simulated_{n}"
    return {
        "entity": "event",
        "account_id": "acc_test",
        "event": "payment.dispute.created",
        "contains": ["payment", "dispute"],
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "amount": scenario["amount"],
                    "currency": "INR",
                    "method": "card",
                    "email": email,
                    "contact": contact,
                    "order_id": order_id,
                    "created_at": created_at,
                    "notes": {"product": scenario["product"], "customer_name": name},
                }
            },
            "dispute": {
                "entity": {
                    "id": dispute_id,
                    "payment_id": payment_id,
                    "amount": scenario["amount"],
                    "currency": "INR",
                    "amount_deducted": 0,
                    "reason_code": scenario["reason"],
                    "respond_by": respond_by,
                    "status": "open",
                    "phase": "chargeback",
                    "created_at": created_at,
                }
            },
        },
        "created_at": created_at,
    }


async def _create_order(provider: RazorpayProvider, index: int) -> str:
    scenario = TEST_SCENARIOS[index]
    receipt = f"test_{index + 1}"
    try:
        order = await asyncio.to_thread(
            provider._client.order.create,
            {
                "amount": scenario["amount"],
                "currency": "INR",
                "receipt": receipt,
                "notes": {"product": scenario["product"]},
            },
        )
        order_id = order.get("id") or f"order_simulated_{index + 1}"
        log.info("seed.order_created", receipt=receipt, order_id=order_id)
        return str(order_id)
    except Exception:
        log.exception("seed.order_create_failed", receipt=receipt)
        return f"order_simulated_{index + 1}"


async def seed_test_disputes(base_url: str | None = None) -> dict:
    host = settings.app_host if settings.app_host != "0.0.0.0" else "127.0.0.1"
    url = (base_url or f"http://{host}:{settings.app_port}").rstrip("/")
    provider = RazorpayProvider()
    now = datetime.now(timezone.utc)
    created_at = int(now.timestamp())
    created = 0
    errors: list[str] = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        for index in range(len(TEST_SCENARIOS)):
            order_id = await _create_order(provider, index)
            respond_by = int((now + timedelta(days=7 + (index % 8))).timestamp())
            payload = _webhook_payload(index, order_id, created_at, respond_by)
            try:
                response = await client.post(f"{url}/webhooks/razorpay", json=payload)
                response.raise_for_status()
                created += 1
                log.info(
                    "seed.webhook_posted",
                    dispute_id=payload["payload"]["dispute"]["entity"]["id"],
                    status_code=response.status_code,
                )
            except Exception as exc:
                msg = f"disp_simulated_{index + 1}: {exc}"
                errors.append(msg)
                log.exception("seed.webhook_failed", index=index)

    return {"created": created, "total": len(TEST_SCENARIOS), "errors": errors}


def main() -> None:
    result = asyncio.run(seed_test_disputes())
    print(result)


if __name__ == "__main__":
    main()
