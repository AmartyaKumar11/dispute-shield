from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from backend.config import settings

engine = create_async_engine(settings.database_url, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db() -> None:
    from backend import models  # noqa: F401 — register tables on Base.metadata

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_sqlite_add_missing_columns)


def _sqlite_add_missing_columns(sync_conn) -> None:
    """SQLite create_all won't ALTER existing tables — add new columns if missing."""
    from sqlalchemy import text

    defs = {
        "disputes": {
            "evidence_analysis_json": "TEXT",
            "win_probability": "FLOAT",
            "win_probability_reasoning": "TEXT",
            "triage_action": "VARCHAR",
            "review_reason": "TEXT",
            "resolution_message": "TEXT",
            "resolution_offer_status": "VARCHAR",
            "resolution_offer_sent_at": "DATETIME",
            "resolution_offer_email": "VARCHAR",
        },
        "transaction_risks": {
            "payment_method": "VARCHAR",
            "vault_fields_json": "TEXT",
            "vault_timeline_json": "TEXT",
            "payment_data_json": "TEXT",
            "customer_email": "VARCHAR",
            "intervention_message": "TEXT",
            "intervention_sent_at": "DATETIME",
            "intervention_email_status": "VARCHAR",
        },
    }
    for table, cols in defs.items():
        existing = {
            row[1]
            for row in sync_conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        }
        for col, typ in cols.items():
            if col not in existing:
                sync_conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {typ}"))



async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
