from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import structlog

from backend.config import settings
from backend.providers.base import ShippingInfo, ShippingProvider

log = structlog.get_logger(__name__)

_CARRIERS = ("Delhivery", "BlueDart", "DTDC", "Ecom Express", "Shadowfax")
_ADDRESSES = (
    "12, Linking Road, Bandra West, Mumbai, Maharashtra 400050",
    "45, MG Road, Shivajinagar, Pune, Maharashtra 411005",
    "88, 100 Feet Road, Indiranagar, Bengaluru, Karnataka 560038",
    "22, Connaught Place, New Delhi, Delhi 110001",
    "7, Road No. 12, Banjara Hills, Hyderabad, Telangana 500034",
    "19, FC Road, Deccan Gymkhana, Pune, Maharashtra 411004",
    "3, Koramangala 5th Block, Bengaluru, Karnataka 560095",
)
_SIGNED_BY = (
    "Ramesh Kumar",
    "Sita Devi",
    "Mohammed Ali",
    "Lakshmi Nair",
    "Deepak Rao",
    "Anjali Mehta",
    "Suresh Patil",
)


def _seed(order_id: str) -> int:
    return int(hashlib.md5(order_id.encode()).hexdigest(), 16)


def _tracking(carrier: str, seed: int) -> str:
    if carrier == "Delhivery":
        return f"{seed % 10**13:013d}"
    if carrier == "BlueDart":
        return f"{(seed % 90_000_000_000) + 10_000_000_000:011d}"
    if carrier == "DTDC":
        return f"D{seed % 10**10:010d}"
    if carrier == "Ecom Express":
        return f"7{seed % 10**13:013d}"[:14]
    return f"SFX{seed % 10**12:012d}"


class MockShippingProvider(ShippingProvider):
    async def get_delivery_status(self, order_id: str) -> ShippingInfo:
        seed = _seed(order_id)
        roll = seed % 100
        # h % 12 == 11 guarantees ~1/12 RTO so the demo always has a shipping gap
        if roll >= 95 or seed % 12 == 11:
            status = "returned"
        elif roll >= 80:
            status = "in_transit"
        else:
            status = "delivered"

        carrier = _CARRIERS[seed % len(_CARRIERS)]
        address = _ADDRESSES[seed % len(_ADDRESSES)]
        transit_days = 2 + (seed % 6)
        order_age = 10 + (seed % 11)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        shipped_at = now - timedelta(days=order_age)
        delivered_at = shipped_at + timedelta(days=transit_days) if status == "delivered" else None
        if status == "in_transit":
            delivered_at = None
        if status == "returned":
            delivered_at = None

        signed_by = _SIGNED_BY[seed % len(_SIGNED_BY)] if status == "delivered" else None
        pod = None
        if status == "delivered":
            pod = f"https://track.example.in/pod/{_tracking(carrier, seed)}"

        return ShippingInfo(
            tracking_id=_tracking(carrier, seed),
            carrier=carrier,
            status=status,
            shipped_at=shipped_at,
            delivered_at=delivered_at,
            delivery_address=address,
            signed_by=signed_by,
            proof_of_delivery_url=pod,
        )


_mock_shipping = MockShippingProvider()


async def get_shipping_info(order_id: str) -> ShippingInfo:
    """Try Shiprocket first when enabled; fall back to mock for demo orders."""
    if (
        settings.shiprocket_enabled
        and settings.shiprocket_email
        and settings.shiprocket_password
    ):
        try:
            from backend.providers.shiprocket_provider import shiprocket

            result = await shiprocket.get_delivery_status(order_id)
            if result is not None:
                return result
        except Exception:
            log.exception("shipping.shiprocket_fallback", order_id=order_id)
    return await _mock_shipping.get_delivery_status(order_id)
