from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import PortalConfig

DEFAULT_SECRET = "disputeshield-portal-secret"
TOKEN_TTL_SECONDS = 30 * 24 * 60 * 60


async def get_portal_config(session: AsyncSession) -> PortalConfig:
    cfg = await session.get(PortalConfig, 1)
    if cfg is None:
        cfg = PortalConfig(id=1)
        session.add(cfg)
        await session.flush()
    return cfg


def generate_token(
    order_id: str,
    payment_id: str | None,
    email: str | None,
    secret: str = DEFAULT_SECRET,
    ttl_seconds: int = TOKEN_TTL_SECONDS,
) -> str:
    payload = {
        "order_id": order_id,
        "payment_id": payment_id or "",
        "email": email or "",
        "exp": int(time.time()) + ttl_seconds,
    }
    raw = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
    sig = hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest()
    return f"{raw}.{sig}"


def validate_token(token: str, secret: str = DEFAULT_SECRET) -> dict[str, Any] | None:
    try:
        raw, sig = token.rsplit(".", 1)
    except ValueError:
        return None
    expected = hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(raw.encode()))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    exp = int(payload.get("exp") or 0)
    if exp < int(time.time()):
        return None
    if not payload.get("order_id"):
        return None
    return payload


async def generate_token_for_session(
    session: AsyncSession,
    order_id: str,
    payment_id: str | None = None,
    email: str | None = None,
) -> str:
    cfg = await get_portal_config(session)
    return generate_token(order_id, payment_id, email, secret=cfg.token_secret)


async def validate_token_for_session(session: AsyncSession, token: str) -> dict[str, Any] | None:
    cfg = await get_portal_config(session)
    return validate_token(token, secret=cfg.token_secret)
