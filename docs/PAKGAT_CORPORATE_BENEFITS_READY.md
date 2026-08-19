# Pakgat Corporate Benefits — Activation Runbook

## Architecture

Pakgat/Salla customer → Corporate Benefits on Google → PostgreSQL → Salla Customer Group.

The current implementation is intentionally inside the existing Google-hosted Pakgat FastAPI service so it can share the same Postgres, OAuth store and deployment process while remaining logically isolated through `corporate_*` tables and `/corporate` routes.

## Employee flow

1. Employee opens `/corporate`.
2. Enters the mobile number registered with Pakgat/Salla.
3. Backend looks up the Salla customer and keeps the Salla Customer ID as the source-of-truth identifier.
4. Employee enters corporate email.
5. Domain is matched to an active Corporate Company/domain whitelist.
6. A 6-digit email OTP is sent. Only a salted PBKDF2 hash is stored; the raw OTP is never stored or logged.
7. Successful verification activates the local corporate membership for the configured membership period.
8. If the company already has a Salla Customer Group ID, the customer is added to that group immediately. Otherwise the member remains `verified_pending_sync` and can be synchronized later without repeating email verification.

## Database tables

- `corporate_companies`
- `corporate_company_domains`
- `corporate_members`
- `corporate_otp_challenges`
- `corporate_audit_logs`

Salla remains the source of truth for customers, orders and payments. Corporate tables store only company membership/verification state.

## Admin routes

- `/admin/company/corporate` — companies, readiness, members.
- `/admin/company/corporate/companies/new` — add company/domain locally.
- `POST /admin/company/corporate/companies/{id}/sync-salla` — create missing Salla group then sync verified pending members.
- `/admin/company/corporate/readiness` — machine-readable readiness status.

## Safety defaults

`CORPORATE_LIVE=false` by default. The public form is visible but activation is blocked until the switch is changed. This lets us deploy and test schema/UI without exposing an unfinished employee flow.

OTP rules:
- 6 digits.
- 10-minute default expiry, configurable from 3 to 20 minutes.
- 60-second resend cooldown.
- maximum 5 verification attempts per challenge.
- raw OTP is never persisted.

## External items still required before public activation

1. Salla OAuth token on Google with `customers.read_write` permission.
2. One transactional SMTP sender for OTP email.
3. At least one company/domain in the Corporate admin page.
4. Salla Customer Group ID for that company, or allow the prepared sync action to create it after OAuth is available.
5. DNS `benefits.pakgat.com` → GCE static IP, then issue TLS certificate and enable the prepared Nginx config.
6. Set `CORPORATE_LIVE=true` only after one end-to-end test account succeeds.

## Discounts / offers

Customer Group membership is prepared now. Do not assume a Customer Group by itself creates a discount. If Pakgat wants automatic percentage offers tied to the group, the Salla app also needs `specialoffers.read_write`, and a corporate special offer can then target `customer_groups`. Keep this as a separate activation step so membership verification cannot be broken by offer configuration.

## AI Company

Corporate Benefits is exposed in the Pakgat AI Company sidebar as `الشركات والموظفون` and the CEO dashboard gets a compact status card showing companies, active members and pending Salla sync.
