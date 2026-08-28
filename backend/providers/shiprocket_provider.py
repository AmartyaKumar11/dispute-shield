from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import structlog

from backend.config import settings
from backend.providers.base import ShippingInfo

log = structlog.get_logger(__name__)

TOKEN_PATH = Path(__file__).resolve().parents[1] / "ml" / "models" / "shiprocket_token.json"


def _parse_dt(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    text = str(value).strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d",
        "%d-%m-%Y %H:%M",
        "%d/%m/%Y %H:%M",
    ):
        try:
            return datetime.strptime(text[:26], fmt)
        except ValueError:
            continue
    return None


class ShiprocketProvider:
    """Real Shiprocket API integration with file-cached auth tokens."""

    def __init__(self) -> None:
        self.base_url = settings.shiprocket_base_url.rstrip("/")
        self.token: str | None = None
        self.token_expires: datetime | None = None
        self._last_login_at: datetime | None = None
        self._load_token_cache()

    def _load_token_cache(self) -> None:
        try:
            if not TOKEN_PATH.exists():
                return
            data = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
            token = data.get("token")
            expires_raw = data.get("token_expires")
            if not token or not expires_raw:
                return
            expires = datetime.fromisoformat(str(expires_raw))
            if datetime.utcnow() < expires:
                self.token = str(token)
                self.token_expires = expires
                log.info("shiprocket.token_cache_hit", expires=expires.isoformat())
            else:
                log.info("shiprocket.token_cache_expired")
        except Exception:
            log.exception("shiprocket.token_cache_load_failed")

    def _save_token_cache(self) -> None:
        if not self.token or not self.token_expires:
            return
        try:
            TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
            TOKEN_PATH.write_text(
                json.dumps(
                    {
                        "token": self.token,
                        "token_expires": self.token_expires.isoformat(),
                        "saved_at": datetime.utcnow().isoformat(),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            log.info("shiprocket.token_cache_saved", path=str(TOKEN_PATH))
        except Exception:
            log.exception("shiprocket.token_cache_save_failed")

    def _clear_token_cache(self) -> None:
        self.token = None
        self.token_expires = None
        try:
            if TOKEN_PATH.exists():
                TOKEN_PATH.unlink()
                log.info("shiprocket.token_cache_cleared")
        except Exception:
            log.exception("shiprocket.token_cache_clear_failed")

    def _can_login(self) -> bool:
        """Never retry login more than once per minute."""
        if self._last_login_at is None:
            return True
        return datetime.utcnow() - self._last_login_at >= timedelta(minutes=1)

    async def _login(self) -> str:
        if not settings.shiprocket_email or not settings.shiprocket_password:
            raise RuntimeError("Shiprocket credentials not configured")
        if not self._can_login():
            raise RuntimeError("Shiprocket login rate-limited (max once per minute)")

        self._last_login_at = datetime.utcnow()
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.base_url}/auth/login",
                json={
                    "email": settings.shiprocket_email,
                    "password": settings.shiprocket_password,
                },
            )
            response.raise_for_status()
            data = response.json()
            token = data.get("token")
            if not token:
                raise RuntimeError(f"Shiprocket login missing token: {data}")
            self.token = str(token)
            # Tokens last ~10 days — refresh after 9
            self.token_expires = datetime.utcnow() + timedelta(days=9)
            self._save_token_cache()
            log.info("shiprocket.login_ok", expires=self.token_expires.isoformat())
            return self.token

    async def _get_token(self, *, force_refresh: bool = False) -> str:
        if not force_refresh and self.token and self.token_expires and datetime.utcnow() < self.token_expires:
            return self.token
        if not force_refresh:
            self._load_token_cache()
            if self.token and self.token_expires and datetime.utcnow() < self.token_expires:
                return self.token
        return await self._login()

    async def _headers(self, *, force_refresh: bool = False) -> dict[str, str]:
        token = await self._get_token(force_refresh=force_refresh)
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
        params: dict | None = None,
        timeout: float = 30.0,
    ) -> dict:
        """HTTP helper: on 401/403 clear cache, refresh token once, retry once."""
        if not settings.shiprocket_enabled:
            raise RuntimeError("Shiprocket disabled (SHIPROCKET_ENABLED=false)")

        async def _do(force_refresh: bool = False) -> httpx.Response:
            headers = await self._headers(force_refresh=force_refresh)
            async with httpx.AsyncClient(timeout=timeout) as client:
                return await client.request(
                    method,
                    f"{self.base_url}{path}",
                    headers=headers,
                    json=json_body,
                    params=params,
                )

        response = await _do(force_refresh=False)
        if response.status_code in (401, 403):
            log.warning("shiprocket.auth_rejected", status=response.status_code, path=path)
            self._clear_token_cache()
            if not self._can_login():
                response.raise_for_status()
            response = await _do(force_refresh=True)
            if response.status_code in (401, 403):
                log.error("shiprocket.auth_retry_failed", status=response.status_code, path=path)
                response.raise_for_status()

        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {"data": data}

    async def create_order(self, order_data: dict) -> dict:
        return await self._request("POST", "/orders/create/adhoc", json_body=order_data, timeout=45.0)

    async def get_tracking(self, shipment_id: str) -> dict:
        return await self._request("GET", f"/courier/track/shipment/{shipment_id}")

    async def get_tracking_by_order(self, order_id: str) -> dict:
        return await self._request("GET", "/courier/track", params={"order_id": order_id})

    async def get_order_details(self, order_id: str) -> dict:
        return await self._request("GET", f"/orders/show/{order_id}")

    async def get_delivery_status(self, order_id: str) -> ShippingInfo | None:
        """Return ShippingInfo, or None so callers can fall back to mock."""
        if not settings.shiprocket_enabled:
            return None
        try:
            data = await self.get_tracking_by_order(order_id)
            tracking_data = data.get("tracking_data") or {}
            if tracking_data.get("track_status") == 0 or tracking_data.get("error"):
                return None

            shipment_track = tracking_data.get("shipment_track") or []
            if not shipment_track:
                return None

            track = shipment_track[0] if isinstance(shipment_track[0], dict) else {}
            activities = track.get("shipment_track_activities") or []

            sr_status = str(
                tracking_data.get("shipment_status")
                or tracking_data.get("shipment_status_text")
                or track.get("current_status")
                or ""
            ).upper()
            if "DELIVERED" in sr_status:
                status = "delivered"
            elif any(s in sr_status for s in ("RTO", "CANCEL", "LOST")):
                status = "returned"
            elif any(s in sr_status for s in ("TRANSIT", "SHIPPED", "PICKED", "OUT FOR")):
                status = "in_transit"
            else:
                status = "pending"

            shipped_at = None
            delivered_at = None
            for activity in activities:
                if not isinstance(activity, dict):
                    continue
                act_status = str(activity.get("sr-status") or activity.get("status") or "").upper()
                act_date = _parse_dt(activity.get("date"))
                if "PICKED" in act_status and not shipped_at:
                    shipped_at = act_date
                if "DELIVERED" in act_status:
                    delivered_at = act_date

            if not delivered_at:
                delivered_at = _parse_dt(track.get("delivered_date") or tracking_data.get("delivered_date"))
            if not shipped_at:
                shipped_at = _parse_dt(track.get("pickup_date"))

            pod = tracking_data.get("pod") or tracking_data.get("pod_status")
            pod_url = pod if isinstance(pod, str) and pod.startswith("http") else None

            return ShippingInfo(
                tracking_id=str(track.get("awb_code") or ""),
                carrier=str(
                    tracking_data.get("courier_name")
                    or track.get("courier_name")
                    or "Unknown"
                ),
                status=status,
                shipped_at=shipped_at,
                delivered_at=delivered_at,
                delivery_address=str(track.get("destination") or ""),
                signed_by=track.get("delivered_to") or None,
                proof_of_delivery_url=pod_url,
            )
        except Exception:
            log.exception("shiprocket.tracking_failed", order_id=order_id)
            return None

    async def check_serviceability(
        self, pickup_pincode: str, delivery_pincode: str, weight: float
    ) -> dict:
        return await self._request(
            "GET",
            "/courier/serviceability",
            params={
                "pickup_postcode": pickup_pincode,
                "delivery_postcode": delivery_pincode,
                "weight": weight,
                "cod": 0,
            },
        )


shiprocket = ShiprocketProvider()
