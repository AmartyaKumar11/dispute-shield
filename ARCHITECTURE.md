# DisputeShield — Architecture Document

## Product Spec

### Problem Statement
Chargebacks cost merchants 2-3% of total revenue. The net chargeback win rate
after recovery costs is only 8.1%. Most SME merchants on Razorpay do not respond
to disputes because the evidence assembly process is too manual — they receive a
dashboard notification, don't know what evidence to submit, miss the deadline,
and lose the dispute by default. Every uncontested chargeback worsens Razorpay's
aggregate dispute ratio with Visa/Mastercard, increasing interchange costs.

### Solution
An automated agent that:
1. Receives dispute webhooks from Razorpay
2. Analyzes the reason code to determine what evidence is needed
3. Pulls payment/order data from Razorpay APIs (real)
4. Pulls shipping/communication data from external sources (mocked)
5. Generates a tailored explanation letter using an LLM
6. Assembles and uploads evidence documents
7. Submits the contest via Razorpay's Dispute API
8. Tracks outcomes and reports metrics

### Goals
- Auto-assemble evidence for 100% of incoming disputes without merchant intervention
- Generate reason-code-specific explanation letters that address the exact dispute claim
- Submit contests within minutes of dispute creation (vs. days for manual process)
- Show measured metrics: evidence coverage rate, submission rate, assembly time

### Non-Goals
- Not building a fraud detection system (Track 02 is defense, not detection)
- Not replacing Razorpay's enterprise Dispute Responder Agent
- Not handling arbitration or pre-arbitration phases (only chargeback phase)
- Not integrating with real shipping providers (mocked, with clean interfaces)
- Not building user auth or multi-tenant support

---

## System Architecture

### Pipeline Flow

```
[Razorpay Webhook] ──POST──▶ [Webhook Router]
                                    │
                                    ▼
                            [Dispute Service]
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
            [Razorpay Provider] [Shipping Provider] [Comms Provider]
            (REAL API calls)    (MOCK data)         (MOCK data)
                    │               │               │
                    └───────┬───────┘───────────────┘
                            ▼
                    [Evidence Strategy]
                    (reason code → what evidence to gather)
                            │
                            ▼
                    [Explanation Generator]
                    (LLM generates letter)
                            │
                            ▼
                    [Document Builder]
                    (generates PDF evidence docs)
                            │
                            ▼
                    [Razorpay Provider]
                    (upload docs → contest dispute)
                            │
                            ▼
                    [Update DB status]
                            │
                            ▼
                    [Dashboard displays result]
```

---

## Data Models

### Dispute (SQLAlchemy model → SQLite)

```python
class Dispute(Base):
    __tablename__ = "disputes"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # Razorpay dispute ID (disp_xxx)
    payment_id: Mapped[str] = mapped_column(String, nullable=False)  # pay_xxx
    order_id: Mapped[str | None] = mapped_column(String, nullable=True)  # order_xxx
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String, default="INR")
    reason_code: Mapped[str] = mapped_column(String, nullable=False)
    phase: Mapped[str] = mapped_column(String, nullable=False)  # fraud, retrieval, chargeback
    respond_by: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # Processing status
    status: Mapped[str] = mapped_column(String, default="received")
    # Values: received → gathering → assembled → submitting → submitted → won → lost → error

    # Evidence gathered
    payment_data_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    order_data_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    shipping_data_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    comms_data_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    refund_data_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Generated content
    explanation_letter: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_strategy: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON of strategy used
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # max 1000 chars

    # Submission tracking
    documents_uploaded: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list of doc IDs
    contest_response_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Metrics
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    processing_completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())
```

### Pydantic Schemas

```python
class DisputeResponse(BaseModel):
    id: str
    payment_id: str
    order_id: str | None
    amount_rupees: float  # Converted from paise
    currency: str
    reason_code: str
    phase: str
    status: str
    respond_by: datetime
    explanation_letter: str | None
    evidence_strategy: dict | None
    processing_time_seconds: float | None
    error_message: str | None
    created_at: datetime

class DisputeListResponse(BaseModel):
    disputes: list[DisputeResponse]
    total: int

class MetricsSummary(BaseModel):
    total_disputes: int
    by_status: dict[str, int]  # status → count
    by_reason_code: dict[str, int]  # reason_code → count
    avg_processing_time_seconds: float
    evidence_coverage_rate: float  # % of evidence fields filled
    submission_rate: float  # % of disputes that reached "submitted" status
    total_amount_disputed_rupees: float
    total_amount_contested_rupees: float

class WebhookPayload(BaseModel):
    entity: str
    account_id: str
    event: str
    contains: list[str]
    payload: dict
    created_at: int
```

---

## API Endpoints

### Backend (FastAPI)

```
POST /webhooks/razorpay
    - Receives Razorpay webhook for payment.dispute.created
    - Validates webhook signature
    - Saves dispute to DB with status "received"
    - Triggers evidence assembly pipeline as background task
    - Returns 200 immediately (webhook must respond fast)

GET /api/disputes
    - Returns all disputes, ordered by created_at desc
    - Query params: status (optional filter), limit (default 50)
    - Response: DisputeListResponse

GET /api/disputes/{dispute_id}
    - Returns single dispute with full detail
    - Response: DisputeResponse (with all evidence data populated)

GET /api/metrics/summary
    - Returns aggregated metrics across all disputes
    - Response: MetricsSummary

POST /api/disputes/{dispute_id}/retry
    - Re-triggers the evidence assembly pipeline for a failed dispute
    - Only works if status is "error"

POST /api/seed/create-test-disputes
    - Development endpoint: creates test payments+orders in Razorpay test mode
    - Then simulates dispute webhooks for each
    - Creates 10-15 disputes with varied reason codes
```

---

## Evidence Strategy Engine

### Reason Code → Evidence Mapping

This is the core intelligence of the system. Different chargeback reason codes
require different evidence to win the contest.

```python
EVIDENCE_STRATEGIES: dict[str, EvidenceStrategy] = {
    "chargeback": EvidenceStrategy(
        reason_code="chargeback",
        display_name="General Chargeback",
        description="Customer disputes the transaction validity",
        required_evidence=["billing_proof", "explanation_letter"],
        recommended_evidence=["shipping_proof", "customer_communication", "proof_of_service"],
        letter_focus="Emphasize that the transaction was legitimate, authorized, and the product/service was delivered as described.",
    ),
    "fraud": EvidenceStrategy(
        reason_code="fraud",
        display_name="Fraud Dispute",
        description="Bank suspects fraudulent transaction",
        required_evidence=["access_activity_log", "billing_proof", "explanation_letter"],
        recommended_evidence=["shipping_proof", "customer_communication"],
        letter_focus="Present IP address, device info, and transaction patterns showing this was the legitimate cardholder. Highlight any 3DS/OTP verification that occurred.",
    ),
    "product_not_received": EvidenceStrategy(
        reason_code="product_not_received",
        display_name="Product Not Received",
        description="Customer claims they did not receive the product",
        required_evidence=["shipping_proof", "explanation_letter"],
        recommended_evidence=["customer_communication", "billing_proof"],
        letter_focus="Present delivery confirmation, tracking details, and proof of delivery signature. If delivered to correct address, emphasize address match with billing.",
    ),
    "product_not_as_described": EvidenceStrategy(
        reason_code="product_not_as_described",
        display_name="Product Not as Described",
        description="Customer claims product differs from description",
        required_evidence=["proof_of_service", "explanation_letter", "term_and_conditions"],
        recommended_evidence=["customer_communication", "billing_proof"],
        letter_focus="Present product description, order confirmation showing what was ordered, and evidence that delivered product matches. Include refund/return policy.",
    ),
    "credit_not_processed": EvidenceStrategy(
        reason_code="credit_not_processed",
        display_name="Credit Not Processed",
        description="Customer claims a refund was promised but not issued",
        required_evidence=["refund_confirmation", "explanation_letter"],
        recommended_evidence=["customer_communication", "refund_cancellation_policy"],
        letter_focus="If refund was issued, present the refund receipt with ARN. If refund was not applicable, explain why per the return/refund policy with supporting evidence.",
    ),
    "subscription_canceled": EvidenceStrategy(
        reason_code="subscription_canceled",
        display_name="Subscription Canceled",
        description="Customer claims they canceled but were still charged",
        required_evidence=["proof_of_service", "term_and_conditions", "explanation_letter"],
        recommended_evidence=["customer_communication", "billing_proof"],
        letter_focus="Present cancellation policy, evidence of service usage after alleged cancellation date, or proof that cancellation was not received before the billing cycle.",
    ),
    "general": EvidenceStrategy(
        reason_code="general",
        display_name="General Dispute",
        description="Dispute does not fit specific categories",
        required_evidence=["explanation_letter", "billing_proof"],
        recommended_evidence=["shipping_proof", "customer_communication", "proof_of_service"],
        letter_focus="Build a comprehensive case covering transaction legitimacy, product/service delivery, and customer authorization.",
    ),
}
```

### EvidenceStrategy Schema

```python
@dataclass
class EvidenceStrategy:
    reason_code: str
    display_name: str
    description: str
    required_evidence: list[str]    # Evidence fields that MUST be submitted
    recommended_evidence: list[str]  # Evidence fields to include if available
    letter_focus: str               # Instruction for LLM on what to emphasize
```

---

## Provider Interfaces

### Base Provider (Abstract)

```python
class PaymentProvider(ABC):
    @abstractmethod
    async def get_payment(self, payment_id: str) -> dict: ...

    @abstractmethod
    async def get_order(self, order_id: str) -> dict: ...

    @abstractmethod
    async def get_refunds(self, payment_id: str) -> list[dict]: ...

    @abstractmethod
    async def upload_document(self, file_path: str, purpose: str) -> str: ...
    # Returns document_id

    @abstractmethod
    async def contest_dispute(self, dispute_id: str, evidence: dict) -> dict: ...

class ShippingProvider(ABC):
    @abstractmethod
    async def get_delivery_status(self, order_id: str) -> ShippingInfo: ...

class CommunicationProvider(ABC):
    @abstractmethod
    async def get_customer_emails(self, customer_email: str, order_id: str) -> list[EmailRecord]: ...

class LLMProvider(ABC):
    @abstractmethod
    async def generate_explanation_letter(
        self,
        reason_code: str,
        letter_focus: str,
        payment_data: dict,
        order_data: dict,
        shipping_info: ShippingInfo | None,
        refund_data: list[dict],
        comms_data: list[EmailRecord],
    ) -> str: ...
```

### Mock Data Shapes

```python
@dataclass
class ShippingInfo:
    tracking_id: str
    carrier: str  # "Delhivery", "BlueDart", "DTDC", "Shiprocket"
    status: str  # "delivered", "in_transit", "returned", "out_for_delivery"
    shipped_at: datetime | None
    delivered_at: datetime | None
    delivery_address: str
    signed_by: str | None  # Name of person who signed for delivery
    proof_of_delivery_url: str | None

@dataclass
class EmailRecord:
    subject: str
    body_snippet: str  # First 200 chars
    sent_at: datetime
    direction: str  # "inbound" (customer → merchant) or "outbound" (merchant → customer)
    sender: str
    recipient: str
```

### Mock Shipping Provider Implementation Notes

The mock shipping provider should generate REALISTIC Indian e-commerce shipping data:
- Carriers: Delhivery, BlueDart, DTDC, Ecom Express, Shadowfax
- Tracking IDs: format varies by carrier (e.g., Delhivery: 13-digit numeric)
- Addresses: use realistic Indian addresses (Tier 1/2 cities)
- Delivery timelines: 2-7 business days from order date
- For ~80% of orders, status should be "delivered" with a signed_by name
- For ~15%, status should be "in_transit" (still within delivery window)
- For ~5%, status should be "returned" (RTO scenario)
- Use the order_id as a seed for deterministic mock data (same order_id always gives same result)

### Mock Communication Provider Implementation Notes

Generate realistic customer service email threads:
- 2-4 emails per order
- Mix of inbound and outbound
- Typical patterns:
  - Order confirmation (outbound)
  - "Where is my order?" (inbound) → Tracking link sent (outbound)
  - Delivery confirmation (outbound)
  - For dispute-related orders: "I want a refund" (inbound) → Policy explanation (outbound)

---

## Dispute Processing Pipeline

### dispute_service.py — Main Orchestration

```python
async def process_dispute(dispute_id: str) -> None:
    """
    Main pipeline. Called as a FastAPI BackgroundTask.
    Orchestrates the full evidence assembly and submission flow.
    """
    # Step 1: Update status to "gathering"
    # Step 2: Fetch dispute details from Razorpay
    # Step 3: Fetch payment details from Razorpay
    # Step 4: Fetch order details from Razorpay (if order_id exists)
    # Step 5: Check for existing refunds on this payment
    # Step 6: Determine evidence strategy from reason code
    # Step 7: Gather shipping data (mock provider)
    # Step 8: Gather communication data (mock provider)
    # Step 9: Update status to "assembled"
    # Step 10: Generate explanation letter via LLM
    # Step 11: Build evidence documents (PDFs)
    # Step 12: Upload documents to Razorpay
    # Step 13: Submit contest with evidence
    # Step 14: Update status to "submitted" (or "error" if any step fails)
    #
    # CRITICAL: Wrap the entire pipeline in try/except.
    # On ANY failure, update status to "error" with error_message.
    # The pipeline should be RESILIENT — if shipping data is unavailable,
    # still proceed with available evidence. Only the explanation letter
    # and at least ONE document are hard requirements for contest submission.
```

### Failure Handling (IMPORTANT for the demo)

The track bar says: "Show one failure handled gracefully."

Implement this scenario:
- When shipping provider returns no data (status "returned" or provider error),
  the agent should:
  1. Log the gap: "Shipping proof unavailable for order {order_id}"
  2. Adjust the LLM prompt: "Note: shipping proof is not available. Focus the
     explanation on other evidence such as billing proof and transaction legitimacy."
  3. Still submit the contest with whatever evidence IS available
  4. Mark the dispute with a flag: `evidence_gaps: ["shipping_proof"]`
  5. Dashboard should show this gap clearly (amber warning badge)

This demonstrates that the system degrades gracefully rather than failing entirely.

---

## Explanation Letter Generation

### LLM Prompt Template

```python
SYSTEM_PROMPT = """You are a payment dispute resolution specialist working for
an Indian e-commerce merchant. Your job is to write compelling, professional
explanation letters that contest chargeback disputes.

Your letters should be:
- Formal and professional in tone
- Structured with clear paragraphs
- Specific to the dispute reason code
- Backed by concrete evidence (dates, amounts, tracking numbers)
- 500-800 words
- Addressed to "Dear Dispute Resolution Team"
- Signed as "Merchant Dispute Resolution Team"

Do NOT:
- Be aggressive or accusatory toward the customer
- Make claims not supported by the evidence provided
- Use legal jargon excessively
- Exceed 800 words"""

USER_PROMPT_TEMPLATE = """Write an explanation letter to contest this chargeback dispute.

## Dispute Details
- Reason Code: {reason_code}
- Dispute Phase: {phase}
- Amount: ₹{amount_rupees}
- Currency: {currency}
- Dispute Created: {dispute_created_at}
- Response Deadline: {respond_by}

## Payment Information
- Payment ID: {payment_id}
- Payment Method: {payment_method}
- Payment Date: {payment_date}
- Customer Email: {customer_email}
- Customer Contact: {customer_contact}

## Order Information
- Order ID: {order_id}
- Order Items: {order_items}
- Order Date: {order_date}

## Shipping Information
{shipping_section}

## Refund History
{refund_section}

## Customer Communication History
{comms_section}

## Letter Focus
{letter_focus}

## Evidence Gaps
{evidence_gaps}

Write the explanation letter now. Address the specific reason for the dispute
and reference the concrete evidence provided above."""
```

---

## Document Builder

### PDF Evidence Documents to Generate

For each dispute, generate these PDFs as needed:

1. **billing_proof.pdf** — Transaction receipt
   - Payment ID, amount, date, method
   - Customer email
   - Order ID and line items
   - "Generated from Razorpay payment records"

2. **shipping_proof.pdf** — Delivery confirmation
   - Tracking ID, carrier name
   - Shipped date, delivered date
   - Delivery address
   - Signed by (if available)
   - "Generated from shipping partner records"

3. **explanation_letter.pdf** — The LLM-generated letter
   - Formal letter format
   - On a simple letterhead (merchant name)
   - The full generated letter text
   - Date and signature

4. **customer_communication.pdf** — Email thread summary
   - Chronological list of emails
   - Date, sender, subject, snippet
   - "Generated from customer communication records"

5. **access_activity_log.pdf** — Transaction activity log (for fraud disputes)
   - IP address (from payment data if available)
   - Payment method details
   - 3DS/OTP verification status
   - "Generated from payment gateway activity logs"

Use `fpdf2` to generate clean, professional PDFs. No fancy formatting needed —
clean text with headers is sufficient for a hackathon demo.

---

## Frontend Dashboard

### Pages & Components

**Dashboard Page (single page app)**

Layout:
```
┌─────────────────────────────────────────────────────────┐
│  DisputeShield                              [Metrics]   │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌─ Metrics Summary Bar ──────────────────────────────┐ │
│  │  Total: 15  │ Submitted: 12 │ Errors: 1 │ Avg: 8s │ │
│  └────────────────────────────────────────────────────┘ │
│                                                         │
│  ┌─ Dispute List ─────────────────────────────────────┐ │
│  │  [Status Badge] disp_xxx  │ ₹1,200 │ fraud │ 8s   │ │
│  │  [Status Badge] disp_xxx  │ ₹3,400 │ chargeback   │ │
│  │  [Status Badge] disp_xxx  │ ₹890   │ product_not..│ │
│  │  ...                                               │ │
│  └────────────────────────────────────────────────────┘ │
│                                                         │
│  ┌─ Dispute Detail (when selected) ──────────────────┐ │
│  │                                                     │ │
│  │  Evidence Timeline:                                 │ │
│  │  ● Received → ● Gathering → ● Assembled →          │ │
│  │  ● Submitted → ○ Awaiting verdict                   │ │
│  │                                                     │ │
│  │  Evidence Collected:                                │ │
│  │  ✓ billing_proof    ✓ shipping_proof                │ │
│  │  ✓ explanation_letter  ⚠ customer_communication     │ │
│  │                                                     │ │
│  │  Explanation Letter:                                │ │
│  │  "Dear Dispute Resolution Team..."                  │ │
│  │                                                     │ │
│  └────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

### Status Colors
- `received` — gray
- `gathering` — blue (pulsing)
- `assembled` — amber
- `submitting` — blue (pulsing)
- `submitted` — green
- `won` — green (bold)
- `lost` — red
- `error` — red

### Polling
- Dashboard polls `GET /api/disputes` every 5 seconds
- When a dispute is selected, poll `GET /api/disputes/{id}` every 3 seconds
- Stop polling when dispute status is terminal (won, lost, error)

---

## Seed Data Script

### seed_disputes.py

This script is CRITICAL for the demo. It creates test data in Razorpay test mode.

```python
"""
Creates test payments and orders in Razorpay test mode,
then simulates dispute webhooks to trigger the pipeline.

Usage: python -m backend.seed.seed_disputes
"""

# Test scenarios to create (10-15 disputes with varied reason codes):
TEST_SCENARIOS = [
    {"amount": 120000, "reason": "product_not_received", "product": "Wireless Headphones"},
    {"amount": 340000, "reason": "fraud", "product": "Laptop Stand"},
    {"amount": 89000, "reason": "credit_not_processed", "product": "Phone Case"},
    {"amount": 250000, "reason": "chargeback", "product": "Running Shoes"},
    {"amount": 45000, "reason": "product_not_as_described", "product": "USB Cable"},
    {"amount": 780000, "reason": "subscription_canceled", "product": "Annual SaaS Plan"},
    {"amount": 150000, "reason": "general", "product": "Bluetooth Speaker"},
    {"amount": 210000, "reason": "product_not_received", "product": "Watch Strap"},
    {"amount": 67000, "reason": "fraud", "product": "Earbuds"},
    {"amount": 430000, "reason": "chargeback", "product": "Backpack"},
    {"amount": 95000, "reason": "credit_not_processed", "product": "Charger"},
    {"amount": 185000, "reason": "product_not_as_described", "product": "T-Shirt"},
]

# For each scenario:
# 1. Create order via Razorpay Orders API
# 2. Create payment via Razorpay Payments API (test mode)
# 3. Capture the payment
# 4. Simulate a dispute webhook by POSTing to our own /webhooks/razorpay endpoint
#    with a properly formatted webhook payload

# NOTE: Razorpay test mode may not support creating disputes via API.
# If that's the case, the seed script should directly POST simulated webhook
# payloads to our endpoint, bypassing Razorpay's webhook system.
# The webhook validator should have a "skip validation in dev mode" flag.
```

---

## Environment Variables

```env
# Razorpay (Test Mode)
RAZORPAY_KEY_ID=rzp_test_xxxxxxxxxxxxx
RAZORPAY_KEY_SECRET=xxxxxxxxxxxxxxxxxxxxx
RAZORPAY_WEBHOOK_SECRET=xxxxxxxxxxxxxxxxxxxxx

# LLM (Kimi via NVIDIA NIM)
LLM_API_BASE_URL=https://integrate.api.nvidia.com/v1
LLM_API_KEY=nvapi-xxxxxxxxxxxxxxxxxxxxx
LLM_MODEL_NAME=kimi

# App
APP_ENV=development  # development | production
APP_HOST=0.0.0.0
APP_PORT=8000
DATABASE_URL=sqlite+aiosqlite:///./disputeshield.db
FRONTEND_URL=http://localhost:5173

# Dev flags
SKIP_WEBHOOK_VALIDATION=true  # Skip signature check in dev
```
