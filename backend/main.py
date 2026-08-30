from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import BackgroundTasks, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings
from backend.database import init_db
from backend.routers import (
    disputes,
    evaluation,
    events,
    health,
    intelligence,
    metrics,
    models,
    portal,
    risks,
    test_integrations,
    webhooks,
)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    await init_db()
    yield


app = FastAPI(title="DisputeShield", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.frontend_url,
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(webhooks.router)
app.include_router(events.router)
app.include_router(disputes.router)
app.include_router(metrics.router)
app.include_router(risks.router)
app.include_router(intelligence.router)
app.include_router(evaluation.router)
app.include_router(models.router)
app.include_router(test_integrations.router)
app.include_router(portal.router)
app.include_router(health.router)


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "OK"}


@app.post("/api/seed/create-test-disputes")
async def create_test_disputes(background_tasks: BackgroundTasks) -> dict:
    from backend.seed.seed_disputes import seed_test_disputes

    return await seed_test_disputes(background_tasks)
