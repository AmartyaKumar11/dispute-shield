# DisputeShield — Task List

Work through these tasks IN ORDER. Each task should result in working,
runnable code. Do not skip ahead. Read ARCHITECTURE.md for full specifications
before starting any task.

---

## Phase 1: Foundation (Day 1)

### Task 1.1 — Project Setup
- [ ] Initialize the project with the exact file structure from .cursorrules
- [ ] Create `requirements.txt`:
  ```
  fastapi==0.115.*
  uvicorn[standard]==0.34.*
  razorpay==1.4.*
  httpx==0.28.*
  fpdf2==2.8.*
  sqlalchemy[asyncio]==2.0.*
  aiosqlite==0.20.*
  pydantic==2.11.*
  pydantic-settings==2.8.*
  python-dotenv==1.1.*
  structlog==25.*
  python-multipart==0.0.*
  ```
- [ ] Create `frontend/package.json` with React 18, Vite, TailwindCSS, axios, lucide-react
- [ ] Create `.env.example` with all env vars from ARCHITECTURE.md
- [ ] Create `backend/config.py` using pydantic-settings to load env vars
- [ ] Verify: `pip install -r requirements.txt` works without errors

### Task 1.2 — Database Setup
- [ ] Create `backend/database.py` — async SQLAlchemy engine + session factory for SQLite
- [ ] Create `backend/models.py` — Dispute SQLAlchemy model exactly as specified in ARCHITECTURE.md
- [ ] Create all Pydantic schemas: DisputeResponse, DisputeListResponse, MetricsSummary, WebhookPayload
- [ ] Add DB initialization function that creates tables on app startup
- [ ] Verify: import models, create engine, create tables — no errors

### Task 1.3 — FastAPI App Shell
- [ ] Create `backend/main.py`:
  - FastAPI app with CORS middleware (allow frontend origin)
  - On startup: initialize database
  - Include routers: webhooks, disputes, metrics
  - Health check endpoint: `GET /health`
- [ ] Create `backend/routers/webhooks.py`:
  - `POST /webhooks/razorpay` — accepts JSON body, validates structure,
    saves dispute to DB with status "received", returns 200
  - For now, skip signature validation and background task — just save to DB
- [ ] Create `backend/routers/disputes.py`:
  - `GET /api/disputes` — query all disputes from DB, ordered by created_at desc
  - `GET /api/disputes/{dispute_id}` — query single dispute
  - Both return proper Pydantic response schemas
- [ ] Create `backend/routers/metrics.py`:
  - `GET /api/metrics/summary` — aggregate query across disputes table
  - Return MetricsSummary schema
- [ ] Verify: `uvicorn backend.main:app --reload` starts, hit all endpoints with curl

### Task 1.4 — Razorpay Provider (Real API)
- [ ] Create `backend/providers/base.py` with abstract base classes from ARCHITECTURE.md
- [ ] Create `backend/providers/razorpay_provider.py`:
  - Initialize Razorpay client with test mode keys from config
  - `get_payment(payment_id)` → calls `client.payment.fetch(payment_id)`
  - `get_order(order_id)` → calls `client.order.fetch(order_id)`
  - `get_refunds(payment_id)` → calls `client.payment.refunds(payment_id)`
  - `upload_document(file_path, purpose)` → calls Document API
    - Read file, POST to /v1/documents with purpose="dispute_evidence"
    - Return the document_id from response
  - `contest_dispute(dispute_id, evidence)` → calls Dispute Contest API
    - PATCH /v1/disputes/{dispute_id} with evidence dict + action="submit"
  - All methods: proper error handling, logging, return raw dict responses
- [ ] Verify: with test mode keys, call `get_payment()` on a manually created test payment

### Task 1.5 — Seed Script (Test Data)
- [ ] Create `backend/seed/seed_disputes.py`:
  - Create test payments in Razorpay test mode using Orders API + capture
  - For each of the 12 test scenarios in ARCHITECTURE.md:
    1. Create order: `client.order.create({"amount": X, "currency": "INR", "receipt": "test_N"})`
    2. NOTE: In test mode, you cannot programmatically create payments against orders
       without going through checkout. Instead:
       - Create the order in Razorpay
       - Simulate the webhook payload locally by constructing the dispute webhook JSON
       - POST it to `http://localhost:8000/webhooks/razorpay`
  - The simulated webhook payload structure:
    ```json
    {
      "entity": "event",
      "account_id": "acc_test",
      "event": "payment.dispute.created",
      "contains": ["payment", "dispute"],
      "payload": {
        "payment": {
          "entity": {
            "id": "pay_simulated_N",
            "amount": 120000,
            "currency": "INR",
            "method": "card",
            "email": "customer@example.com",
            "contact": "+919876543210",
            "order_id": "order_xxx",
            "created_at": 1693000000
          }
        },
        "dispute": {
          "entity": {
            "id": "disp_simulated_N",
            "payment_id": "pay_simulated_N",
            "amount": 120000,
            "currency": "INR",
            "amount_deducted": 0,
            "reason_code": "product_not_received",
            "respond_by": 1698000000,
            "status": "open",
            "phase": "chargeback",
            "created_at": 1693000000
          }
        }
      },
      "created_at": 1693000000
    }
    ```
  - Add `respond_by` timestamps that are 7-14 days from now (realistic)
  - Use varied customer emails and product names from the scenario list
- [ ] Update `backend/routers/webhooks.py` to properly parse this payload structure
  and extract dispute + payment fields
- [ ] Add `POST /api/seed/create-test-disputes` endpoint that runs the seed script
- [ ] Verify: run seed script, check DB has 12 disputes with status "received",
  check `GET /api/disputes` returns them all

---

## Phase 2: Evidence Pipeline (Day 2)

### Task 2.1 — Mock Providers
- [ ] Create `backend/providers/shipping_provider.py`:
  - `MockShippingProvider` implementing `ShippingProvider` interface
  - `get_delivery_status(order_id)` → returns `ShippingInfo` dataclass
  - Use hash of order_id as deterministic seed for mock data
  - 80% delivered, 15% in_transit, 5% returned (use hash % 100)
  - Realistic Indian carriers, addresses, tracking IDs
  - Delivery date = order date + random 2-7 days
  - Include realistic signed_by names for delivered orders
- [ ] Create `backend/providers/comms_provider.py`:
  - `MockCommunicationProvider` implementing `CommunicationProvider` interface
  - `get_customer_emails(email, order_id)` → returns list of `EmailRecord`
  - Generate 2-4 emails per order in chronological order
  - Standard pattern: order confirmation → delivery update → (for disputes: complaint + response)
- [ ] Verify: call both providers with test data, inspect output looks realistic

### Task 2.2 — Evidence Strategy Engine
- [ ] Create `backend/services/evidence_strategy.py`:
  - Define `EvidenceStrategy` dataclass exactly as in ARCHITECTURE.md
  - Define `EVIDENCE_STRATEGIES` dict with all 7 reason code mappings
  - Function: `get_strategy(reason_code: str) -> EvidenceStrategy`
    - Returns the matching strategy, falls back to "general" for unknown codes
  - Function: `evaluate_evidence_coverage(strategy, gathered_evidence) -> float`
    - Returns 0.0-1.0 indicating what % of required+recommended evidence was gathered
    - Required evidence missing = lower score than recommended missing
- [ ] Verify: test each reason code returns correct strategy, test coverage calculation

### Task 2.3 — LLM Provider (Kimi via NVIDIA NIM)
- [ ] Create `backend/providers/llm_provider.py`:
  - `KimiLLMProvider` implementing `LLMProvider` interface
  - Uses `httpx.AsyncClient` to call NVIDIA NIM inference endpoint
  - Endpoint: `{LLM_API_BASE_URL}/chat/completions`
  - Headers: `Authorization: Bearer {LLM_API_KEY}`
  - Body format: standard OpenAI-compatible chat completions
    ```json
    {
      "model": "{LLM_MODEL_NAME}",
      "messages": [
        {"role": "system", "content": "..."},
        {"role": "user", "content": "..."}
      ],
      "temperature": 0.3,
      "max_tokens": 2000
    }
    ```
  - System prompt and user prompt template from ARCHITECTURE.md
  - Build the user prompt by filling in the template with actual data
  - Handle shipping_info being None (evidence gap) — adjust prompt accordingly
  - Parse response: extract `choices[0].message.content`
  - Error handling: if LLM fails, generate a basic template letter as fallback
    (the system must NEVER fail completely because the LLM is down)
- [ ] Verify: call with test data, inspect the generated letter quality

### Task 2.4 — Document Builder
- [ ] Create `backend/services/document_builder.py`:
  - Uses `fpdf2` to generate clean PDF documents
  - Function: `build_billing_proof(payment_data, order_data) -> str`
    - Returns file path to generated PDF
    - Content: transaction receipt with payment ID, amount, date, method, customer info
  - Function: `build_shipping_proof(shipping_info) -> str | None`
    - Returns None if shipping_info indicates no delivery (returned/no data)
    - Content: delivery confirmation with tracking, dates, address, signature
  - Function: `build_explanation_letter(letter_text) -> str`
    - Returns file path to generated PDF
    - Content: formal letter with simple header, date, body text, signature
  - Function: `build_customer_communication(comms_data) -> str | None`
    - Returns None if no communication data
    - Content: chronological email thread summary
  - Function: `build_access_activity_log(payment_data) -> str`
    - Content: IP address, payment method, verification status from payment data
  - All PDFs saved to a temp directory: `/tmp/disputeshield/{dispute_id}/`
  - Use clean formatting: header with title, horizontal rule, body text
  - Font: Helvetica (built into fpdf2, no external fonts needed)
- [ ] Verify: generate each PDF type, open and inspect they look professional

### Task 2.5 — Main Pipeline Orchestration
- [ ] Create `backend/services/dispute_service.py`:
  - `process_dispute(dispute_id: str)` — the full pipeline from ARCHITECTURE.md
  - Step by step:
    1. Load dispute from DB, update status to "gathering"
    2. Get strategy from evidence_strategy.py
    3. Pull payment data from Razorpay provider
    4. Pull order data from Razorpay provider (if order_id exists)
    5. Check for refunds from Razorpay provider
    6. Pull shipping data from mock shipping provider
    7. Pull communication data from mock comms provider
    8. Save all gathered data as JSON in dispute record
    9. Update status to "assembled"
    10. Generate explanation letter via LLM provider
    11. Generate PDF documents via document builder
    12. Upload documents to Razorpay via provider
        - For each generated PDF, upload and collect document_id
        - NOTE: If Razorpay test mode doesn't support document upload,
          simulate this step — generate the PDFs but skip the actual upload,
          store fake doc IDs
    13. Build evidence dict mapping fields to document_id arrays
    14. Build summary text (max 1000 chars) from strategy + key facts
    15. Contest dispute via Razorpay provider
        - NOTE: If Razorpay test mode doesn't support dispute contest on
          simulated disputes, simulate this step — log the contest payload
          but don't actually call the API
    16. Update status to "submitted", save contest response
    17. Record processing_completed_at timestamp
  - Error handling:
    - Each step wrapped in try/except
    - If shipping data fails → continue without it, note in evidence_gaps
    - If LLM fails → use fallback template letter
    - If document upload fails → log error, continue with available docs
    - If contest submission fails → update status to "error" with message
    - ONLY hard failure: cannot load dispute from DB (should never happen)
  - Calculate and save processing time
- [ ] Update `backend/routers/webhooks.py`:
  - After saving dispute to DB, trigger `process_dispute(dispute_id)` as BackgroundTask
- [ ] Add retry endpoint: `POST /api/disputes/{dispute_id}/retry`
- [ ] Verify: run seed script, watch logs as pipeline processes each dispute,
  check DB shows disputes progressing through statuses

---

## Phase 3: Frontend (Day 3)

### Task 3.1 — Frontend Setup
- [ ] Initialize Vite + React project in `frontend/`
- [ ] Install and configure TailwindCSS
- [ ] Install axios, lucide-react
- [ ] Create `frontend/src/lib/api.js`:
  - Axios instance with base URL `http://localhost:8000`
  - Functions: `getDisputes()`, `getDispute(id)`, `getMetrics()`, `seedDisputes()`, `retryDispute(id)`
- [ ] Create `vite.config.js` with proxy to backend (optional, or just use CORS)
- [ ] Verify: `npm run dev` starts, blank page loads

### Task 3.2 — Dashboard Layout
- [ ] Create `frontend/src/App.jsx`:
  - Single page layout with header bar and main content area
  - Header: "DisputeShield" logo text + "Seed Test Data" button (calls seed endpoint)
  - Two-column layout: dispute list (left, 40%) + detail panel (right, 60%)
  - Use Tailwind: `bg-slate-50`, `text-slate-900`, blue accent `bg-blue-600`
- [ ] Create `frontend/src/components/StatusBadge.jsx`:
  - Takes `status` prop, renders colored pill badge
  - Colors from ARCHITECTURE.md status color mapping
  - Pulsing animation for "gathering" and "submitting" states

### Task 3.3 — Dispute List Component
- [ ] Create `frontend/src/components/DisputeList.jsx`:
  - Fetches disputes from API on mount, polls every 5 seconds
  - Renders each dispute as a clickable row:
    - Status badge | Dispute ID (truncated) | Amount (₹) | Reason code | Processing time
  - Selected dispute highlighted with blue-left border
  - onClick sets selected dispute ID (passed via prop/state)
  - Empty state: "No disputes yet. Click 'Seed Test Data' to generate test disputes."
  - Loading state: skeleton rows

### Task 3.4 — Metrics Summary Component
- [ ] Create `frontend/src/components/MetricsSummary.jsx`:
  - Fetches from `/api/metrics/summary`
  - Renders as a horizontal bar of stat cards:
    - Total Disputes (number)
    - Submitted (number, green)
    - Errors (number, red — 0 is green)
    - Avg Processing Time (Xs)
    - Evidence Coverage (X%)
  - Compact design, sits above the dispute list

### Task 3.5 — Dispute Detail Panel
- [ ] Create `frontend/src/components/DisputeDetail.jsx`:
  - Fetches single dispute detail, polls every 3 seconds while non-terminal
  - Sections:
    1. **Header**: Dispute ID, amount, reason code display name, deadline
    2. **Evidence Timeline** (see next task)
    3. **Evidence Collected**: checklist of evidence fields
       - ✓ green check for gathered fields
       - ⚠ amber warning for missing/gap fields
       - ○ gray circle for not-applicable fields
    4. **Explanation Letter**: rendered text of the generated letter
       - Scrollable container, max-height 300px
       - If letter not yet generated, show "Generating..." with spinner
    5. **Strategy Used**: display the reason code strategy description
    6. **Error Info**: if status is "error", show error_message in red box
  - "Retry" button visible when status is "error"

### Task 3.6 — Evidence Timeline Component
- [ ] Create `frontend/src/components/EvidenceTimeline.jsx`:
  - Visual stepper showing pipeline progress:
    `Received → Gathering → Assembled → Submitted → Verdict`
  - Each step: circle + label
  - Completed steps: filled blue circle + check icon
  - Current step: pulsing blue circle
  - Future steps: gray outlined circle
  - Error state: red circle with X icon at the failed step
  - Use flexbox with connecting lines between circles
  - Timestamps shown below each completed step

### Task 3.7 — Integration & Polish
- [ ] Wire everything together in Dashboard.jsx
  - MetricsSummary at top
  - DisputeList on left, DisputeDetail on right
  - Selected dispute state managed in Dashboard
  - Seed button in header triggers seed + auto-refreshes list
- [ ] Add loading/error states for all API calls
- [ ] Ensure polling stops for terminal states
- [ ] Test the full flow: seed data → watch disputes process → inspect detail
- [ ] Verify: the entire demo loop works smoothly end-to-end

---

## Phase 4: Polish & Demo (Day 4)

### Task 4.1 — Batch Demo Run
- [ ] Clear the database (delete SQLite file)
- [ ] Run the full seed script with 12 disputes
- [ ] Watch the pipeline process all 12 in the dashboard
- [ ] Verify each reason code generates appropriate evidence strategy
- [ ] Verify at least one dispute shows graceful failure handling
  (shipping_proof gap for an RTO scenario)
- [ ] Screenshot the dashboard at each interesting state for README

### Task 4.2 — Metrics Accuracy
- [ ] Verify MetricsSummary shows correct aggregations
- [ ] Add per-reason-code breakdown to metrics if not already present
- [ ] Ensure processing time is accurately calculated
- [ ] Ensure evidence coverage rate correctly reflects gathered vs required evidence

### Task 4.3 — Error Handling Hardening
- [ ] Test: what happens if LLM API is unreachable? (fallback letter should generate)
- [ ] Test: what happens if Razorpay API returns 401? (should log and error gracefully)
- [ ] Test: what happens if webhook payload is malformed? (should return 400, not 500)
- [ ] Test: what happens if the same webhook fires twice? (should be idempotent — check if dispute ID exists)
- [ ] Add idempotency check to webhook handler (skip if dispute already in DB)

### Task 4.4 — UI Polish
- [ ] Add subtle animations: fade-in for new disputes appearing in list
- [ ] Evidence Timeline step transitions should animate smoothly
- [ ] Ensure reason code shows display_name not raw code
- [ ] Format amounts properly: ₹1,200.00 (not 120000 paise)
- [ ] Format dates properly: "28 Aug 2026, 2:30 PM" (not unix timestamps)
- [ ] Ensure dashboard looks good at 1920x1080 (primary demo resolution)
- [ ] Add a "Processing..." indicator when disputes are being assembled

---

## Phase 5: Ship (Day 5)

### Task 5.1 — README
- [ ] Write README.md with:
  - Project name and one-line description
  - Problem statement (3 sentences)
  - Solution overview (3 sentences)
  - Architecture diagram (text-based or link to image)
  - Tech stack list
  - Setup instructions (step by step — clone, install, env vars, run)
  - Demo instructions (seed data, watch pipeline, explore dashboard)
  - Screenshots (embed from screenshots taken in Task 4.1)
  - What's REAL vs MOCKED (be transparent — judges will respect this)
  - Extension points (where to plug in real Shiprocket, real CRM)
  - Key design decisions and tradeoffs
  - Built for: Razorpay AI Buildathon 2026 — Track 02: AI Risk Manager

### Task 5.2 — Repo Cleanup
- [ ] Remove any debug print statements
- [ ] Ensure .env is in .gitignore (but .env.example is committed)
- [ ] Ensure no API keys are committed anywhere
- [ ] Remove any unused files or dependencies
- [ ] Ensure `pip install -r requirements.txt && uvicorn backend.main:app` works fresh
- [ ] Ensure `cd frontend && npm install && npm run dev` works fresh

### Task 5.3 — Video Script (NOT for Cursor — do this yourself)
Record a 5-minute pitch video with this structure:
- 0:00-0:30 — Problem: "Chargebacks cost merchants 2-3% of revenue. The net win
  rate is 8.1%. Most SME merchants don't respond because evidence assembly is too
  manual. Every uncontested chargeback raises Razorpay's dispute ratio with card
  networks."
- 0:30-3:00 — Live Demo: Show the dashboard. Click "Seed Test Data". Watch
  disputes arrive. Select one, show evidence timeline progressing. Show the
  generated explanation letter. Show a fraud dispute vs a product_not_received
  dispute getting different evidence strategies. Show the graceful failure case.
  Show metrics.
- 3:00-4:00 — Architecture: Show the pipeline diagram. Explain real vs mock.
  Show the provider interface pattern. Show how plugging in Shiprocket is a
  one-file change.
- 4:00-4:30 — Why Razorpay cares: "This is the SME version of your enterprise
  Dispute Responder Agent. It directly improves your aggregate dispute ratio.
  Every auto-contested dispute is margin you're protecting."
- 4:30-5:00 — Extension vision: "In production: real shipping APIs, real CRM
  integration, ML model trained on historical win/loss data to predict contest
  success probability before submitting."

---

## Notes for Cursor Agent

- After completing each task, run the verify step before moving to the next task.
- If a verify step fails, fix the issue before proceeding.
- When creating Razorpay API calls, ALWAYS use the test mode client.
  The keys start with `rzp_test_`.
- If the Razorpay SDK doesn't support a method directly, use httpx to call
  the REST API with basic auth (key_id:key_secret).
- When generating mock data, make it REALISTIC. Indian names, Indian addresses,
  Indian carrier names. This is for a hackathon by an Indian company.
- The LLM endpoint uses OpenAI-compatible chat completions format.
  If the NVIDIA NIM endpoint differs, check the docs and adapt.
- All amounts in the database are in PAISE. Convert to rupees only at the
  API response layer (in Pydantic schemas or frontend).
- Keep the frontend SIMPLE. No fancy animations, no complex state management.
  Tailwind utility classes, functional components, useState/useEffect.
  The judges care about the pipeline working, not the UI being beautiful.
