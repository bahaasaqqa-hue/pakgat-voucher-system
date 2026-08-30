# Merchant Sadq Completion & WhatsApp Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record completed Sadq merchant contracts on the existing Pakgat merchant profile, preserve immutable agreement identity, notify the merchant on WhatsApp, and expose safe retry/audit controls without changing merchant activation, vouchers, or finance calculations.

**Architecture:** Extend the existing `merchant_finance` data model additively, with one safe schema migration for `merchant_contracts.agreement_number`. Put Sadq webhook normalization, signed-file retrieval, delivery orchestration, and admin retry/UI augmentation in a focused `app/merchant_contracts.py` module. Reuse the existing WhatsLoop text sender and keep media/document sending behind a dedicated adapter so no undocumented provider endpoint is invented.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, urllib, unittest, existing Pakgat/WhatsLoop integration.

**Spec:** `docs/superpowers/specs/2026-08-30-merchant-sadq-whatsapp-completion-design.md`

## Global Constraints

- Do not change voucher issuance, redemption, Salla webhook behavior, existing customer notifications, settlement calculations, or WhatsLoop inbound behavior.
- Sadq completion never activates a merchant.
- The webhook must fail closed when `SADQ_WEBHOOK_TOKEN` is absent or invalid.
- No Sadq Account Secret, password, OTP, bearer token, or authorization header is exposed in HTML, JS, logs, or repository files.
- Repeated completed callbacks are idempotent and must not duplicate merchant notes or WhatsApp delivery.
- Signed-document retrieval uses `GET /api/v1/documents/{id}/signed` with server-side bearer auth only.
- Do not invent a WhatsLoop media/document endpoint. Text delivery uses the existing sender; document delivery is attempted only through a provider adapter with an explicitly configured/documented endpoint contract.
- Existing finance and voucher tests must remain unchanged and passing.

---

### Task 1: Add contract identity and delivery audit storage

**Files:**
- Modify: `app/merchant_finance.py`
- Test: `tests/test_merchant_contracts.py`

**Interfaces:**
- Produces: `MerchantContract.agreement_number: Optional[str]`
- Produces: `MerchantContractDelivery` SQLAlchemy model
- Produces: `ensure_merchant_contract_schema() -> None`
- Produces: `next_agreement_number(db: Session, when: datetime | None = None) -> str`

- [ ] **Step 1: Write failing storage tests**

Create `tests/test_merchant_contracts.py` with tests that import the real application/database models and assert:

```python
class MerchantContractStorageTests(unittest.TestCase):
    def test_agreement_number_format_uses_riyadh_year_month_and_sequence(self):
        number = contracts.next_agreement_number(self.db, datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc))
        self.assertRegex(number, r"^PKG-MA-2026-08-\d{4}$")

    def test_delivery_is_unique_per_contract_and_channel(self):
        first = finance.MerchantContractDelivery(
            merchant_contract_id=self.contract.id,
            merchant_id=self.merchant.id,
            channel="whatsapp",
            destination="966500000000",
            status="pending",
        )
        self.db.add(first)
        self.db.commit()
        duplicate = finance.MerchantContractDelivery(
            merchant_contract_id=self.contract.id,
            merchant_id=self.merchant.id,
            channel="whatsapp",
            destination="966500000000",
            status="pending",
        )
        self.db.add(duplicate)
        with self.assertRaises(IntegrityError):
            self.db.commit()
```

- [ ] **Step 2: Run the targeted tests and verify RED**

Run: `python -m unittest tests.test_merchant_contracts.MerchantContractStorageTests -v`

Expected: failure because `MerchantContractDelivery`, `agreement_number`, and agreement-number helper do not exist.

- [ ] **Step 3: Implement minimal additive schema support**

In `app/merchant_finance.py`:

```python
class MerchantContract(core.Base):
    ...
    agreement_number: Mapped[Optional[str]] = mapped_column(String(40), nullable=True, unique=True, index=True)


class MerchantContractDelivery(core.Base):
    __tablename__ = "merchant_contract_deliveries"
    __table_args__ = (
        UniqueConstraint("merchant_contract_id", "channel", name="uq_contract_delivery_channel"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    merchant_contract_id: Mapped[int] = mapped_column(Integer, index=True)
    merchant_id: Mapped[int] = mapped_column(Integer, index=True)
    channel: Mapped[str] = mapped_column(String(30), default="whatsapp", index=True)
    destination: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    provider_message_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=core.now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=core.now_utc)
```

Add the new table to `FINANCE_TABLES`. Add `ensure_merchant_contract_schema()` that first calls `ensure_merchant_finance_schema()`, inspects `merchant_contracts`, safely adds nullable `agreement_number` when missing, then creates a unique index if absent. The migration must be safe on SQLite test DB and PostgreSQL production.

Implement `next_agreement_number()` by converting `when or core.now_utc()` to Riyadh time, querying the highest existing number matching `PKG-MA-YYYY-MM-%`, parsing the final four digits, and returning the next zero-padded serial. Unique DB enforcement remains the final race guard.

- [ ] **Step 4: Run storage tests and full merchant finance tests**

Run:

```bash
python -m unittest tests.test_merchant_contracts.MerchantContractStorageTests -v
python -m unittest tests.test_merchant_finance_models tests.test_merchant_finance_regression tests.test_merchant_settlements -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/merchant_finance.py tests/test_merchant_contracts.py
git commit -m "feat: add merchant contract delivery audit"
```

---

### Task 2: Normalize and authenticate Sadq completion callbacks

**Files:**
- Create: `app/merchant_contracts.py`
- Modify: `main.py`
- Test: `tests/test_merchant_contracts.py`

**Interfaces:**
- Produces: `normalize_sadq_status(value) -> Optional[str]`
- Produces: `extract_sadq_callback(payload: dict) -> SadqCallback`
- Produces: `POST /integrations/sadq/webhook`
- Consumes: existing `MerchantContract`, `Merchant`, `MerchantNote`

- [ ] **Step 1: Write failing webhook tests**

Add tests for:

```python
def test_invalid_webhook_token_does_not_change_contract(self):
    response = self.client.post(
        "/integrations/sadq/webhook",
        headers={"Authorization": "Bearer wrong"},
        json={"requestId": self.contract.sadq_transaction_id, "status": 2},
    )
    self.assertIn(response.status_code, {401, 403})
    self.db.refresh(self.contract)
    self.assertEqual(self.contract.status, "sent")


def test_completed_webhook_marks_contract_signed_without_activating_merchant(self):
    response = self.client.post(
        "/integrations/sadq/webhook",
        headers={"Authorization": "Bearer webhook-test-token"},
        json={"requestId": self.contract.sadq_transaction_id, "documentId": self.contract.sadq_document_id, "status": 2},
    )
    self.assertEqual(response.status_code, 200)
    self.db.refresh(self.contract)
    self.db.refresh(self.merchant)
    self.assertEqual(self.contract.status, "signed")
    self.assertIsNotNone(self.contract.signed_at)
    self.assertEqual(self.merchant.status, "pending")
```

Also test rejected/cancelled/expired normalization, unknown contract 404, and unknown/non-terminal status acknowledgement without mutation.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m unittest tests.test_merchant_contracts.MerchantSadqWebhookTests -v`

Expected: 404 route/not-defined failures.

- [ ] **Step 3: Implement webhook module**

Create `app/merchant_contracts.py` with:

```python
@dataclass(frozen=True)
class SadqCallback:
    request_id: str
    document_id: str
    status: Optional[str]


def normalize_sadq_status(value) -> Optional[str]:
    mapping = {
        "2": "signed", "completed": "signed", "success": "signed",
        "4": "rejected", "rejected": "rejected",
        "3": "cancelled", "cancelled": "cancelled", "voided": "cancelled",
        "5": "expired", "expired": "expired",
    }
    return mapping.get(str(value or "").strip().lower())
```

The extractor reads only documented/common callback concepts: `requestId`, `documentId`, and `status`, with snake_case aliases for compatibility. Do not accept a phone number from the callback.

Webhook auth compares the configured `SADQ_WEBHOOK_TOKEN` against an incoming bearer token or `X-Sadq-Webhook-Token` using `hmac.compare_digest`. Missing server configuration fails closed with 503; invalid client token returns 403.

Find a contract by `sadq_transaction_id` first, then `sadq_document_id`. Terminal transitions update only `MerchantContract`; `Merchant.status` is never touched. First transition to signed creates exactly one contract note.

- [ ] **Step 4: Register module in `main.py` and run tests**

Add:

```python
from app import merchant_contracts as _merchant_contracts  # noqa: F401 - Sadq contract completion + merchant WhatsApp audit
```

Run targeted webhook tests and `python -m compileall -q main.py app`.

- [ ] **Step 5: Commit**

```bash
git add app/merchant_contracts.py main.py tests/test_merchant_contracts.py
git commit -m "feat: handle authenticated Sadq contract callbacks"
```

---

### Task 3: Retrieve the signed Sadq PDF and orchestrate idempotent WhatsApp delivery

**Files:**
- Modify: `app/merchant_contracts.py`
- Test: `tests/test_merchant_contracts.py`

**Interfaces:**
- Produces: `download_signed_sadq_pdf(document_id: str) -> tuple[bool, bytes | None, str]`
- Produces: `deliver_signed_contract(db: Session, contract: MerchantContract) -> MerchantContractDelivery`
- Reuses: `app.jood_outbound._send_whatsloop_text(phone, message)`

- [ ] **Step 1: Write failing delivery tests**

Tests must patch network boundaries only and assert real orchestration state:

```python
def test_pdf_retrieval_failure_keeps_signed_and_records_failed_delivery(self):
    with patch("app.merchant_contracts.download_signed_sadq_pdf", return_value=(False, None, "sadq_http_502")):
        delivery = contracts.deliver_signed_contract(self.db, self.contract)
    self.db.refresh(self.contract)
    self.assertEqual(self.contract.status, "signed")
    self.assertEqual(delivery.status, "failed")
    self.assertEqual(delivery.attempt_count, 1)


def test_missing_merchant_phone_records_failure(self):
    self.merchant.contact_phone = None
    self.db.commit()
    delivery = contracts.deliver_signed_contract(self.db, self.contract)
    self.assertEqual(delivery.status, "failed")
    self.assertEqual(delivery.last_error, "merchant_contact_phone_missing")
```

Add a successful-text test that asserts destination uses normalized `Merchant.contact_phone`, provider response is safely summarized, `attempt_count` increments once, and the activity note is created once. Add a duplicate-completion test proving the existing `sent` delivery is not resent.

- [ ] **Step 2: Run delivery tests and verify RED**

Run: `python -m unittest tests.test_merchant_contracts.MerchantContractDeliveryTests -v`

Expected: missing delivery functions.

- [ ] **Step 3: Implement signed-PDF retrieval**

Use environment values:

```python
SADQ_API_BASE_URL = os.getenv("SADQ_API_BASE_URL", "https://sandbox-api.sadq-sa.com").rstrip("/")
SADQ_BEARER_TOKEN = os.getenv("SADQ_BEARER_TOKEN", "").strip()
```

Request exactly:

`GET {SADQ_API_BASE_URL}/api/v1/documents/{document_id}/signed`

with `Authorization: Bearer ...`, `Accept: application/pdf`. Return only safe error codes/summaries; never return or log authorization values.

- [ ] **Step 4: Implement delivery orchestration**

`deliver_signed_contract()` must:

1. Fetch/create the one `(contract, whatsapp)` delivery row.
2. Return immediately when status is already `sent`.
3. Increment `attempt_count` for each real attempt.
4. Normalize destination from `Merchant.contact_phone` using `core.normalize_saudi_phone`.
5. Download the signed PDF first; failure records `failed` and never changes contract status.
6. Send the approved Arabic completion text using the existing `_send_whatsloop_text`.
7. Do not invent a document endpoint. If no documented WhatsLoop document adapter is configured, record a safe `whatsloop_document_sender_not_configured` failure after successful text. This keeps audit truth: the delivery is not considered complete until the PDF can also be sent.
8. When a documented provider document sender is later configured/implemented, it must update the same row rather than create a second logical delivery.

Approved message:

```text
تم توقيع اتفاقية الشراكة مع Pakgat بنجاح ✅
رقم الاتفاقية: {agreement_number}
أرفقنا لك نسخة الاتفاقية الموقعة للاحتفاظ بها.
سيكون التواصل التشغيلي معك عبر رقم الواتساب المسجل لدينا.
```

If `agreement_number` is missing, do not invent one in the webhook path; use a safe internal failure `agreement_number_missing` and leave the contract signed.

- [ ] **Step 5: Connect first signed transition to delivery and run tests**

Only the first transition into `signed` calls `deliver_signed_contract()`. A duplicate callback to a contract already `signed` acknowledges without calling it again.

Run targeted delivery tests and webhook tests.

- [ ] **Step 6: Commit**

```bash
git add app/merchant_contracts.py tests/test_merchant_contracts.py
git commit -m "feat: audit merchant signed-contract delivery"
```

---

### Task 4: Add admin contract visibility and retry controls

**Files:**
- Modify: `app/merchant_contracts.py`
- Modify: `app/merchant_profile_admin.py`
- Test: `tests/test_merchant_contracts.py`

**Interfaces:**
- Produces: `POST /admin/merchants/{merchant_id}/contracts/{contract_id}/retry-whatsapp`
- Produces: contract/delivery summary HTML injected into existing merchant detail/edit UI

- [ ] **Step 1: Write failing admin tests**

Cover:

```python
def test_admin_retry_requires_auth(self):
    response = self.unauthenticated_client.post(
        f"/admin/merchants/{self.merchant.id}/contracts/{self.contract.id}/retry-whatsapp",
        follow_redirects=False,
    )
    self.assertEqual(response.status_code, 303)
    self.assertIn("/admin/login", response.headers["location"])


def test_retry_reuses_existing_delivery_row(self):
    before_id = self.delivery.id
    with patch("app.merchant_contracts.deliver_signed_contract") as deliver:
        deliver.return_value = self.delivery
        response = self.client.post(
            f"/admin/merchants/{self.merchant.id}/contracts/{self.contract.id}/retry-whatsapp",
            follow_redirects=False,
        )
    self.assertEqual(response.status_code, 303)
    self.assertEqual(self.db.query(finance.MerchantContractDelivery).count(), 1)
    self.assertEqual(self.db.query(finance.MerchantContractDelivery).first().id, before_id)
```

Also assert merchant detail/edit HTML includes agreement number, contract status, Sadq document/request IDs, signed date, delivery status/attempt count, safe error, and retry button only when signed and not sent.

- [ ] **Step 2: Run admin tests and verify RED**

Run: `python -m unittest tests.test_merchant_contracts.MerchantContractAdminTests -v`

- [ ] **Step 3: Implement retry route and UI augmentation**

Retry route must use existing admin auth, verify the contract belongs to the merchant, reject non-signed contracts with 409, call `deliver_signed_contract()`, then redirect back to `/admin/merchants/{merchant_id}`.

Extend the existing contract section in `merchant_profile_admin.py`; augment the existing merchant-detail response without rewriting finance calculations/tables. Escape every displayed value through `core.esc` and never show tokens.

- [ ] **Step 4: Run targeted admin tests and existing merchant admin regression tests**

Run:

```bash
python -m unittest tests.test_merchant_contracts.MerchantContractAdminTests -v
python -m unittest tests.test_merchant_admin_routes tests.test_merchant_profile_admin -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/merchant_contracts.py app/merchant_profile_admin.py tests/test_merchant_contracts.py
git commit -m "feat: show and retry merchant contract delivery"
```

---

### Task 5: Document deployment settings and run full regression verification

**Files:**
- Modify: `deploy/gce/pakgat.env.example`
- Modify: `docs/superpowers/specs/2026-08-30-merchant-sadq-whatsapp-completion-design.md` only if implementation evidence requires a clarified documented constraint
- Test: full suite

**Interfaces:**
- Deployment environment consumes `SADQ_API_BASE_URL`, `SADQ_BEARER_TOKEN`, `SADQ_WEBHOOK_TOKEN`

- [ ] **Step 1: Add non-secret environment examples**

Append:

```dotenv
# Sadq merchant contract completion
SADQ_API_BASE_URL=https://sandbox-api.sadq-sa.com
SADQ_BEARER_TOKEN=
SADQ_WEBHOOK_TOKEN=
```

Do not add Account ID, Account Secret, username, password, or sandbox OTP.

- [ ] **Step 2: Compile and run the full regression suite**

Run:

```bash
python -m compileall -q main.py app
python -m unittest discover -s tests -p 'test_*.py' -v
```

Expected: all tests PASS.

- [ ] **Step 3: Verify repository safety properties**

Confirm through tests/code review:

- Duplicate signed callbacks do not resend.
- Merchant activation remains unchanged.
- No callback phone is trusted.
- No Sadq secrets are rendered or logged.
- Voucher/finance behavior is untouched.
- Failed document/WhatsApp delivery cannot roll back a signed contract.

- [ ] **Step 4: Commit**

```bash
git add deploy/gce/pakgat.env.example
git commit -m "docs: configure Sadq contract completion"
```

- [ ] **Step 5: Open PR to `gce-migration` and use CI as the final execution gate**

PR title:

`feat: complete merchant Sadq contracts and WhatsApp audit`

The existing `Jood PR Verification` workflow compiles all application modules, imports the full app, and runs `python -m unittest discover -s tests -p 'test_*.py' -v`. Do not claim completion until that workflow is green.
