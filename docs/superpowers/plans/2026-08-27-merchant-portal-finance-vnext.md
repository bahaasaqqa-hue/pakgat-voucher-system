# Merchant Portal & Finance vNext Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add merchant management, product-level commission, refund/expiry lifecycle visibility, settlement accounting, and finance dashboard safely around the existing Pakgat voucher system.

**Architecture:** Keep existing voucher/Salla/WhatsLoop behavior intact and add a focused `app/merchant_finance.py` extension module imported by the GCE entry path. Reuse existing `LocalPartnerProduct` and voucher tables via additive columns/tables and only make narrow changes to existing webhook/scheduling points where lifecycle behavior must change.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, PostgreSQL, pytest, existing Salla webhook flow, existing WhatsLoop integration.

**Spec:** `docs/superpowers/specs/2026-08-27-merchant-portal-finance-vnext-design.md`

## Global Constraints
- Base branch is `gce-migration`; implementation branch is `feat/merchant-portal-finance-vnext`.
- No production deployment from this branch.
- Do not alter public domains or existing WhatsLoop/Salla endpoint construction.
- Database changes are additive only.
- Existing voucher URLs and notification message builders remain compatible.
- Merchant payable is created only after successful redemption.
- Expired/refunded/revoked vouchers create no merchant payable.
- Commission is product-specific and snapshotted at redemption/payable creation.
- Weekly settlement cadence defaults to Thursday.

---

### Task 1: Regression safety tests
**Files:**
- Create: `tests/test_merchant_finance_regression.py`
- Read only: `app/application.py`, `app/gce_entry.py`

**Interfaces:**
- Consumes existing message builders, voucher status handling, local partner registry.
- Produces regression gates for URL/message compatibility and existing lookup behavior.

- [ ] Write tests asserting existing customer voucher WhatsApp builder still includes the supplied verification URL and Pakgat URL.
- [ ] Write tests asserting merchant redemption WhatsApp builder remains available and does not introduce purchase-time wording.
- [ ] Write a test confirming local partner lookup still resolves Product ID/SKU.
- [ ] Run targeted tests and confirm baseline behavior before feature code.
- [ ] Commit tests.

### Task 2: Merchant and finance schema
**Files:**
- Create: `app/merchant_finance.py`
- Modify: `main.py`
- Test: `tests/test_merchant_finance_models.py`

**Interfaces:**
- Produces `Merchant`, `MerchantNote`, `MerchantContract`, `MerchantPayable`, `SettlementBatch`, `SettlementPayment` SQLAlchemy models.
- Produces `ensure_merchant_finance_schema()` and helper functions.

- [ ] Write failing model/schema tests for stable merchant identity, product commission snapshot, unique payable per voucher and settlement payment fields.
- [ ] Implement focused models and additive schema bootstrap.
- [ ] Import `app.merchant_finance` in `main.py` before final unified-theme import.
- [ ] Run model tests plus existing voucher tests.
- [ ] Commit schema foundation.

### Task 3: Upgrade local partner products without breaking lookup
**Files:**
- Modify: `app/gce_entry.py`
- Test: `tests/test_merchant_product_linking.py`

**Interfaces:**
- Existing `_lookup_local_partner()` remains compatible.
- Adds optional merchant association, commission percentage, lifecycle mirror and last-sync fields.

- [ ] Write failing tests proving old rows with only Product ID/SKU still resolve.
- [ ] Write failing tests for merchant-linked product with commission.
- [ ] Add nullable fields and additive schema ALTER helper for existing deployments.
- [ ] Preserve metadata payload and local-first Salla fallback behavior.
- [ ] Run tests.
- [ ] Commit product-link upgrade.

### Task 4: Voucher lifecycle refund/cancel/expiry accounting
**Files:**
- Modify: `app/application.py`
- Modify: `app/merchant_finance.py`
- Test: `tests/test_voucher_finance_lifecycle.py`

**Interfaces:**
- Adds safe helpers `mark_order_vouchers_refunded_or_revoked()` and `ensure_payable_for_redeemed_voucher()`.

- [ ] Write failing tests: active voucher can become refunded/revoked; redeemed voucher is not auto-reversed; expired voucher creates no payable.
- [ ] Extend accepted status labels/UI safely for refunded/revoked.
- [ ] Handle `order.refunded` and `order.cancelled` Salla events without altering signature verification.
- [ ] Preserve redeemed voucher and log review action if refund/cancel arrives afterward.
- [ ] Run lifecycle tests and existing webhook reliability tests.
- [ ] Commit lifecycle handling.

### Task 5: Disable merchant purchase notification while preserving redemption notification
**Files:**
- Modify: `app/application.py`
- Test: `tests/test_merchant_notification_policy.py`

**Interfaces:**
- Historical `merchant_sale_notifications` remains untouched.
- Purchase-time scheduling no longer creates/sends merchant sale messages.
- `notify_merchant_after_redemption()` remains unchanged in outbound endpoint construction.

- [ ] Write failing test proving purchase webhook does not reserve merchant sale notification.
- [ ] Write regression test proving redemption path still reserves merchant redemption notification.
- [ ] Disable only the purchase-time scheduling trigger.
- [ ] Run notification and WhatsLoop regression tests.
- [ ] Commit notification policy change.

### Task 6: Merchant payable and weekly settlement engine
**Files:**
- Modify: `app/merchant_finance.py`
- Test: `tests/test_merchant_settlements.py`

**Interfaces:**
- Produces `ensure_payable_for_redeemed_voucher(voucher_id)`.
- Produces `build_weekly_settlement_batch(merchant_id, as_of)`.
- Produces `record_settlement_payment(...)`.

- [ ] Write failing test: redeemed voucher creates one payable only.
- [ ] Write failing test: commission snapshot remains unchanged after product commission edit.
- [ ] Write failing test: only unpaid payables enter a batch.
- [ ] Write failing test: paid batch cannot be paid/included twice.
- [ ] Implement minimal settlement engine with Thursday due-date calculation.
- [ ] Run settlement tests.
- [ ] Commit settlement engine.

### Task 7: Admin merchant pages and finance dashboard
**Files:**
- Modify: `app/merchant_finance.py`
- Test: `tests/test_merchant_admin_routes.py`

**Interfaces:**
- Adds `/admin/merchants`, `/admin/merchants/{id}`, `/admin/settlements` and payment recording route.
- Extends admin navigation additively.

- [ ] Write failing auth tests for new routes.
- [ ] Write response tests for merchant product counts, redeemed/refunded/expired metrics, notes and settlement statuses.
- [ ] Implement merchant list/detail pages with compact tables.
- [ ] Implement finance overview cards and merchant dues table.
- [ ] Implement paid transfer fields: amount, transfer date, bank, IBAN snapshot, reference, recorded-by, note.
- [ ] Add short notes field to overview and full timeline on merchant page.
- [ ] Run route tests.
- [ ] Commit admin UI.

### Task 8: API creation protection
**Files:**
- Modify: `app/application.py`
- Test: `tests/test_voucher_api_security.py`

**Interfaces:**
- Optional env `VOUCHER_API_SECRET`.
- Header `X-Pakgat-Voucher-Secret` required when secret is configured.

- [ ] Write failing tests for missing/wrong/correct header when configured.
- [ ] Implement constant-time comparison dependency without touching Salla webhook auth.
- [ ] Run API security plus webhook tests.
- [ ] Commit API protection.

### Task 9: Full regression verification
**Files:** none unless fixes are required.

- [ ] Run full pytest suite.
- [ ] Confirm no tests changed WhatsLoop base URL, Pakgat public URL, Salla API base URL or voucher verification route format.
- [ ] Review diff for unrelated changes.
- [ ] Open a draft PR from `feat/merchant-portal-finance-vnext` to `gce-migration` with deployment explicitly disabled pending review.
