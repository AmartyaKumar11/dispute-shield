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

_VPAS = ("customer@okicici", "buyer@ybl", "user@paytm", "shopper@oksbi", "payee@ibl")
_SIGNED = ("Ramesh Kumar", "Sita Devi", "Mohammed Ali", "Lakshmi Nair", "Deepak Rao")

# 12 card/mixed disputes — index 10 is FN (low score forced later)
CARD_DISPUTES: list[dict] = [
    {"amount": 120000, "reason": "product_not_received", "product": "Wireless Headphones", "demo_triage": "auto_submit", "method": "card", "city_tier": 1, "hour": 14},
    {"amount": 340000, "reason": "fraud", "product": "Laptop Stand", "demo_triage": "auto_submit", "method": "card", "city_tier": 1, "hour": 11, "orders_last_24h": 1},
    {"amount": 89000, "reason": "credit_not_processed", "product": "Phone Case", "demo_triage": "auto_submit", "method": "card", "city_tier": 1, "hour": 10},
    {"amount": 250000, "reason": "chargeback", "product": "Running Shoes", "demo_triage": "auto_submit", "method": "card", "city_tier": 2, "hour": 16},
    {"amount": 45000, "reason": "product_not_as_described", "product": "USB Cable", "demo_triage": "auto_submit", "method": "card", "city_tier": 1, "hour": 12},
    {"amount": 780000, "reason": "subscription_canceled", "product": "Annual SaaS Plan", "demo_triage": "auto_submit", "method": "card", "city_tier": 1, "hour": 9},
    {"amount": 150000, "reason": "general", "product": "Bluetooth Speaker", "demo_triage": "auto_submit", "method": "card", "city_tier": 1, "hour": 15},
    {"amount": 210000, "reason": "product_not_received", "product": "Watch Strap", "demo_triage": "review", "method": "card", "city_tier": 3, "hour": 23},
    {"amount": 67000, "reason": "fraud", "product": "Earbuds", "demo_triage": "review", "method": "card", "city_tier": 2, "hour": 2, "orders_last_24h": 3},
    {"amount": 430000, "reason": "chargeback", "product": "Backpack", "demo_triage": "review", "method": "card", "city_tier": 2, "hour": 20},
    # False negative: will force risk_score < 50 but still dispute
    {"amount": 95000, "reason": "credit_not_processed", "product": "Charger", "demo_triage": "accept", "method": "card", "city_tier": 1, "hour": 11, "force_risk": 28, "metric_role": "fn"},
    {"amount": 185000, "reason": "product_not_as_described", "product": "T-Shirt", "demo_triage": "accept", "method": "card", "city_tier": 3, "hour": 3},
]

# 3 UPI disputes
UPI_DISPUTES: list[dict] = [
    {"amount": 275000, "reason": "upi_goods_not_provided", "product": "Smart Watch", "demo_triage": "auto_submit", "method": "upi", "city_tier": 2, "hour": 14, "vpa": "buyer@ybl"},
    {"amount": 199000, "reason": "upi_unauthorized", "product": "Gaming Mouse", "demo_triage": "review", "method": "upi", "city_tier": 1, "hour": 22, "vpa": "user@paytm", "orders_last_24h": 2},
    {"amount": 149000, "reason": "upi_duplicate_transaction", "product": "USB Hub", "demo_triage": "auto_submit", "method": "upi", "city_tier": 1, "hour": 13, "vpa": "customer@okicici"},
]

# Clean txs: 8 low + 2 FP (high risk, no dispute) + 2 clean UPI
CLEAN_TXNS: list[dict] = [
    {"amount": 49900, "product": "Notebook Set", "method": "upi", "city_tier": 1, "hour": 11, "force_risk": 12},
    {"amount": 129900, "product": "Kitchen Towels", "method": "upi", "city_tier": 1, "hour": 14, "force_risk": 14},
    {"amount": 79900, "product": "Water Bottle", "method": "upi", "city_tier": 1, "hour": 10, "force_risk": 10},
    {"amount": 24900, "product": "Stationery Pack", "method": "card", "city_tier": 1, "hour": 16, "force_risk": 15},
    {"amount": 159900, "product": "Desk Organizer", "method": "upi", "city_tier": 1, "hour": 12, "force_risk": 11},
    {"amount": 99900, "product": "Phone Stand", "method": "upi", "city_tier": 1, "hour": 13, "force_risk": 13},
    {"amount": 34900, "product": "Socks Pack", "method": "card", "city_tier": 1, "hour": 15, "force_risk": 9},
    {"amount": 59900, "product": "Mouse Pad", "method": "upi", "city_tier": 1, "hour": 17, "force_risk": 16},
    # False positives — high risk, never disputed
    {"amount": 620000, "product": "Designer Bag", "method": "card", "city_tier": 3, "hour": 1, "force_risk": 72, "metric_role": "fp", "orders_last_24h": 3},
    {"amount": 510000, "product": "Premium Sneakers", "method": "card", "city_tier": 3, "hour": 2, "force_risk": 68, "metric_role": "fp", "orders_last_24h": 2},
    # Extra clean UPI
    {"amount": 89000, "product": "Power Bank", "method": "upi", "city_tier": 1, "hour": 11, "force_risk": 18, "vpa": "shopper@oksbi"},
    {"amount": 45000, "product": "Cable Pack", "method": "upi", "city_tier": 1, "hour": 12, "force_risk": 8, "vpa": "payee@ibl"},
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
    ("Kabir Khan", "kabir.k@example.com", "+919811122233"),
    ("Tara Sen", "tara.sen@example.com", "+919822233344"),
    ("Yash Mehta", "yash.m@example.com", "+919833344455"),
]

CLEAN_CUSTOMERS: list[tuple[str, str, str]] = [
    ("Neha Kapoor", "neha.kapoor@example.com", "+919700000001"),
    ("Siddharth Rao", "sid.rao@example.com", "+919700000002"),
    ("Isha Banerjee", "isha.b@example.com", "+919700000003"),
    ("Farhan Ali", "farhan.ali@example.com", "+919700000004"),
    ("Kavya Menon", "kavya.m@example.com", "+919700000005"),
    ("Dev Patel", "dev.patel@example.com", "+919700000006"),
    ("Riya Shah", "riya.shah@example.com", "+919700000007"),
    ("Nikhil Jain", "nikhil.j@example.com", "+919700000008"),
    ("Asha Reddy", "asha.r@example.com", "+919700000009"),
    ("Vivek Nair", "vivek.n@example.com", "+919700000010"),
    ("Mira Das", "mira.das@example.com", "+919700000011"),
    ("Omar Sheikh", "omar.s@example.com", "+919700000012"),
]

_ADDRESSES = {
    1: "12, Linking Road, Bandra West, Mumbai, Maharashtra 400050",
    2: "45, MG Road, Shivajinagar, Pune, Maharashtra 411005",
    3: "88, Civil Lines, Nagpur, Maharashtra 440001",
}

_shipping = MockShippingProvider()

# Back-compat aliases used by older imports/tests
TEST_SCENARIOS = CARD_DISPUTES + UPI_DISPUTES
HEALTHY_TXNS = CLEAN_TXNS


def _upi_fields(index: int, scenario: dict) -> dict:
    if (scenario.get("method") or "card").lower() != "upi":
        return {}
    vpa = scenario.get("vpa") or _VPAS[index % len(_VPAS)]
    return {
        "vpa": vpa,
        "upi_transaction_id": f"{(index + 1) * 111_222_333_444 % 10**12:012d}",
        "bank_reference": f"UPI{(index + 37) * 7919 % 10**9:09X}"[:9],
    }


def _payment_entity(index: int, order_id: str, created_at: int, scenario: dict, customer: tuple) -> dict:
    name, email, contact = customer
    hour = int(scenario.get("hour") or 12)
    base = datetime.fromtimestamp(created_at, tz=timezone.utc).replace(
        hour=hour % 24, minute=0, second=0, microsecond=0
    )
    payment = {
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
    payment.update(_upi_fields(index, scenario))
    return payment


def _build_vault(index: int, shipping, disputed: bool, order_day: datetime) -> tuple[list[str], list[dict]]:
    signed = _SIGNED[index % len(_SIGNED)]
    carrier = shipping.carrier if shipping else "Delhivery"
    tracking = shipping.tracking_id if shipping else f"TRK{index:08d}"
    delivered = shipping and shipping.status == "delivered"
    fields = ["billing_proof", "access_activity_log"]
    timeline = [
        {
            "day": 0,
            "at": (order_day).isoformat(),
            "text": "Day 0 — Order placed. Checkout metadata stored.",
            "ok": True,
        },
        {
            "day": 1,
            "at": (order_day + timedelta(days=1)).isoformat(),
            "text": f"Day 1 — Shipped via {carrier}. Tracking {tracking} registered.",
            "ok": True,
        },
    ]
    fields.append("shipping_proof")
    if delivered:
        fields.append("delivery_photo")
        timeline.append(
            {
                "day": 3,
                "at": (order_day + timedelta(days=3)).isoformat(),
                "text": f"Day 3 — Delivered. Delivery photo captured. Signed by {signed}.",
                "ok": True,
            }
        )
    else:
        timeline.append(
            {
                "day": 3,
                "at": (order_day + timedelta(days=3)).isoformat(),
                "text": "Day 3 — Delivery pending / RTO. Shipping proof incomplete.",
                "ok": False,
            }
        )
    fields.append("customer_communication")
    timeline.append(
        {
            "day": 5,
            "at": (order_day + timedelta(days=5)).isoformat(),
            "text": "Day 5 — Follow-up email sent. Customer replied.",
            "ok": True,
        }
    )
    # unique preserve order
    fields = list(dict.fromkeys(fields))
    coverage = int(round(len(fields) / 5 * 100))
    if disputed:
        timeline.append(
            {
                "day": 8,
                "at": (order_day + timedelta(days=8)).isoformat(),
                "text": f"Day 8 — ⚠ DISPUTE FILED — Evidence vault {coverage}% complete",
                "ok": False,
                "warn": True,
            }
        )
    else:
        timeline.append(
            {
                "day": 8,
                "at": (order_day + timedelta(days=8)).isoformat(),
                "text": "No dispute filed — transaction clean",
                "ok": True,
            }
        )
    return fields, timeline


def _level(score: float) -> str:
    if score >= 75:
        return "critical"
    if score >= 50:
        return "high"
    if score >= 25:
        return "medium"
    return "low"


async def _save_risk(
    payment: dict,
    shipping,
    known_emails: set[str],
    force_risk: float | None,
    disputed: bool,
    order_day: datetime,
    index: int,
) -> bool:
    assessment = await score_transaction_risk(
        payment, {"id": payment.get("order_id")}, shipping, known_emails=known_emails, use_llm=False
    )
    score = float(force_risk) if force_risk is not None else assessment.risk_score
    if force_risk is None and disputed and score < 50:
        score = min(95.0, max(55.0, score + 35))
    fields, timeline = _build_vault(index, shipping, disputed, order_day)
    async with AsyncSessionLocal() as session:
        existing = (
            await session.execute(
                select(TransactionRisk).where(TransactionRisk.payment_id == payment["id"])
            )
        ).scalar_one_or_none()
        if existing is not None:
            return False
        session.add(
            TransactionRisk(
                payment_id=payment["id"],
                order_id=payment.get("order_id"),
                amount_paise=int(payment["amount"]),
                payment_method=str(payment.get("method") or "card"),
                risk_score=score,
                risk_level=_level(score),
                risk_factors_json=json.dumps([f.__dict__ for f in assessment.risk_factors]),
                recommended_actions_json=json.dumps(assessment.recommended_actions),
                predicted_dispute_type=assessment.predicted_dispute_type,
                alert_status="dispute_filed" if disputed else "active",
                vault_fields_json=json.dumps(fields),
                vault_timeline_json=json.dumps(timeline),
                payment_data_json=json.dumps(payment),
            )
        )
        await session.commit()
    return True


async def seed_test_disputes(background_tasks: BackgroundTasks | None = None) -> dict:
    now = datetime.now(timezone.utc)
    created_at = int(now.timestamp())
    order_day = now - timedelta(days=8)
    created = 0
    skipped = 0
    risks_created = 0
    errors: list[str] = []
    to_process: list[str] = []
    known_emails: set[str] = set()

    dispute_scenarios = CARD_DISPUTES + UPI_DISPUTES

    # Clean first so known_emails reflects established customers for some scores
    for i, scenario in enumerate(CLEAN_TXNS):
        idx = len(dispute_scenarios) + i
        order_id = f"order_simulated_{idx + 1}"
        cust = CLEAN_CUSTOMERS[i % len(CLEAN_CUSTOMERS)]
        payment = _payment_entity(idx, order_id, created_at, scenario, cust)
        try:
            shipping = await _shipping.get_delivery_status(order_id)
            made = await _save_risk(
                payment,
                shipping,
                set(known_emails),
                scenario.get("force_risk"),
                disputed=False,
                order_day=order_day,
                index=idx,
            )
            if made:
                risks_created += 1
            known_emails.add(payment["email"].lower())
        except Exception as exc:
            errors.append(f"clean_{idx + 1}: {exc}")
            log.exception("seed.clean_failed", index=idx)

    for index, scenario in enumerate(dispute_scenarios):
        dispute_id = f"disp_simulated_{index + 1}"
        order_id = f"order_simulated_{index + 1}"
        cust = CUSTOMERS[index % len(CUSTOMERS)]
        payment = _payment_entity(index, order_id, created_at, scenario, cust)
        email_l = payment["email"].lower()
        known_for = set(known_emails)
        known_emails.add(email_l)
        respond_by = unix_to_naive(int((now + timedelta(days=7 + (index % 8))).timestamp()))
        try:
            shipping = await _shipping.get_delivery_status(order_id)
            made = await _save_risk(
                payment,
                shipping,
                known_for,
                scenario.get("force_risk"),
                disputed=True,
                order_day=order_day,
                index=index,
            )
            if made:
                risks_created += 1

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
            log.info("seed.dispute_created", dispute_id=dispute_id, reason=scenario["reason"])
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
        "total_disputes": len(dispute_scenarios),
        "total_transactions": len(dispute_scenarios) + len(CLEAN_TXNS),
        "errors": errors,
    }


def main() -> None:
    result = asyncio.run(seed_test_disputes())
    print(result)


if __name__ == "__main__":
    main()
