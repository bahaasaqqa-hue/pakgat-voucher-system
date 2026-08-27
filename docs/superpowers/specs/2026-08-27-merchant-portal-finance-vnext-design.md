# Merchant Portal & Finance vNext Design

## Goal
Build a conservative, additive merchant/finance layer around the existing Pakgat voucher system without changing the public domain, WhatsLoop endpoints, current voucher URLs, Salla search/data paths, or customer notification delivery flow.

## Safety constraints
- Base all work on `gce-migration`.
- No production deployment from this branch.
- Do not rename or remove existing voucher, notification, Salla, Jood, WhatsLoop, or local-partner tables/columns/routes.
- Do not change `WHATSLOOP_API_BASE_URL`, `WHATSLOOP_API_TOKEN`, `PUBLIC_BASE_URL`, `SALLA_API_BASE_URL`, or any existing outbound URL construction.
- New database work is additive only.
- Existing vouchers remain readable/redeemable.
- Existing customer voucher-issued and redemption notifications remain unchanged.
- Merchant purchase/sale notification is disabled only at the scheduling trigger; historical rows remain untouched.

## Merchant data model
Create a stable `merchants` entity. Each merchant has a stable internal code, display/legal identity fields, VAT/IBAN/contact fields, status, settlement cadence and notes metadata.

Existing `local_partner_products` records remain valid. Add optional `merchant_id`, product commission percentage and product lifecycle mirror fields. Existing product-id/SKU local-first lookup continues to work exactly as before.

## Product model
Salla remains the commercial source of truth for product identity/name/status and relevant availability data. Pakgat owns merchant association, commission, sales rep association and settlement accounting.

Each merchant page lists linked products with:
- product name
- Salla Product ID / SKU
- Pakgat commission percentage
- mirrored product status
- end date when available
- last Salla sync time
- counts for active/redeemed/refunded/expired vouchers

Commission is product-specific. A voucher/financial event stores a commission snapshot so later commission changes only affect future sales.

## Voucher lifecycle
Supported business states:
- `active`
- `redeemed`
- `expired`
- `refunded`
- `revoked`

`expired` means unused voucher whose validity ended. It creates no merchant payable. `refunded`/`revoked` create no merchant payable. Only a successful redemption may create merchant payable value.

Salla `order.cancelled` and `order.refunded` events revoke/refund only active matching vouchers. Redeemed vouchers are never silently reversed; they are flagged for admin review/audit instead.

## Merchant notification policy
Do not notify merchants when the customer merely purchases/receives a voucher. Merchant notifications occur after successful redemption. Existing merchant sale notification rows remain historical; the purchase-time scheduling trigger is disabled.

## Settlement ledger
Create immutable settlement ledger entries from redeemed vouchers. One voucher can contribute to at most one payable entry. Each entry stores gross amount when known, commission snapshot, calculated merchant payable and lifecycle state.

Settlement batches group unpaid payable entries by merchant and weekly cycle. Default cadence is weekly Thursday. Batch states:
- `draft`
- `approved`
- `paid`
- `on_hold`

A paid batch records transfer amount, transfer date, bank name, beneficiary IBAN snapshot, bank reference, recorded-by and optional note. Paid batches are not edited to retroactively rewrite history; later corrections use adjustments.

## Admin dashboard
Extend the existing voucher admin with additive finance cards and a merchant settlement table:
- unpaid merchant liabilities
- ready for Thursday settlement
- paid this week
- paid this month
- merchants with dues
- overdue/on-hold settlements
- refunds requiring review

Each merchant row shows redeemed count, payable amount, settlement state, due date/last transfer and short note.

## Merchant detail page
Admin route `/admin/merchants/{merchant_id}` shows:
- merchant profile/status
- linked products
- active/redeemed/refunded/expired voucher counts
- redemption and refund rates
- current payable
- paid totals
- pending settlements
- recent transfer references
- branches placeholder/data when available
- contract/Sadq fields placeholder-ready but not requiring Sadq API credentials yet
- notes timeline and activity summary

## Contracts / Sadq
Prepare additive contract fields/tables for future Sadq integration, including external document/transaction ids and signed-document metadata. Do not call Sadq until API credentials and exact API contract are provided. This phase must not invent endpoints.

## My Vouchers
Prepare customer-facing lookup only after core merchant/finance logic is stable. The initial release may include a phone-based internal query foundation, but no OTP provider is introduced without an approved provider. Existing individual voucher URLs continue unchanged.

## API security
Protect `POST /api/vouchers` with an internal API secret header when configured. Production configuration must fail closed once `VOUCHER_API_SECRET` is supplied. Salla webhook flow remains unaffected.

## Testing
Regression coverage must prove:
- existing customer WhatsApp message builder text/URL remains unchanged
- existing redemption WhatsApp route/URL construction remains unchanged
- local partner lookup by Product ID/SKU still works
- merchant purchase notification scheduling is disabled
- refund/cancel marks only active vouchers
- redeemed vouchers are not auto-refunded
- expired vouchers create no merchant payable
- redeemed voucher creates a single payable entry
- commission snapshot is immutable after product commission changes
- paid settlement cannot be included again
- admin merchant/finance routes require admin auth
