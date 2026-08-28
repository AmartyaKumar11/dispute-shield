from __future__ import annotations

from fastapi import APIRouter

from backend.ml.predictor import predictor

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("/info")
async def models_info() -> dict:
    return predictor.get_model_info()
