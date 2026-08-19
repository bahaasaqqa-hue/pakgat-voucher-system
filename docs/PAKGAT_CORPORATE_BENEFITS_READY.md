# Pakgat Corporate Benefits — Activation Runbook

## Final architecture

Pakgat Theme V3 / Salla customer profile → Salla login + OTP → verified Salla profile email → `customer.updated` → Google Corporate Benefits → company-domain match → Salla Customer Group.

Salla remains the source of truth for customer authentication, mobile, email, orders and payments. Google stores only the additional Corporate Benefits state and company mapping.

## Final employee flow

1. Employee sees the homepage banner/section: **فعّل مزايا شركتك**.
2. If not logged in, Salla handles customer login and mobile OTP through its storefront login component.
3. The activation page uses the logged-in Salla customer profile. The mobile number is not verified again by Google.
4. Employee adds/updates the corporate email in the Salla profile/contact flow.
5. Salla handles the email OTP and commits the email only after successful verification.
6. Salla emits `customer.updated`.
7. Google receives the signed event at `/webhooks/salla-corporate`, then fetches Customer Details by Salla Customer ID.
8. Google extracts the email domain and matches it against `corporate_company_domains`.
9. If the domain belongs to an active Pakgat Corporate company, Google upserts `corporate_members` using the Salla Customer ID as the permanent identifier.
10. When `CORPORATE_LIVE=true`, Google creates the company's Salla Customer Group if needed and adds the customer to it. If Salla is temporarily unavailable, membership remains `verified_pending_sync` and can be retried without asking the employee to verify again.

## What Google does NOT do

- No mobile OTP.
- No email OTP.
- No second customer account.
- No separate Corporate password/authentication system.
- No SMTP dependency for employee verification.

The old standalone OTP code remains disabled/staging only and is not the approved production flow.

## Database tables

- `corporate_companies`
- `corporate_company_domains`
- `corporate_members`
- `corporate_audit_logs`

Legacy/staging table `corporate_otp_challenges` may remain in PostgreSQL for compatibility but is not used by the approved Salla-managed production flow.

## Backend routes prepared

- `POST /webhooks/salla-corporate` — dedicated signed `customer.updated` receiver.
- `POST /admin/company/corporate/sync-pending` — retry eligible members waiting for Salla group synchronization.
- `/admin/company/corporate` — company/domain/member administration.

## Salla permissions required at activation

- `customers.read` to fetch Customer Details.
- `customers.read_write` to create/update Customer Groups and add customers.
- `webhooks.read_write` only if Pakgat registers the `customer.updated` webhook programmatically; otherwise the Partner App Store Event can be configured from Salla.
- `specialoffers.read_write` only if Pakgat later enables automatic group-targeted special offers. This is independent from membership verification.

## Webhook security

`/webhooks/salla-corporate` verifies `X-Salla-Signature` with the configured Salla webhook secret using HMAC-SHA256 and timing-safe comparison before processing any customer event.

## Safety defaults

- `CORPORATE_LIVE=false` until the first end-to-end test succeeds.
- Customer/profile events can be captured and eligible members can remain `verified_pending_sync` while live write actions are disabled.
- No Customer Group write occurs while Corporate live mode is off.
- Existing Voucher System behavior is not changed.

## Theme V3 implementation

The theme should contain:

1. Homepage banner/section: **فعّل مزايا شركتك**.
2. A dedicated activation view/card inside the Salla storefront experience.
3. Salla login component when the visitor is not authenticated.
4. Salla profile/contact update for the corporate email.
5. Salla verify component/modal with `type="email"` when the email change returns verification pending.
6. Success message explaining that Corporate Benefits will activate automatically after verification; Google processes the resulting `customer.updated` event in the background.

Do not ask the customer to re-enter a mobile number after Salla login unless the Salla profile itself requires it.

## External items still required before public activation

1. Complete Salla OAuth on Google with the required customer scopes.
2. Add the `customer.updated` Store Event / webhook to the Corporate endpoint.
3. Add at least one real company and approved corporate email domain.
4. Create or sync that company's Salla Customer Group.
5. Insert the approved Theme V3 banner + activation UI.
6. Run one real employee end-to-end test.
7. Set `CORPORATE_LIVE=true` only after the test succeeds.

## AI Company

Corporate Benefits remains exposed in Pakgat AI Company as **الشركات والموظفون**. Status should reflect Salla OAuth + company/domain readiness; SMTP is no longer part of production readiness.
