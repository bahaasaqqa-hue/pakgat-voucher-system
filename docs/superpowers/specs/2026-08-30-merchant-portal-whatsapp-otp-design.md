# Pakgat Merchant Portal + WhatsApp OTP Design

## Goal
Provide merchants a public, branded portal at `https://pakgat.com/merchant` while keeping Pakgat internal operations under `voucher.pakgat.com/admin`. Merchants authenticate using a one-time code sent through Pakgat's existing WhatsLoop WhatsApp integration; no Salla login, username/password, or SMS provider is introduced.

## Scope
This iteration adds the portal foundation only:
- fix the remaining merchant-admin contract-summary integration regression;
- public merchant login at `/merchant`;
- WhatsApp OTP request/verify flow;
- secure merchant session cookie;
- merchant dashboard reading the existing Merchant/Contract/Product data;
- logout;
- tests and additive database schema.

Offer annex creation/approval, signed-PDF WhatsApp attachment transport, and new settlement calculations remain outside this iteration.

## Domain and routing
Canonical merchant URL: `https://pakgat.com/merchant`.
The application routes are `/merchant`, `/merchant/login/request`, `/merchant/login/verify`, `/merchant/dashboard`, and `/merchant/logout`. Production routing/proxy must forward `pakgat.com/merchant*` to the Pakgat application while preserving the public `pakgat.com` host.

Admin remains separate: `https://voucher.pakgat.com/admin/...`.

## Identity model
The canonical identity is `Merchant.id`. `Merchant.contact_phone` is only the current login delivery destination. Changing a merchant's phone must not change the merchant identity, contract history, product links, or settlements.

Portal access is allowed for `pending` and `active` merchants. `suspended` merchants are denied even if they hold an old cookie.

## OTP challenge storage
Add an additive table `merchant_portal_otp_challenges` with:
- `id`
- `challenge_token` unique random public identifier
- `merchant_id`
- `destination`
- `otp_hash`
- `status`: `pending`, `used`, `expired`, `failed`
- `attempt_count`
- `expires_at`
- `sent_at`
- `used_at`
- `created_at`

No plaintext OTP is stored.

OTP rules:
- six numeric digits generated with `secrets`;
- five-minute validity;
- maximum five verify attempts;
- at least sixty seconds between sends for the same merchant;
- issuing a newer challenge invalidates previous pending challenges;
- successful verification immediately marks the challenge used.

Unknown phone numbers receive the same generic UI response as known numbers. The login UI must not reveal whether a phone belongs to a Pakgat merchant.

## OTP delivery
Reuse the existing WhatsLoop text transport and existing `WHATSLOOP_API_BASE_URL` / `WHATSLOOP_API_TOKEN` settings.

Approved message:

`رمز الدخول إلى بوابة Pakgat للتجار: {code}\nالرمز صالح لمدة 5 دقائق.\nلا تشارك الرمز مع أي شخص.`

Normalize the destination from `Merchant.contact_phone`; never trust a destination supplied by the browser beyond locating the merchant.

## Portal secret and hashing
Add `MERCHANT_PORTAL_SECRET`. Production must fail closed for OTP/session creation when it is empty. Tests set an explicit test secret.

OTP hashing uses HMAC-SHA256 over `challenge_token:otp` with `MERCHANT_PORTAL_SECRET`. Verification uses constant-time comparison.

## Merchant session
After successful OTP verification, set an HttpOnly cookie `pakgat_merchant` containing `merchant_id`, expiry, and an HMAC-SHA256 signature under `MERCHANT_PORTAL_SECRET`.

Cookie requirements:
- HttpOnly;
- Secure when `COOKIE_SECURE` is enabled;
- SameSite=Lax;
- Path `/merchant`;
- 14-day expiry.

Every authenticated request re-loads the Merchant row and rejects missing or suspended merchants. Logout deletes the cookie.

## Portal dashboard
The first dashboard is intentionally operational and read-only. It shows:
- merchant display/legal name and Pakgat merchant code;
- current merchant status (`pending` / `active`);
- registered phone;
- latest partnership agreement number/status and signed date;
- linked products with product name/SKU/status;
- clear navigation placeholders for future offer annexes without fabricating annex records.

The portal must never expose admin controls, other merchants, internal notes, Sadq bearer credentials, WhatsLoop credentials, or unrestricted finance-management actions.

## Admin contract-summary regression
Before adding the portal, fix the existing test failure where the contract summary helper exists but its HTML is not injected into the current merchant detail page. Preserve all existing finance/voucher calculations and admin theme behavior.

## Security and audit
- Never log OTP values or secrets.
- Generic response for unknown phone.
- Rate-limit resend and verification attempts in persistent DB state.
- Use only the merchant phone stored by Pakgat for OTP delivery.
- Login does not alter `Merchant.status`.
- OTP/session code does not touch vouchers, Salla customer flows, settlement calculations, or Sadq contract state.

## Tests
Tests must prove:
1. existing merchant detail page renders the contract summary;
2. OTP request for a known merchant sends through WhatsLoop and stores only a hash;
3. unknown phone gets generic response and no merchant is created;
4. resend within 60 seconds does not send again;
5. correct OTP issues a merchant cookie and marks the challenge used;
6. wrong OTP increments attempts and never authenticates;
7. expired/used challenges cannot authenticate;
8. five failed attempts block verification;
9. pending and active merchants can access the dashboard;
10. suspended merchants cannot access with an old session;
11. dashboard can only read the authenticated merchant's data;
12. logout clears the merchant cookie;
13. existing voucher, merchant-finance, Salla, Jood, and WhatsLoop regression tests remain unchanged.
