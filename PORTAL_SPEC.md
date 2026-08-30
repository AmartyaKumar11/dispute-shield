# DisputeShield Resolution Portal — Feature Spec

## Read First

Read .cursorrules and ARCHITECTURE.md before starting. This feature adds
a CUSTOMER-FACING resolution portal alongside the existing MERCHANT-FACING
dashboard. Do NOT break any existing functionality. All existing endpoints,
models, and UI must continue working.

---

## What This Is

A standalone customer-facing web page where frustrated customers can:
1. Look up their order status (real-time from Shiprocket + Razorpay)
2. Request a refund with one click (auto-approved under a threshold)
3. Chat with an AI agent that resolves their issue using real order data
4. Get their problem solved in under 60 seconds — no reason to call their bank

The portal link is included in every order confirmation email. When a
customer uses it instead of filing a bank dispute, the dispute never
happens. The metric: DEFLECTION RATE — % of potential disputes resolved
through the portal.

Every portal interaction is stored in the evidence vault. If the customer
files a dispute anyway, the merchant has a complete record: "We offered
this customer a full refund through our resolution portal on Aug 25.
They did not respond. The dispute was filed on Aug 28."

---

## Architecture

```
Customer opens portal link (unique per order)
         │
         ▼
┌─────────────────────────────┐
│   Resolution Portal (React) │  ← Separate React app OR route
│                             │     in existing frontend
│  ┌─────────────────────┐   │
│  │ Order Lookup         │   │  ← Razorpay Order API + Shiprocket
│  │ (order ID or email)  │   │
│  └──────────┬──────────┘   │
│             │               │
│  ┌──────────▼──────────┐   │
│  │ Order Status View    │   │  ← Payment status, shipping, delivery
│  │ + Resolution Options │   │
│  └──────────┬──────────┘   │
│             │               │
│     ┌───────┼───────┐      │
│     │       │       │      │
│  Refund  Replace  Chat     │
│     │       │       │      │
│  ┌──▼───────▼───────▼──┐  │
│  │  AI Resolution Agent │  │  ← Kimi/NIM with order context
│  └──────────┬──────────┘  │
│             │              │
│  ┌──────────▼──────────┐  │
│  │  Resolution Record   │  │  ← Stored in DB + evidence vault
│  └─────────────────────┘  │
└─────────────────────────────┘
```

The portal is a SEPARATE route/page in the existing React frontend,
accessible WITHOUT authentication. Customers access it via a unique
link: `http://localhost:5173/resolve/{order_token}`

The `order_token` is a base64-encoded string containing the order_id
and a HMAC signature to prevent URL guessing. Only valid tokens load
the portal.

---

## Database Models

### PortalSession

Tracks every customer visit to the resolution portal.

```python
class PortalSession(Base):
    __tablename__ = "portal_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # UUID
    order_token: Mapped[str] = mapped_column(String, nullable=False)
    order_id: Mapped[str] = mapped_column(String, nullable=False)
    payment_id: Mapped[str | None] = mapped_column(String, nullable=True)
    customer_email: Mapped[str | None] = mapped_column(String, nullable=True)

    # Session state
    status: Mapped[str] = mapped_column(String, default="active")
    # Values: active, resolved_refund, resolved_replacement,
    #         resolved_chat, abandoned, expired

    # What the customer did
    viewed_order_status: Mapped[bool] = mapped_column(Boolean, default=False)
    requested_refund: Mapped[bool] = mapped_column(Boolean, default=False)
    requested_replacement: Mapped[bool] = mapped_column(Boolean, default=False)
    started_chat: Mapped[bool] = mapped_column(Boolean, default=False)

    # Resolution details
    resolution_type: Mapped[str | None] = mapped_column(String, nullable=True)
    # "auto_refund", "manual_refund", "replacement", "info_provided",
    # "issue_explained", "escalated_to_merchant"
    resolution_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    refund_amount_paise: Mapped[int | None] = mapped_column(Integer, nullable=True)
    refund_id: Mapped[str | None] = mapped_column(String, nullable=True)  # Razorpay refund ID

    # Chat history
    chat_history_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON array of {role: "customer"|"agent", message: str, timestamp: str}

    # Dispute prevention tracking
    dispute_filed_after: Mapped[bool] = mapped_column(Boolean, default=False)
    # Did the customer file a dispute AFTER using the portal?
    linked_dispute_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # Timestamps
    started_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
```

### PortalConfig

Merchant-configurable settings for the portal.

```python
class PortalConfig(Base):
    __tablename__ = "portal_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)

    # Auto-refund settings
    auto_refund_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_refund_max_amount_paise: Mapped[int] = mapped_column(
        Integer, default=200000  # ₹2,000
    )
    # Orders below this amount get instant refund, no merchant approval needed

    # Portal branding
    merchant_name: Mapped[str] = mapped_column(String, default="Merchant")
    support_email: Mapped[str | None] = mapped_column(String, nullable=True)

    # Token settings
    token_secret: Mapped[str] = mapped_column(String, default="disputeshield-portal-secret")
    # HMAC secret for generating portal tokens

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
```

---

## API Endpoints

### Portal Token Generation

```
POST /api/portal/generate-link
Body: {
    "order_id": "order_xxx",
    "payment_id": "pay_xxx",
    "customer_email": "customer@example.com"
}
Response: {
    "portal_url": "http://localhost:5173/resolve/eyJvcm...",
    "token": "eyJvcm..."
}
```

Generates a unique, signed portal link for an order. The token is:
`base64(json({"order_id": "...", "payment_id": "...", "email": "...", "exp": unix_timestamp}))`
signed with HMAC-SHA256 using `PortalConfig.token_secret`.

Token expires in 30 days.

### Portal Order Lookup

```
GET /api/portal/{order_token}/status
Response: {
    "valid": true,
    "order": {
        "order_id": "order_xxx",
        "amount_rupees": 1200.00,
        "product_name": "Wireless Headphones",
        "order_date": "2026-08-20T10:30:00Z",
        "payment_method": "card",
        "payment_status": "captured"
    },
    "shipping": {
        "status": "delivered",           // or "in_transit", "pending", "returned"
        "carrier": "Delhivery",
        "tracking_id": "DEL1234567890",
        "shipped_at": "2026-08-21T14:00:00Z",
        "delivered_at": "2026-08-24T11:30:00Z",
        "signed_by": "Rahul M.",
        "estimated_delivery": "2026-08-23T00:00:00Z"
    },
    "refund_eligible": true,             // based on auto_refund_max_amount
    "auto_refund_available": true,       // under threshold + no existing refund
    "existing_refunds": [],              // list of any refunds already issued
    "portal_session_id": "uuid-xxx"      // created on first access
}
```

This endpoint:
1. Validates the token (signature + expiry)
2. Fetches order data from Razorpay Order API
3. Fetches payment data from Razorpay Payment API
4. Fetches shipping status from Shiprocket (with mock fallback)
5. Checks for existing refunds via Razorpay Refund API
6. Creates a PortalSession record if this is the first visit
7. Returns everything the portal UI needs

If token is invalid or expired:
```
{"valid": false, "error": "This link has expired or is invalid."}
```

### Request Refund

```
POST /api/portal/{order_token}/refund
Body: {
    "reason": "Product not received",     // customer-selected reason
    "detail": "It's been 10 days..."      // optional free text
}
Response: {
    "success": true,
    "refund_type": "auto",                // "auto" (instant) or "manual" (pending approval)
    "refund_id": "rfnd_xxx",              // if auto-approved
    "refund_amount_rupees": 1200.00,
    "estimated_days": "5-7 business days",
    "message": "Your refund of ₹1,200.00 has been initiated. You'll receive it within 5-7 business days."
}
```

Logic:
1. Validate token
2. Check if order amount <= auto_refund_max_amount AND no existing refund
3. If YES (auto-refund):
   - Call Razorpay Refund API: `client.payment.refund(payment_id, {"amount": amount_paise})`
   - Save refund_id to PortalSession
   - Update session status to "resolved_refund"
   - Update evidence vault: "Customer requested refund via portal. Auto-approved and processed."
   - Return success with refund details
4. If NO (over threshold or auto-refund disabled):
   - Save the request to PortalSession with status "pending_merchant_review"
   - Send email notification to merchant via Gmail SMTP
   - Return success with refund_type "manual" and message about merchant review
   - Update evidence vault with the request

Refund reasons (dropdown options in the UI):
- "Product not received"
- "Product damaged or defective"
- "Wrong product received"
- "Changed my mind"
- "Charged incorrect amount"
- "Other"

### Request Replacement

```
POST /api/portal/{order_token}/replacement
Body: {
    "reason": "Product damaged or defective",
    "detail": "The screen has a crack..."
}
Response: {
    "success": true,
    "message": "Your replacement request has been submitted. The merchant will contact you within 24 hours.",
    "ticket_id": "RPL-xxx"
}
```

Logic:
1. Validate token
2. Save replacement request to PortalSession
3. Send email to merchant with full order details + customer's reason
4. Update session status to "resolved_replacement"
5. Update evidence vault
6. Return confirmation

Replacements are NEVER auto-approved — always go to merchant.

### AI Chat

```
POST /api/portal/{order_token}/chat
Body: {
    "message": "I haven't received my order yet"
}
Response: {
    "reply": "I can see your order was shipped on Aug 21 via Delhivery (tracking: DEL1234567890). According to the tracking, it was delivered on Aug 24 and signed by Rahul M. Could you check with Rahul or at the delivery address? If you still can't find it, I can initiate a refund for you right away.",
    "suggested_actions": ["Request refund", "I found it, thanks"],
    "session_id": "uuid-xxx"
}
```

Logic:
1. Validate token
2. Load PortalSession (create if first chat)
3. Load full order context: payment data, shipping status, refund history
4. Build chat history from session
5. Call Kimi/NIM with this system prompt:

```
SYSTEM PROMPT:

You are a customer support agent for an e-commerce merchant. You are
chatting with a customer who has an issue with their order. Your goal
is to RESOLVE the issue quickly and prevent the customer from filing
a bank dispute.

You have access to the customer's order data:

Order ID: {order_id}
Product: {product_name}
Amount: ₹{amount}
Payment method: {payment_method}
Order date: {order_date}
Payment status: {payment_status}

Shipping:
- Carrier: {carrier}
- Tracking ID: {tracking_id}
- Status: {shipping_status}
- Shipped: {shipped_at}
- Delivered: {delivered_at}
- Signed by: {signed_by}

Existing refunds: {refunds}

Rules:
1. Be empathetic but concise. Max 3 sentences per reply.
2. Use the actual order data in your responses — don't be vague.
3. If the customer wants a refund and the amount is under ₹{auto_refund_max}:
   suggest using the "Request refund" button for instant processing.
4. If the order shows as delivered, gently mention who signed for it
   and suggest checking with them before requesting a refund.
5. If shipping shows "in_transit", give the tracking ID and estimated
   delivery date. Ask the customer to wait.
6. If shipping shows "returned" or "failed", apologize and suggest
   an immediate refund.
7. NEVER blame the customer. NEVER be defensive.
8. NEVER say "I'm just an AI" or "I don't have access to..."
   You DO have access to everything listed above.
9. If you can't resolve the issue, say "Let me connect you with our
   support team" and suggest the customer reply to the email with
   their issue.
10. End every response with a suggested next action.

Previous conversation:
{chat_history}

Customer's message: {message}

Respond in JSON:
{
    "reply": "your response text",
    "suggested_actions": ["action1", "action2"],
    "resolution_detected": false,
    "resolution_type": null
}

If the issue is resolved (customer says thanks, found the product,
accepts the explanation), set resolution_detected: true and
resolution_type to one of: "info_provided", "issue_explained",
"refund_suggested", "replacement_suggested".
```

6. Parse the LLM response
7. Append both customer message and agent reply to chat_history_json
8. If resolution_detected: update session status
9. Update evidence vault with the full chat transcript
10. Return reply + suggested actions

If Kimi/NIM fails, return a fallback message:
"I'm having trouble processing your request right now. Please use the
refund or replacement buttons above, or reply to your order confirmation
email for direct support."

### Portal Metrics

```
GET /api/portal/metrics
Response: {
    "total_portal_visits": 15,
    "total_resolved": 9,
    "resolution_breakdown": {
        "auto_refund": 4,
        "manual_refund": 1,
        "replacement": 1,
        "info_provided": 2,
        "issue_explained": 1
    },
    "deflection_rate": 0.60,           // resolved / total visits
    "disputes_after_portal": 2,         // customers who filed dispute AFTER using portal
    "disputes_without_portal": 8,       // disputes from customers who never used portal
    "avg_resolution_time_seconds": 45,
    "total_refunds_issued_rupees": 5400,
    "estimated_chargebacks_prevented": 9,
    "estimated_savings_rupees": 12600    // (prevented × avg dispute amount) + processing cost saved
}
```

### Generate Portal Links for All Orders (Seed Helper)

```
POST /api/portal/generate-links-batch
```

For each existing transaction in TransactionRisk table, generate a portal
link. Used during seeding so the demo has ready-made links.

---

## Frontend: Resolution Portal

### Route Setup

Add a new route to the React app:
- `/resolve/:token` → PortalPage component

This route does NOT use the merchant dashboard layout. It has its own
clean, customer-facing design. No navigation tabs, no sidebar, no
merchant branding (except merchant name from PortalConfig).

### Design System (Customer-Facing)

The portal uses a LIGHT theme — customers expect light backgrounds.
This is different from the merchant dashboard's dark upsk.to design.

```
Background: #FFFFFF
Surface: #F8F9FA
Border: #E5E7EB
Text primary: #111827
Text secondary: #6B7280
Accent (CTA): #2563EB (blue — trust color for financial actions)
Success: #059669
Warning: #D97706
Error: #DC2626
Font: Inter (already loaded)
Border radius: 12px cards, 8px buttons
Max width: 480px (mobile-first, centered)
```

The portal should look like a modern customer support page — clean,
trustworthy, minimal. Think Stripe's payment page, not a dashboard.

### PortalPage Component

```
┌──────────────────────────────────┐
│                                  │
│     🛡️ DisputeShield            │
│     Order resolution center      │
│                                  │
│  ┌────────────────────────────┐  │
│  │                            │  │
│  │  Order #order_xxx          │  │
│  │  Wireless Headphones       │  │
│  │  ₹1,200.00 · Aug 20, 2026 │  │
│  │                            │  │
│  │  Shipping: ✅ Delivered     │  │
│  │  Carrier: Delhivery        │  │
│  │  Delivered: Aug 24, 2026   │  │
│  │  Signed by: Rahul M.      │  │
│  │                            │  │
│  └────────────────────────────┘  │
│                                  │
│  How can we help?                │
│                                  │
│  ┌────────────────────────────┐  │
│  │  💰 I want a refund        │  │
│  └────────────────────────────┘  │
│  ┌────────────────────────────┐  │
│  │  📦 I want a replacement   │  │
│  └────────────────────────────┘  │
│  ┌────────────────────────────┐  │
│  │  💬 Chat with support      │  │
│  └────────────────────────────┘  │
│                                  │
│  ─────────────────────────────── │
│  Powered by DisputeShield        │
│                                  │
└──────────────────────────────────┘
```

### Component Breakdown

#### PortalPage.jsx (main container)
- Fetches order status on mount: `GET /api/portal/{token}/status`
- If token invalid: shows error state with message
- If valid: shows OrderCard + ResolutionOptions
- Manages which view is active: "overview" | "refund" | "replacement" | "chat" | "resolved"

#### OrderStatusCard.jsx
- Displays order info: product, amount, date
- Displays shipping status with appropriate icon:
  - Delivered: green checkmark, "Delivered on {date}, signed by {name}"
  - In transit: blue truck icon, "In transit — estimated delivery {date}"
  - Pending: gray clock, "Processing — shipment not yet dispatched"
  - Returned/Failed: red alert, "Delivery failed — we're sorry about this"
- Displays payment method badge (Card / UPI)

#### RefundFlow.jsx
- Step 1: Select reason from dropdown (list from API section above)
- Step 2: Optional detail text input (max 500 chars)
- Step 3: "Request refund" button
- On submit: POST /api/portal/{token}/refund
- Auto-refund response: show green success card with refund amount + timeline
  "✅ Refund of ₹1,200.00 initiated. You'll receive it within 5-7 business days."
- Manual refund response: show blue info card
  "📋 Your refund request has been submitted. Our team will review it within 24 hours."
- After success: update PortalPage to "resolved" view

#### ReplacementFlow.jsx
- Step 1: Select reason from dropdown
- Step 2: Detail text input (required, min 20 chars)
- Step 3: "Request replacement" button
- On submit: POST /api/portal/{token}/replacement
- Success: show confirmation with ticket ID
- After success: update PortalPage to "resolved" view

#### ChatInterface.jsx
- Chat bubble UI (customer messages right-aligned, agent left-aligned)
- Text input at bottom with send button
- On send: POST /api/portal/{token}/chat
- Show typing indicator while waiting for response
- Display suggested actions as tappable buttons below agent's reply
- When a suggested action is tapped, send it as the next message
- Chat history persists (loaded from PortalSession on mount)
- If resolution_detected in response: show resolution confirmation card
  and offer "Is there anything else?" or "I'm all set" buttons

#### ResolvedView.jsx
- Shown after any resolution (refund, replacement, or chat resolution)
- Green card: "Your issue has been resolved"
- Details of what happened (refund amount, replacement ticket, etc.)
- "If you need further help, reply to your order confirmation email"
- Small text: "This interaction has been recorded for your protection"

### Portal States

```
Loading → fetch order status
  ├── Invalid token → show error "This link is invalid or expired"
  ├── Order found → show OrderStatusCard + ResolutionOptions
  │     ├── "Refund" clicked → RefundFlow
  │     │     └── Submitted → ResolvedView
  │     ├── "Replacement" clicked → ReplacementFlow
  │     │     └── Submitted → ResolvedView
  │     └── "Chat" clicked → ChatInterface
  │           └── Resolution detected → ResolvedView
  └── Already resolved → show ResolvedView (from previous session)
```

---

## Integration with Existing System

### Evidence Vault Integration

Every portal interaction creates an evidence record. When a dispute is
later filed for the same order, the dispute pipeline checks the vault
and finds: "Customer visited resolution portal on Aug 25. Viewed order
status (delivered, signed by Rahul M.). Started chat. Agent explained
delivery was confirmed. Customer did not request refund. Dispute filed
Aug 28."

This is DEVASTATING evidence in a chargeback contest. The merchant can
prove the customer knew the order was delivered and chose not to use
the resolution options available to them.

In dispute_service.py, when gathering evidence, add:

```python
# Check if customer used the portal before filing this dispute
portal_sessions = get_portal_sessions_for_order(order_id)
if portal_sessions:
    for session in portal_sessions:
        # Add portal interaction as evidence
        vault_entry = {
            "type": "portal_interaction",
            "session_id": session.id,
            "started_at": session.started_at.isoformat(),
            "actions_taken": {
                "viewed_status": session.viewed_order_status,
                "requested_refund": session.requested_refund,
                "started_chat": session.started_chat,
            },
            "resolution": session.resolution_type,
            "chat_transcript": session.chat_history_json,
        }
        # This goes into the explanation letter:
        # "The customer accessed our resolution portal on {date} and
        #  was shown delivery confirmation (signed by {name}).
        #  The customer did not request a refund through the portal.
        #  The dispute was filed {N} days later."
```

### Escalation Engine Integration

When the escalation engine generates an intervention email, include the
portal link in the email:

```
"Hi, we noticed your delivery may have been delayed. You can check
your order status and request a refund instantly at:
{portal_url}

If you have any questions, simply reply to this email."
```

Update the email_provider.py intervention email template to include
the portal URL. The portal URL is generated via POST /api/portal/generate-link.

### Resolution Pathway Integration

When the dispute pipeline attempts direct resolution (the "resolving"
step), check if a portal session exists for this order:

- If the customer already resolved via portal (refund/replacement):
  mark the dispute as "resolved" — the portal already handled it.
- If the customer visited the portal but didn't resolve:
  use the portal interaction as evidence in the contest.

### Merchant Dashboard Integration

Add portal metrics to the Intelligence tab:

New section: "Resolution portal" with eyebrow label "CUSTOMER SELF-SERVICE"

Show:
- Portal visits (number)
- Resolution rate (% of visits that resolved)
- Deflection rate (% of potential disputes prevented)
- Auto-refunds issued (count + ₹ amount)
- Top resolution reasons (bar chart)
- "Disputes after portal" vs "Disputes without portal" comparison

Add to the Disputes tab detail view:
- If the disputed order has portal sessions, show a "Portal activity"
  section with the chat transcript and actions taken

Add to the Merchant Health Score:
- New component: "Customer self-service" (weight 0.10)
  - Score based on portal deflection rate
  - 100 if > 60%, 80 if > 40%, 50 if > 20%, 0 if no portal

Add to the Shield tab:
- For each transaction, show a small "Portal link" button that copies
  the portal URL to clipboard. If the transaction has portal sessions,
  show a badge: "Portal visited" or "Resolved via portal"

---

## Email Integration

### Portal Link in Order Confirmation

Update the intervention email template to always include the portal link.

When the seed script creates transactions and sends intervention emails
(SEND_REAL_EMAILS=true), include the portal URL in every email.

The email template should include:

```html
<div style="margin-top: 20px; padding: 15px; background: #EFF6FF;
            border-radius: 8px; text-align: center;">
    <p style="margin: 0 0 10px; color: #1E40AF; font-weight: 500;">
        Need help with your order?
    </p>
    <a href="{portal_url}" style="display: inline-block; padding: 10px 24px;
       background: #2563EB; color: white; text-decoration: none;
       border-radius: 8px; font-weight: 500;">
        Resolve your issue instantly
    </a>
    <p style="margin: 10px 0 0; color: #6B7280; font-size: 12px;">
        Get a refund, replacement, or chat with support — no waiting
    </p>
</div>
```

### Resolution Confirmation Email

When a customer resolves through the portal (refund approved, replacement
submitted), send a confirmation email via Gmail SMTP:

Subject: "Your issue has been resolved — Order {order_id}"
Body: Confirmation of what was resolved, refund amount/timeline if
applicable, and a note that they can reply if they need further help.

---

## Seed Data

Update the seed script to:

1. Generate portal tokens for ALL transactions (not just disputed ones)
2. Simulate portal visits for some transactions:
   - 5-6 transactions: customer visited portal
     - 3-4 of these: resolved (refund or chat resolution) → NO dispute filed
     - 1-2 of these: visited but didn't resolve → dispute filed later
   - Rest: no portal visit
3. For portal-resolved transactions:
   - Create PortalSession with status "resolved_*"
   - Include realistic chat histories (2-4 messages each)
   - Include refund records where applicable
4. For portal-visited-then-disputed transactions:
   - Create PortalSession with status "active" or "abandoned"
   - Mark dispute_filed_after = True
   - Link to the dispute record
5. When SEND_REAL_EMAILS=true:
   - Include portal links in intervention emails
   - The links should actually work — clicking them in your inbox
     should open the portal with real order data

### Seeded Chat Histories (Realistic Examples)

Portal session for a "delivered but customer claims not received" order:
```json
[
    {"role": "customer", "message": "I never received my order", "timestamp": "2026-08-25T14:30:00Z"},
    {"role": "agent", "message": "I can see your order was delivered on Aug 24 via Delhivery and signed by Rahul M. at your delivery address. Could you check with Rahul or at the specified location? If you still can't locate it, I can process a refund for you right away.", "timestamp": "2026-08-25T14:30:05Z"},
    {"role": "customer", "message": "Oh let me check with my neighbor", "timestamp": "2026-08-25T14:31:00Z"},
    {"role": "agent", "message": "Of course! Take your time. If you find it, great — no further action needed. If not, just come back and click 'Request refund' and we'll process it instantly.", "timestamp": "2026-08-25T14:31:04Z"}
]
```

Portal session for an auto-refund:
```json
[
    {"role": "customer", "message": "Wrong product received", "timestamp": "2026-08-26T10:00:00Z"},
    {"role": "agent", "message": "I'm sorry about that. Your order for Wireless Headphones (₹1,200) shows as delivered. Since you received the wrong item, I'd recommend clicking 'Request refund' above — your refund will be processed automatically within seconds since the order is under our instant refund threshold.", "timestamp": "2026-08-26T10:00:06Z"}
]
```

---

## Task Phases

### Phase P1: Backend Foundation

#### Task P1.1 — Database Models
- [ ] Add PortalSession model to backend/models.py
- [ ] Add PortalConfig model to backend/models.py
- [ ] Add Pydantic schemas: PortalStatusResponse, RefundRequest,
      RefundResponse, ReplacementRequest, ReplacementResponse,
      ChatRequest, ChatResponse, PortalMetricsResponse
- [ ] Run DB migration (delete SQLite, restart to recreate tables)
- [ ] **VERIFY**: Import models, create tables, no errors.
      Run `python -c "from backend.models import PortalSession, PortalConfig; print('OK')"`

#### Task P1.2 — Token Generation
- [ ] Create backend/services/portal_token.py:
  - `generate_token(order_id, payment_id, email) -> str`
  - `validate_token(token) -> dict | None`
  - Uses HMAC-SHA256 with PortalConfig.token_secret
  - Token is base64(json({"order_id", "payment_id", "email", "exp"})) + "." + signature
  - validate_token checks signature AND expiry (30 days)
- [ ] **VERIFY**: Generate a token, validate it — returns data.
      Generate a token, tamper with it — returns None.
      Generate a token, advance time past expiry — returns None.

#### Task P1.3 — Portal API Endpoints
- [ ] Create backend/routers/portal.py with ALL endpoints from the spec:
  - POST /api/portal/generate-link
  - GET /api/portal/{token}/status
  - POST /api/portal/{token}/refund
  - POST /api/portal/{token}/replacement
  - POST /api/portal/{token}/chat
  - GET /api/portal/metrics
  - POST /api/portal/generate-links-batch
- [ ] Include router in main.py
- [ ] **VERIFY**: Start server. Hit each endpoint:
  - POST /api/portal/generate-link with a test order_id → returns URL
  - GET /api/portal/{token}/status → returns order data (or mock data)
  - POST /api/portal/{token}/chat with "hello" → returns AI reply
  - GET /api/portal/metrics → returns zeroes (no data yet)

#### Task P1.4 — Refund Integration
- [ ] In the refund endpoint, implement REAL Razorpay refund logic:
  - For simulated orders (disp_simulated_*): simulate refund response
  - For real Razorpay orders: call client.payment.refund()
  - Check auto_refund_max_amount from PortalConfig
  - Store refund_id in PortalSession
- [ ] Implement replacement request (email to merchant via Gmail SMTP)
- [ ] **VERIFY**: POST /api/portal/{token}/refund with a simulated order
      → returns success with simulated refund_id.
      POST /api/portal/{token}/replacement → sends email to SMTP_USER.

#### Task P1.5 — Chat Integration
- [ ] Implement the chat endpoint with Kimi/NIM:
  - Build the system prompt from spec (include real order data)
  - Maintain chat history in PortalSession.chat_history_json
  - Parse JSON response from LLM
  - Handle LLM failure with fallback message
  - Detect resolution from LLM response
- [ ] **VERIFY**: POST /api/portal/{token}/chat with "I didn't receive my order"
      → returns contextual reply mentioning actual order details.
      Send 3 messages in sequence → chat history accumulates.

#### Task P1.6 — Evidence Vault Integration
- [ ] In the portal endpoints, after every resolution action:
  - Create/update an evidence vault entry for the order
  - Store: portal visit timestamp, actions taken, chat transcript,
    resolution type, refund details
- [ ] In dispute_service.py, when gathering evidence for a dispute:
  - Check for PortalSession records for the same order
  - If found, add portal interaction data to evidence
  - Include portal evidence in the explanation letter prompt
- [ ] **VERIFY**: Create a portal session, then trigger a dispute for the
      same order. Check that the dispute's evidence includes portal data.

### Phase P2: Frontend Portal

#### Task P2.1 — Portal Route Setup
- [ ] Add route to React app: `/resolve/:token` → PortalPage
- [ ] This route uses its own layout — NO merchant dashboard chrome
- [ ] Create PortalPage.jsx as the main container
- [ ] On mount: fetch GET /api/portal/{token}/status
- [ ] Handle states: loading, invalid token, valid order
- [ ] **VERIFY**: Navigate to http://localhost:5173/resolve/invalid_token
      → shows error message. Navigate with valid token → shows loading then data.

#### Task P2.2 — Order Status Card
- [ ] Create OrderStatusCard.jsx with LIGHT theme design
- [ ] Show: product name, amount (₹ formatted), order date
- [ ] Show shipping status with color-coded badge:
  - Delivered: green badge, delivery date, signed by name
  - In transit: blue badge, estimated delivery, tracking ID
  - Pending: gray badge, "Processing"
  - Returned: red badge, "Delivery failed"
- [ ] Payment method badge (Card / UPI)
- [ ] **VERIFY**: Portal page shows order card with correct data from API.

#### Task P2.3 — Resolution Options
- [ ] Create three action buttons below the order card:
  - "I want a refund" → opens RefundFlow
  - "I want a replacement" → opens ReplacementFlow
  - "Chat with support" → opens ChatInterface
- [ ] Style as large, full-width cards with icon + label
- [ ] Smooth transition when selecting an option
- [ ] Back button to return to options
- [ ] **VERIFY**: Click each button → correct flow opens.

#### Task P2.4 — Refund Flow
- [ ] Create RefundFlow.jsx
- [ ] Step 1: reason dropdown (6 options from spec)
- [ ] Step 2: optional detail textarea
- [ ] Step 3: "Request refund" button (blue, prominent)
- [ ] On submit: POST /api/portal/{token}/refund
- [ ] Loading state while processing
- [ ] Success: green card with refund amount + timeline
- [ ] For manual refunds: blue info card with "pending review" message
- [ ] **VERIFY**: Submit refund request → success card appears.
      Check DB: PortalSession updated with refund details.

#### Task P2.5 — Replacement Flow
- [ ] Create ReplacementFlow.jsx
- [ ] Reason dropdown + required detail textarea (min 20 chars)
- [ ] Submit → POST /api/portal/{token}/replacement
- [ ] Success card with ticket ID
- [ ] **VERIFY**: Submit replacement → success card. Check inbox for
      merchant notification email.

#### Task P2.6 — Chat Interface
- [ ] Create ChatInterface.jsx
- [ ] Chat bubble UI:
  - Customer messages: right-aligned, blue background
  - Agent messages: left-aligned, gray background
  - Timestamps below each message (small, muted)
- [ ] Text input at bottom with send button
- [ ] Typing indicator (three dots animation) while waiting for response
- [ ] Suggested action buttons below agent's reply (tappable)
- [ ] When suggested action tapped, send as next message
- [ ] Chat history loaded from session on mount
- [ ] Resolution detected → show ResolvedView
- [ ] **VERIFY**: Open chat, send "I didn't receive my order" → AI replies
      with actual order details. Send follow-up → conversation continues.
      Suggested actions appear and are tappable.

#### Task P2.7 — Resolved View
- [ ] Create ResolvedView.jsx
- [ ] Green card: "Your issue has been resolved ✓"
- [ ] Shows resolution details (refund amount, ticket ID, or chat summary)
- [ ] "If you need further help, reply to your order confirmation email"
- [ ] Small footer: "This interaction has been recorded for your protection"
- [ ] **VERIFY**: After completing any resolution flow, ResolvedView appears.
      Refreshing the portal page with the same token shows ResolvedView
      (session is already resolved).

### Phase P3: Dashboard Integration

#### Task P3.1 — Portal Metrics on Intelligence Tab
- [ ] Add "Resolution portal" section to Intelligence tab
- [ ] Eyebrow label: "CUSTOMER SELF-SERVICE"
- [ ] Stat cards: visits, resolved, deflection rate, auto-refunds
- [ ] Comparison card: "Disputes after portal" vs "Disputes without portal"
- [ ] Fetch from GET /api/portal/metrics
- [ ] **VERIFY**: Intelligence tab shows portal metrics section with data.

#### Task P3.2 — Portal Activity in Dispute Detail
- [ ] In DisputeDetail.jsx, if the disputed order has portal sessions:
  - Show "Portal activity" section
  - Show chat transcript (if any)
  - Show actions taken (viewed status, requested refund, etc.)
  - Badge: "Customer used portal before filing dispute"
- [ ] **VERIFY**: Click on a dispute that has a portal session →
      portal activity section appears with chat history.

#### Task P3.3 — Portal Link in Shield Tab
- [ ] For each transaction in the Shield tab transaction list:
  - Add a small "📋 Portal link" button that copies the URL to clipboard
  - If the transaction has portal sessions: show "Portal visited" badge
  - If resolved via portal: show "Resolved via portal ✓" in green
- [ ] **VERIFY**: Click "Portal link" button → URL copied. Badge appears
      for transactions with portal activity.

#### Task P3.4 — Health Score Update
- [ ] Add "Customer self-service" component to health score (weight 0.10)
- [ ] Score based on portal deflection rate:
  - 100 if > 60%, 80 if > 40%, 50 if > 20%, 0 if no portal
- [ ] Adjust other component weights to sum to 1.0
  (reduce dispute_rate weight from 0.30 to 0.25 and evidence_readiness
  from 0.20 to 0.15 to make room)
- [ ] **VERIFY**: GET /api/health/score includes the new component.
      Intelligence tab shows updated health score.

### Phase P4: Seed Data + Email Integration

#### Task P4.1 — Portal Links in Emails
- [ ] Update intervention email template to include portal link
- [ ] Generate portal token for the transaction's order
- [ ] Include the "Resolve your issue instantly" button block from spec
- [ ] Update resolution offer emails to include portal link
- [ ] **VERIFY**: Set SEND_REAL_EMAILS=true. Seed data. Check inbox.
      Intervention emails contain the portal link button. Click it →
      opens the portal with correct order data.

#### Task P4.2 — Seed Portal Sessions
- [ ] Update seed script to create portal sessions for some transactions:
  - 5-6 transactions get portal visits
  - 3-4 resolve via portal (auto_refund or chat)
  - 1-2 visit but don't resolve, then dispute
- [ ] Include realistic chat histories from the spec examples
- [ ] For resolved sessions: mark status, resolution type, timestamps
- [ ] For visited-then-disputed: set dispute_filed_after=True,
      link to the dispute record
- [ ] **VERIFY**: After seeding:
  - GET /api/portal/metrics shows: ~5 visits, ~3 resolved, ~60% deflection
  - Shield tab shows "Portal visited" and "Resolved via portal" badges
  - Intelligence tab shows portal metrics
  - At least one dispute detail shows "Portal activity" section

#### Task P4.3 — Full Integration Test
- [ ] Delete DB completely
- [ ] Restart backend
- [ ] Run seed script with SEND_REAL_EMAILS=true
- [ ] Verify ALL of the following:
  1. Shield tab: transactions with portal badges
  2. Disputes tab: mix of auto_submit/review/accept with portal activity
  3. Intelligence tab: portal metrics + health score + model evaluation
  4. Check Gmail inbox: intervention emails with portal links
  5. Click a portal link in email → portal loads with order data
  6. In the portal: view order status, start chat, request refund
  7. After portal resolution: check that evidence vault has portal data
  8. Check a dispute detail for a portal-visited order → shows transcript
  9. GET /api/portal/metrics → deflection rate > 0
  10. Health score includes "Customer self-service" component

---

## Important Notes

- The portal is UNAUTHENTICATED — anyone with the token can access it.
  The token's HMAC signature prevents guessing. This is intentional —
  customers should not need to create an account to resolve an issue.
- All portal API endpoints start with /api/portal/ — keep them separate
  from merchant endpoints.
- The portal React components use a LIGHT theme. The merchant dashboard
  uses a dark theme. They share the same React app but different layouts.
- If Kimi/NIM is rate-limited during chat, return the fallback message.
  The chat should NEVER show an error to the customer.
- Refunds via Razorpay API will fail for simulated payments — handle
  this gracefully by simulating the refund response for disp_simulated_*
  orders.
- The portal is the SINGLE MOST IMPRESSIVE DEMO FEATURE. When recording
  the video: open your Gmail, click the portal link from an intervention
  email, show the order status loading, chat with the AI, request a
  refund, see it confirmed — all in 60 seconds. Then switch to the
  merchant dashboard and show the portal metrics: "60% deflection rate,
  3 disputes prevented, ₹12,600 saved."
