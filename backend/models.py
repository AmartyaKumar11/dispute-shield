from __future__ import annotations

import json
from datetime import datetime

from pydantic import BaseModel, Field
from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class Dispute(Base):
    __tablename__ = "disputes"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    payment_id: Mapped[str] = mapped_column(String, nullable=False)
    order_id: Mapped[str | None] = mapped_column(String, nullable=True)
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String, default="INR")
    reason_code: Mapped[str] = mapped_column(String, nullable=False)
    phase: Mapped[str] = mapped_column(String, nullable=False)
    respond_by: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    status: Mapped[str] = mapped_column(String, default="received")

    payment_data_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_data_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    shipping_data_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    comms_data_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    refund_data_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    explanation_letter: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_strategy: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_analysis_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    win_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    win_probability_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    triage_action: Mapped[str | None] = mapped_column(String, nullable=True)
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    documents_uploaded: Mapped[str | None] = mapped_column(Text, nullable=True)
    contest_response_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    processing_completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    def to_response(self) -> DisputeResponse:
        strategy: dict | None = None
        if self.evidence_strategy:
            try:
                parsed = json.loads(self.evidence_strategy)
                strategy = parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                strategy = None

        processing_time: float | None = None
        if self.processing_completed_at:
            start = self.created_at or self.processing_started_at
            if start:
                processing_time = (self.processing_completed_at - start).total_seconds()

        analysis: dict | None = None
        if self.evidence_analysis_json:
            try:
                parsed_a = json.loads(self.evidence_analysis_json)
                analysis = parsed_a if isinstance(parsed_a, dict) else None
            except json.JSONDecodeError:
                analysis = None

        return DisputeResponse(
            id=self.id,
            payment_id=self.payment_id,
            order_id=self.order_id,
            amount_rupees=self.amount_paise / 100,
            currency=self.currency,
            reason_code=self.reason_code,
            phase=self.phase,
            status=self.status,
            respond_by=self.respond_by,
            explanation_letter=self.explanation_letter,
            evidence_strategy=strategy,
            evidence_analysis=analysis,
            win_probability=self.win_probability,
            win_probability_reasoning=self.win_probability_reasoning,
            triage_action=self.triage_action,
            review_reason=self.review_reason,
            processing_time_seconds=processing_time,
            error_message=self.error_message,
            created_at=self.created_at,
        )


class TransactionRisk(Base):
    __tablename__ = "transaction_risks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    payment_id: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    order_id: Mapped[str | None] = mapped_column(String, nullable=True)
    amount_paise: Mapped[int] = mapped_column(Integer, default=0)
    risk_score: Mapped[float] = mapped_column(Float, nullable=False)
    risk_level: Mapped[str] = mapped_column(String, nullable=False)
    risk_factors_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_actions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    predicted_dispute_type: Mapped[str | None] = mapped_column(String, nullable=True)
    alert_status: Mapped[str] = mapped_column(String, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    def to_response(self, dispute_id: str | None = None) -> RiskResponse:
        factors = []
        actions = []
        try:
            factors = json.loads(self.risk_factors_json or "[]")
        except json.JSONDecodeError:
            factors = []
        try:
            actions = json.loads(self.recommended_actions_json or "[]")
        except json.JSONDecodeError:
            actions = []
        return RiskResponse(
            id=self.id,
            payment_id=self.payment_id,
            order_id=self.order_id,
            amount_rupees=self.amount_paise / 100,
            risk_score=self.risk_score,
            risk_level=self.risk_level,
            risk_factors=factors if isinstance(factors, list) else [],
            recommended_actions=actions if isinstance(actions, list) else [],
            predicted_dispute_type=self.predicted_dispute_type,
            alert_status=self.alert_status,
            dispute_id=dispute_id,
            created_at=self.created_at,
        )


class DisputeResponse(BaseModel):
    id: str
    payment_id: str
    order_id: str | None
    amount_rupees: float
    currency: str
    reason_code: str
    phase: str
    status: str
    respond_by: datetime
    explanation_letter: str | None
    evidence_strategy: dict | None
    evidence_analysis: dict | None = None
    win_probability: float | None = None
    win_probability_reasoning: str | None = None
    triage_action: str | None = None
    review_reason: str | None = None
    processing_time_seconds: float | None
    error_message: str | None
    created_at: datetime


class DisputeListResponse(BaseModel):
    disputes: list[DisputeResponse]
    total: int


class RiskResponse(BaseModel):
    id: int
    payment_id: str
    order_id: str | None
    amount_rupees: float
    risk_score: float
    risk_level: str
    risk_factors: list[dict]
    recommended_actions: list[str]
    predicted_dispute_type: str | None
    alert_status: str
    dispute_id: str | None = None
    created_at: datetime


class RiskListResponse(BaseModel):
    risks: list[RiskResponse]
    total: int


class RiskSummary(BaseModel):
    total_transactions: int
    by_level: dict[str, int]
    high_risk_count: int
    alerts_that_became_disputes: int
    prediction_accuracy: float
    avg_risk_score: float


class MetricsSummary(BaseModel):
    total_disputes: int
    by_status: dict[str, int]
    by_reason_code: dict[str, int]
    avg_processing_time_seconds: float
    evidence_coverage_rate: float
    submission_rate: float
    total_amount_disputed_rupees: float
    total_amount_contested_rupees: float


class WebhookPayload(BaseModel):
    entity: str
    account_id: str
    event: str
    contains: list[str] = Field(default_factory=list)
    payload: dict
    created_at: int
