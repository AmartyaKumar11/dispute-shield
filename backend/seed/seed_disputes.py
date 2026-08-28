from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import BackgroundTasks
from sqlalchemy import select

from backend.database import AsyncSessionLocal
from backend.models import Dispute, TransactionRisk
from backend.providers.shipping_provider import MockShippingProvider
from backend.services.dispute_service import process_dispute
from backend.services.risk_scorer import score_transaction_risk
from backend.utils.helpers import unix_to_naive

log = structlog.get_logger(__name__)

# 12 disputes — triage bands via demo_triage for a natural mix (~7/3/2)
TEST_SCENARIOS: list[dict] = [
    {"amount": 120000, "reason": "product_not_received", "product": "Wireless Headphones", "demo_triage": "auto_submit", "method": "card", "city_tier": 1, "hour": 14},
    {"amount": 340000, "reason": "fraud", "product": "Laptop Stand", "demo_triage": "auto_submit", "method": "card", "city_tier": 1, "hour": 11, "orders_last_24h": 1},
    {"amount": 89000, "reason": "credit_not_processed", "product": "Phone Case", "demo_triage": "auto_submit", "method": "upi", "city_tier": 1, "hour": 10},
    {"amount": 250000, "reason": "chargeback", "product": "Running Shoes", "demo_triage": "auto_submit", "method": "card", "city_tier": 2, "hour": 16},
    {"amount": 45000, "reason": "product_not_as_described", "product": "USB Cable", "demo_triage": "auto_submit", "method": "upi", "city_tier": 1, "hour": 12},
    {"amount": 780000, "reason": "subscription_canceled", "product": "Annual SaaS Plan", "demo_triage": "auto_submit", "method": "card", "city_tier": 1, "hour": 9},
    {"amount": 150000, "reason": "general", "product": "Bluetooth Speaker", "demo_triage": "auto_submit", "method": "card", "city_tier": 1, "hour": 15},
    {"amount": 210000, "reason": "product_not_received", "product": "Watch Strap", "demo_triage": "review", "method": "card", "city_tier": 3, "hour": 23},
    {"amount": 67000, "reason": "fraud", "product": "Earbuds", "demo_triage": "review", "method": "card", "city_tier": 2, "hour": 2, "orders_last_24h": 3},
    {"amount": 430000, "reason": "chargeback", "product": "Backpack", "demo_triage": "review", "method": "card", "city_tier": 2, "hour": 20},
    {"amount": 95000, "reason": "credit_not_processed", "product": "Charger", "demo_triage": "accept", "method": "card", "city_tier": 3, "hour": 1},
    {"amount": 185000, "reason": "product_not_as_described", "product": "T-Shirt", "demo_triage": "accept", "method": "cod", "city_tier": 3, "hour": 3},
]

# 8 healthy transactions — low risk, never disputed
HEALTHY_TXNS: list[dict] = [
    {"amount": 49900, "product": "Notebook Set", "method": "upi", "city_tier": 1, "hour": 11},
    {"amount": 129900, "product": "Kitchen Towels", "method": "upi", "city_tier": 1, "hour": 14},
    {"amount": 79900, "product": "Water Bottle", "method": "upi", "city_tier": 1, "hour": 10},
    {"amount": 24900, "product": "Stationery Pack", "method": "upi", "city_tier": 1, "hour": 16},
    {"amount": 159900, "product": "Desk Organizer", "method": "upi", "city_tier": 1, "hour": 12},
    {"amount": 99900, "product": "Phone Stand", "method": "upi", "city_tier": 1, "hour": 13},
    {"amount": 34900, "product": "Socks Pack", "method": "upi", "city_tier": 1, "hour": 15},
    {"amount": 59900, "product": "Mouse Pad", "method": "upi", "city_tier": 1, "hour": 17},
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

HEALTHY_CUSTOMERS: list[tuple[str, str, str]] = [
    ("Neha Kapoor", "neha.kapoor@example.com", "+919700000001"),
    ("Siddharth Rao", "sid.rao@example.com", "+919700000002"),
    ("Isha Banerjee", "isha.b@example.com", "+919700000003"),
    ("Farhan Ali", "farhan.ali@example.com", "+919700000004"),
    ("Kavya Menon", "kavya.m@example.com", "+919700000005"),
    ("Dev Patel", "dev.patel@example.com", "+919700000006"),
    ("Riya Shah", "riya.shah@example.com", "+919700000007"),
    ("Nikhil Jain", "nikhil.j@example.com", "+919700000008"),
]

_ADDRESSES = {
    1: "12, Linking Road, Bandra West, Mumbai, Maharashtra 400050",
    2: "45, MG Road, Shivajinagar, Pune, Maharashtra 411005",
    3: "88, Civil Lines, Nagpur, Maharashtra 440001",
}

_shipping = MockShippingProvider()


def _payment_entity(index: int, order_id: str, created_at: int, scenario: dict, customer: tuple) -> dict:
    name, email, contact = customer
    hour = int(scenario.get("hour") or 12)
    # Align unix created_at hour approximately for risk scorer
    base = datetime.fromtimestamp(created_at, tz=timezone.utc).replace(
        hour=hour % 24, minute=0, second=0, microsecond=0
    )
    return {
        "id": f"pay_simulated_{index + 1}",
        "amount": scenario["amount"],
        "currency": "INR",
        "method": scenario.get("method") or "card",
        "email": email,
        "contact": contact,
        "order_id": order_id,
        "created_at": int(base.timestamp()),
        "notes": {
            "product": scenario["product"],
            "customer_name": name,
            "city_tier": scenario.get("city_tier", 1),
            "shipping_address": _ADDRESSES.get(int(scenario.get("city_tier") or 1), _ADDRESSES[1]),
            "hour": hour,
            "orders_last_24h": scenario.get("orders_last_24h", 0),
            "demo_triage": scenario.get("demo_triage"),
        },
    }


async def _upsert_risk(
    payment: dict,
    order: dict,
    shipping,
    known_emails: set[str],
) -> None:
    assessment = await score_transaction_risk(
        payment, order, shipping, known_emails=known_emails, use_llm=False
    )
    async with AsyncSessionLocal() as session:
        existing = (
            await session.execute(
                select(TransactionRisk).where(TransactionRisk.payment_id == payment["id"])
            )
        ).scalar_one_or_none()
        if existing is not None:
            return
        session.add(
            TransactionRisk(
                payment_id=payment["id"],
                order_id=payment.get("order_id"),
                amount_paise=int(payment["amount"]),
                risk_score=assessment.risk_score,
                risk_level=assessment.risk_level,
                risk_factors_json=json.dumps([f.__dict__ for f in assessment.risk_factors]),
                recommended_actions_json=json.dumps(assessment.recommended_actions),
                predicted_dispute_type=assessment.predicted_dispute_type,
                alert_status="active",
            )
        )
        await session.commit()


async def seed_test_disputes(background_tasks: BackgroundTasks | None = None) -> dict:
    now = datetime.now(timezone.utc)
    created_at = int(now.timestamp())
    created = 0
    skipped = 0
    risks_created = 0
    errors: list[str] = []
    to_process: list[str] = []
    known_emails: set[str] = set()

    # --- Healthy transactions (risk only) ---
    for i, scenario in enumerate(HEALTHY_TXNS):
        idx = 12 + i  # pay_simulated_13..20
        order_id = f"order_simulated_{idx + 1}"
        payment = _payment_entity(idx, order_id, created_at, scenario, HEALTHY_CUSTOMERS[i])
        known_emails.add(payment["email"].lower())
        try:
            shipping = await _shipping.get_delivery_status(order_id)
            before = risks_created
            async with AsyncSessionLocal() as session:
                exists = (
                    await session.execute(
                        select(TransactionRisk).where(TransactionRisk.payment_id == payment["id"])
                    )
                ).scalar_one_or_none()
            if exists is None:
                await _upsert_risk(payment, {"id": order_id}, shipping, known_emails - {payment["email"].lower()})
                risks_created += 1
            # Force low score for healthy demo contrast
            async with AsyncSessionLocal() as session:
                row = (
                    await session.execute(
                        select(TransactionRisk).where(TransactionRisk.payment_id == payment["id"])
                    )
                ).scalar_one_or_none()
                if row and row.risk_score > 24:
                    row.risk_score = 12.0 + (i % 5)
                    row.risk_level = "low"
                    row.recommended_actions_json = json.dumps(["No action needed"])
                    await session.commit()
            if before == risks_created and exists is None:
                pass
        except Exception as exc:
            errors.append(f"healthy_{idx + 1}: {exc}")
            log.exception("seed.healthy_failed", index=idx)

    # --- Dispute-bound transactions ---
    for index, scenario in enumerate(TEST_SCENARIOS):
        dispute_id = f"disp_simulated_{index + 1}"
        order_id = f"order_simulated_{index + 1}"
        payment = _payment_entity(index, order_id, created_at, scenario, CUSTOMERS[index])
        email_l = payment["email"].lower()
        is_new = email_l not in known_emails
        known_for_score = set(known_emails)
        known_emails.add(email_l)
        respond_by = unix_to_naive(int((now + timedelta(days=7 + (index % 8))).timestamp()))
        try:
            shipping = await _shipping.get_delivery_status(order_id)
            async with AsyncSessionLocal() as session:
                risk_exists = (
                    await session.execute(
                        select(TransactionRisk).where(TransactionRisk.payment_id == payment["id"])
                    )
                ).scalar_one_or_none()
            if risk_exists is None:
                await _upsert_risk(
                    payment,
                    {"id": order_id},
                    shipping,
                    known_for_score if not is_new else set(),
                )
                risks_created += 1
            # Boost dispute-bound risk scores so alerts → disputes look accurate
            async with AsyncSessionLocal() as session:
                row = (
                    await session.execute(
                        select(TransactionRisk).where(TransactionRisk.payment_id == payment["id"])
                    )
                ).scalar_one_or_none()
                if row and row.risk_score < 50:
                    row.risk_score = min(95.0, max(55.0, row.risk_score + 35))
                    row.risk_level = "critical" if row.risk_score >= 75 else "high"
                    await session.commit()

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
                risk = (
                    await session.execute(
                        select(TransactionRisk).where(TransactionRisk.payment_id == payment["id"])
                    )
                ).scalar_one_or_none()
                if risk is not None:
                    risk.alert_status = "dispute_filed"
                await session.commit()
            created += 1
            to_process.append(dispute_id)
            log.info("seed.dispute_created", dispute_id=dispute_id)
        except Exception as exc:
            errors.append(f"{dispute_id}: {exc}")
            log.exception("seed.dispute_failed", index=index)

    for dispute_id in to_process:
        if background_tasks is not None:
            background_tasks.add_task(process_dispute, dispute_id)
        else:
            asyncio.create_task(process_dispute(dispute_id))

    return {
        "created": created,
        "skipped": skipped,
        "risks_created": risks_created,
        "total_disputes": len(TEST_SCENARIOS),
        "total_transactions": len(TEST_SCENARIOS) + len(HEALTHY_TXNS),
        "errors": errors,
    }


def main() -> None:
    result = asyncio.run(seed_test_disputes())
    print(result)


if __name__ == "__main__":
    main()
