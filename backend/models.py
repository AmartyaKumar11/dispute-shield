from __future__ import annotations

import json
from datetime import datetime

from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func
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

    resolution_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution_offer_status: Mapped[str | None] = mapped_column(String, nullable=True)
    resolution_offer_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolution_offer_email: Mapped[str | None] = mapped_column(String, nullable=True)

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
            resolution_offer_status=self.resolution_offer_status,
            resolution_offer_sent_at=self.resolution_offer_sent_at,
            resolution_offer_email=self.resolution_offer_email,
            resolution_message=self.resolution_message,
        )


class TransactionRisk(Base):
    __tablename__ = "transaction_risks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    payment_id: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    order_id: Mapped[str | None] = mapped_column(String, nullable=True)
    amount_paise: Mapped[int] = mapped_column(Integer, default=0)
    payment_method: Mapped[str] = mapped_column(String, default="card")
    risk_score: Mapped[float] = mapped_column(Float, nullable=False)
    risk_level: Mapped[str] = mapped_column(String, nullable=False)
    risk_factors_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_actions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    predicted_dispute_type: Mapped[str | None] = mapped_column(String, nullable=True)
    alert_status: Mapped[str] = mapped_column(String, default="active")
    vault_fields_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    vault_timeline_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_data_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    customer_email: Mapped[str | None] = mapped_column(String, nullable=True)
    intervention_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    intervention_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    intervention_email_status: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    def to_response(
        self,
        dispute_id: str | None = None,
        portal_badge: str | None = None,
    ) -> RiskResponse:
        factors = []
        actions = []
        vault_fields: list = []
        timeline: list = []
        try:
            factors = json.loads(self.risk_factors_json or "[]")
        except json.JSONDecodeError:
            factors = []
        try:
            actions = json.loads(self.recommended_actions_json or "[]")
        except json.JSONDecodeError:
            actions = []
        try:
            vault_fields = json.loads(self.vault_fields_json or "[]")
        except json.JSONDecodeError:
            vault_fields = []
        try:
            timeline = json.loads(self.vault_timeline_json or "[]")
        except json.JSONDecodeError:
            timeline = []
        return RiskResponse(
            id=self.id,
            payment_id=self.payment_id,
            order_id=self.order_id,
            amount_rupees=self.amount_paise / 100,
            payment_method=self.payment_method or "card",
            risk_score=self.risk_score,
            risk_level=self.risk_level,
            risk_factors=factors if isinstance(factors, list) else [],
            recommended_actions=actions if isinstance(actions, list) else [],
            predicted_dispute_type=self.predicted_dispute_type,
            alert_status=self.alert_status,
            vault_fields=vault_fields if isinstance(vault_fields, list) else [],
            vault_timeline=timeline if isinstance(timeline, list) else [],
            vault_field_count=len(vault_fields) if isinstance(vault_fields, list) else 0,
            vault_field_total=5,
            dispute_id=dispute_id,
            created_at=self.created_at,
            customer_email=self.customer_email,
            intervention_message=self.intervention_message,
            intervention_sent_at=self.intervention_sent_at,
            intervention_email_status=self.intervention_email_status,
            portal_badge=portal_badge,
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
    resolution_offer_status: str | None = None
    resolution_offer_sent_at: datetime | None = None
    resolution_offer_email: str | None = None
    resolution_message: str | None = None


class DisputeListResponse(BaseModel):
    disputes: list[DisputeResponse]
    total: int


class RiskResponse(BaseModel):
    id: int
    payment_id: str
    order_id: str | None
    amount_rupees: float
    payment_method: str = "card"
    risk_score: float
    risk_level: str
    risk_factors: list[dict]
    recommended_actions: list[str]
    predicted_dispute_type: str | None
    alert_status: str
    vault_fields: list[str] = Field(default_factory=list)
    vault_timeline: list[dict] = Field(default_factory=list)
    vault_field_count: int = 0
    vault_field_total: int = 5
    dispute_id: str | None = None
    created_at: datetime
    customer_email: str | None = None
    intervention_message: str | None = None
    intervention_sent_at: datetime | None = None
    intervention_email_status: str | None = None
    portal_badge: str | None = None


class EscalationEvent(Base):
    __tablename__ = "escalation_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    source: Mapped[str] = mapped_column(String, nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    order_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    processed: Mapped[bool] = mapped_column(Integer, default=0)


class EscalationAlert(Base):
    __tablename__ = "escalation_alerts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    rule_id: Mapped[str] = mapped_column(String, nullable=False)
    event_id: Mapped[str | None] = mapped_column(String, nullable=True)
    order_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    payment_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    customer_email: Mapped[str | None] = mapped_column(String, nullable=True)
    transaction_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    product_name: Mapped[str | None] = mapped_column(String, nullable=True)
    severity: Mapped[str] = mapped_column(String, default="high")
    signal_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    intervention_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    intervention_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    intervention_email_status: Mapped[str | None] = mapped_column(String, nullable=True)
    state: Mapped[str] = mapped_column(String, default="OPEN")
    state_history_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


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
    transactions_protected: int = 0
    evidence_fields_precollected: int = 0
    disputes_anticipated: int = 0
    vault_hit_rate: float = 0.0


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


class PortalSession(Base):
    __tablename__ = "portal_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    order_token: Mapped[str] = mapped_column(String, nullable=False, index=True)
    order_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    payment_id: Mapped[str | None] = mapped_column(String, nullable=True)
    customer_email: Mapped[str | None] = mapped_column(String, nullable=True)

    status: Mapped[str] = mapped_column(String, default="active")
    viewed_order_status: Mapped[bool] = mapped_column(Boolean, default=False)
    requested_refund: Mapped[bool] = mapped_column(Boolean, default=False)
    requested_replacement: Mapped[bool] = mapped_column(Boolean, default=False)
    started_chat: Mapped[bool] = mapped_column(Boolean, default=False)

    resolution_type: Mapped[str | None] = mapped_column(String, nullable=True)
    resolution_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    refund_amount_paise: Mapped[int | None] = mapped_column(Integer, nullable=True)
    refund_id: Mapped[str | None] = mapped_column(String, nullable=True)

    chat_history_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    dispute_filed_after: Mapped[bool] = mapped_column(Boolean, default=False)
    linked_dispute_id: Mapped[str | None] = mapped_column(String, nullable=True)

    started_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class PortalConfig(Base):
    __tablename__ = "portal_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    auto_refund_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_refund_max_amount_paise: Mapped[int] = mapped_column(Integer, default=200000)
    merchant_name: Mapped[str] = mapped_column(String, default="Merchant")
    support_email: Mapped[str | None] = mapped_column(String, nullable=True)
    token_secret: Mapped[str] = mapped_column(String, default="disputeshield-portal-secret")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())


class GenerateLinkRequest(BaseModel):
    order_id: str
    payment_id: str | None = None
    customer_email: str | None = None


class GenerateLinkResponse(BaseModel):
    portal_url: str
    token: str


class RefundRequest(BaseModel):
    reason: str
    detail: str | None = None


class RefundResponse(BaseModel):
    success: bool
    refund_type: str
    refund_id: str | None = None
    refund_amount_rupees: float | None = None
    estimated_days: str | None = None
    message: str


class ReplacementRequest(BaseModel):
    reason: str
    detail: str


class ReplacementResponse(BaseModel):
    success: bool
    message: str
    ticket_id: str


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str
    suggested_actions: list[str] = Field(default_factory=list)
    session_id: str
    resolution_detected: bool = False
    resolution_type: str | None = None


class PortalMetricsResponse(BaseModel):
    total_portal_visits: int
    total_resolved: int
    resolution_breakdown: dict[str, int]
    deflection_rate: float
    disputes_after_portal: int
    disputes_without_portal: int
    avg_resolution_time_seconds: float
    total_refunds_issued_rupees: float
    estimated_chargebacks_prevented: int
    estimated_savings_rupees: float
