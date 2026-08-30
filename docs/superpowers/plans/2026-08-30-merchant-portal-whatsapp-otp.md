# Merchant Portal WhatsApp OTP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a secure merchant portal at `/merchant` using WhatsApp OTP through the existing WhatsLoop integration and the existing Merchant database.

**Architecture:** Keep admin and merchant experiences separate while sharing the same Merchant records. Add one focused portal-auth module that owns OTP challenges, signed merchant sessions, login/logout routes, and a read-only dashboard; reuse existing WhatsLoop text delivery without altering voucher/customer messaging.

**Tech Stack:** FastAPI, SQLAlchemy, existing Pakgat HTML helpers, HMAC-SHA256, Python `secrets`, WhatsLoop text API.

**Spec:** `docs/superpowers/specs/2026-08-30-merchant-portal-whatsapp-otp-design.md`

## Global Constraints

- Canonical merchant URL is `https://pakgat.com/merchant`.
- Do not use Salla auth, usernames/passwords, or SMS in this iteration.
- Use only Pakgat's stored `Merchant.contact_phone` as the OTP destination.
- Never store or log plaintext OTP values.
- OTP validity is 5 minutes; maximum 5 verification attempts; resend cooldown is 60 seconds.
- Merchant session expiry is 14 days and must be HttpOnly, SameSite=Lax, path `/merchant`, Secure when `COOKIE_SECURE` is enabled.
- `pending` and `active` merchants may enter; `suspended` merchants may not.
- Do not alter voucher, Salla, settlement, Sadq state, or current WhatsLoop customer flows.

---

### Task 1: Fix Existing Merchant Contract Summary Regression

**Files:**
- Modify: `app/merchant_profile_admin.py`
- Test: `tests/test_merchant_contract_admin.py`

**Interfaces:**
- Consumes: `app.merchant_contracts.merchant_contract_summary_html(db, merchant_id)`
- Produces: existing `/admin/merchants/{merchant_id}` response including contract summary exactly once.

- [ ] **Step 1: Confirm the existing failing test**

Run: `python -m unittest tests.test_merchant_contract_admin.MerchantContractAdminTests.test_existing_merchant_detail_page_includes_contract_summary -v`
Expected: FAIL because agreement number is absent from rendered detail HTML.

- [ ] **Step 2: Inject the contract summary into the existing detail wrapper**

Import `app.merchant_contracts as contracts` in `merchant_profile_admin.py`. In `_merchant_detail_with_edit`, after injecting the edit button, call `contracts.merchant_contract_summary_html(db, merchant_id)` and insert it before the products section (or immediately after the header/KPI area), guarded so the section appears once.

- [ ] **Step 3: Re-run the focused test**

Run: `python -m unittest tests.test_merchant_contract_admin.MerchantContractAdminTests.test_existing_merchant_detail_page_includes_contract_summary -v`
Expected: PASS.

- [ ] **Step 4: Commit**

Commit message: `fix: render merchant contract summary in admin detail`

---

### Task 2: Merchant OTP Storage and Security Primitives

**Files:**
- Create: `app/merchant_portal.py`
- Modify: `main.py`
- Create: `tests/test_merchant_portal.py`

**Interfaces:**
- Produces `MerchantPortalOtpChallenge`, `ensure_merchant_portal_schema()`, `request_merchant_otp(db, phone)`, `verify_merchant_otp(db, challenge_token, otp)`, `merchant_session_token(merchant_id, expires)`, `valid_merchant_session(token)`.

- [ ] **Step 1: Write failing storage/security tests**

Cover: challenge table registration, six-digit OTP generation, no plaintext OTP storage, HMAC verification, five-minute expiry, 5-attempt cap, 60-second resend cooldown, and session-token tamper rejection.

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `python -m unittest tests.test_merchant_portal -v`
Expected: FAIL because `app.merchant_portal` does not exist.

- [ ] **Step 3: Implement minimal storage/security layer**

Create `MerchantPortalOtpChallenge` on `core.Base` with fields from the spec. Configure `MERCHANT_PORTAL_SECRET = os.getenv("MERCHANT_PORTAL_SECRET", "").strip()`. Hash OTP as `HMAC(secret, f"{challenge_token}:{otp}", sha256)`. Generate OTP with `secrets.randbelow(1_000_000)` formatted to six digits. Session token format: `merchant_id:expires:signature` with constant-time validation.

- [ ] **Step 4: Ensure additive schema and import registration**

Add `ensure_merchant_portal_schema()` using `create(..., checkfirst=True)` and import/call it from `main.py` after `merchant_finance`/`merchant_contracts` are available.

- [ ] **Step 5: Re-run focused tests**

Run: `python -m unittest tests.test_merchant_portal -v`
Expected: PASS for storage/security cases.

- [ ] **Step 6: Commit**

Commit message: `feat: add merchant portal OTP security`

---

### Task 3: WhatsApp OTP Request and Verification Routes

**Files:**
- Modify: `app/merchant_portal.py`
- Modify: `tests/test_merchant_portal.py`

**Interfaces:**
- Consumes: `app.jood_outbound._send_whatsloop_text(phone, message)` and `core.normalize_saudi_phone`.
- Produces routes `GET /merchant`, `POST /merchant/login/request`, `POST /merchant/login/verify`, `POST /merchant/logout`.

- [ ] **Step 1: Write failing route tests**

Cover: known phone sends one WhatsLoop message; unknown phone returns the same generic page; resend before 60 seconds does not send twice; correct OTP sets `pakgat_merchant`; wrong/expired/used OTP cannot authenticate; five wrong attempts block the challenge; logout removes the cookie.

- [ ] **Step 2: Run tests and confirm RED**

Run: `python -m unittest tests.test_merchant_portal -v`
Expected: FAIL only on missing route behavior.

- [ ] **Step 3: Implement OTP request flow**

Normalize the submitted phone, scan Merchant rows by normalized stored contact phone, reject `suspended`, and return generic UI regardless of match. For a valid merchant, enforce cooldown, invalidate previous pending challenge, create a new challenge, send the approved OTP message through `_send_whatsloop_text`, and mark failed delivery without revealing it to unknown callers.

- [ ] **Step 4: Implement verification and cookie issuance**

Validate challenge token + OTP, increment attempts on mismatch, mark used on success, and set the signed 14-day cookie. Never change Merchant status.

- [ ] **Step 5: Implement logout**

Delete `pakgat_merchant` with path `/merchant` and redirect to `/merchant`.

- [ ] **Step 6: Re-run focused tests**

Run: `python -m unittest tests.test_merchant_portal -v`
Expected: PASS.

- [ ] **Step 7: Commit**

Commit message: `feat: add WhatsApp OTP merchant login`

---

### Task 4: Read-Only Merchant Dashboard and Full Regression Gate

**Files:**
- Modify: `app/merchant_portal.py`
- Modify: `tests/test_merchant_portal.py`

**Interfaces:**
- Produces `GET /merchant/dashboard` and merchant-only page rendering.

- [ ] **Step 1: Write failing dashboard tests**

Cover: unauthenticated redirect; active/pending access; suspended denial with old cookie; one merchant cannot see another merchant's profile; latest contract number/status/signed date render; linked products render; admin-only/internal notes are absent.

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `python -m unittest tests.test_merchant_portal -v`
Expected: FAIL on dashboard behavior.

- [ ] **Step 3: Implement dashboard**

Render a branded Arabic page with merchant name/code/status, registered phone, latest contract summary, linked products, logout action, and a clearly labeled future-annex area that does not create or claim annex records.

- [ ] **Step 4: Run focused tests**

Run: `python -m unittest tests.test_merchant_portal -v`
Expected: PASS.

- [ ] **Step 5: Run full verification**

Run: `python -m compileall -q main.py app`
Expected: exit 0.

Run: `python -c "import main; print('ROUTES=' + str(len(main.app.routes)))"`
Expected: import succeeds and route count increases.

Run: `python -m unittest discover -s tests -p 'test_*.py' -v`
Expected: all tests pass with zero failures/errors.

- [ ] **Step 6: Commit**

Commit message: `feat: add merchant portal dashboard`
