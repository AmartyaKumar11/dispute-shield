from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import BackgroundTasks

from backend.database import AsyncSessionLocal
from backend.models import Dispute
from backend.services.dispute_service import process_dispute
from backend.utils.helpers import unix_to_naive

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


def _payment_entity(index: int, order_id: str, created_at: int) -> dict:
    scenario = TEST_SCENARIOS[index]
    name, email, contact = CUSTOMERS[index]
    return {
        "id": f"pay_simulated_{index + 1}",
        "amount": scenario["amount"],
        "currency": "INR",
        "method": "card",
        "email": email,
        "contact": contact,
        "order_id": order_id,
        "created_at": created_at,
        "notes": {"product": scenario["product"], "customer_name": name},
    }


async def seed_test_disputes(background_tasks: BackgroundTasks | None = None) -> dict:
    """Insert simulated disputes in-process (idempotent). No self-HTTP — avoids deadlocks."""
    now = datetime.now(timezone.utc)
    created_at = int(now.timestamp())
    created = 0
    skipped = 0
    errors: list[str] = []
    to_process: list[str] = []

    for index in range(len(TEST_SCENARIOS)):
        scenario = TEST_SCENARIOS[index]
        dispute_id = f"disp_simulated_{index + 1}"
        order_id = f"order_simulated_{index + 1}"
        payment = _payment_entity(index, order_id, created_at)
        respond_by = unix_to_naive(int((now + timedelta(days=7 + (index % 8))).timestamp()))
        try:
            async with AsyncSessionLocal() as session:
                existing = await session.get(Dispute, dispute_id)
                if existing is not None:
                    skipped += 1
                    continue
                session.add(
                    Dispute(
                        id=dispute_id,
                        payment_id=payment["id"],
                        order_id=order_id,
                        amount_paise=int(scenario["amount"]),
                        currency="INR",
                        reason_code=str(scenario["reason"]),
                        phase="chargeback",
                        respond_by=respond_by,
                        status="received",
                        payment_data_json=json.dumps(payment),
                    )
                )
                await session.commit()
            created += 1
            to_process.append(dispute_id)
            log.info("seed.dispute_created", dispute_id=dispute_id)
        except Exception as exc:
            errors.append(f"{dispute_id}: {exc}")
            log.exception("seed.dispute_failed", dispute_id=dispute_id)

    for dispute_id in to_process:
        if background_tasks is not None:
            background_tasks.add_task(process_dispute, dispute_id)
        else:
            asyncio.create_task(process_dispute(dispute_id))

    return {
        "created": created,
        "skipped": skipped,
        "total": len(TEST_SCENARIOS),
        "errors": errors,
    }


def main() -> None:
    result = asyncio.run(seed_test_disputes())
    print(result)


if __name__ == "__main__":
    main()
