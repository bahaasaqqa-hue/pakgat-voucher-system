# Pakgat Theme V3 — Corporate Benefits UI Contract

## Homepage CTA

Primary copy:

**فعّل مزايا شركتك**

Supporting copy:

`سجّل دخولك ببكجات وأضف بريدك الوظيفي للاستفادة من مزايا وعروض جهة عملك.`

Button:

**تفعيل المزايا**

The banner/section must open the Corporate activation experience inside Pakgat Theme V3. Do not send the employee to a separate Google authentication form.

## Activation experience

### State 1 — visitor is not logged in

Use Salla's storefront login flow/component. Salla owns mobile authentication and OTP.

UI:

- Heading: `فعّل مزايا شركتك`
- Text: `سجّل دخولك أولًا برقم الجوال المسجل في بكجات.`
- Action: open Salla login.

### State 2 — logged in, corporate email not submitted

Show the current Salla customer mobile as an account identity indicator, not as a second verification field.

UI:

- `رقم الجوال: مسجل في حسابك ✓`
- Input: `البريد الوظيفي`
- Example: `name@company.com`
- Button: `إرسال رمز التحقق`

Submission must use the Salla storefront profile/contact update mechanism so Salla owns the email change and verification state.

### State 3 — Salla says email verification is pending

Open/use Salla's email verification component/modal (`salla-verify`, email type) and let Salla send/validate the OTP.

Google must not receive, generate or validate the OTP.

### State 4 — Salla verification succeeds

Show:

`تم التحقق من بريدك الوظيفي ✅`

`سيتم تفعيل مزايا جهة عملك تلقائيًا عند مطابقة نطاق الشركة.`

The Google backend receives the resulting `customer.updated` event, fetches Salla Customer Details, maps the email domain and syncs the Customer Group.

### State 5 — domain is not enrolled

Google will ignore the customer for automatic company assignment. The storefront can display a neutral message such as:

`جهة عملك غير مضافة حاليًا إلى برنامج مزايا بكجات.`

Do not expose internal company/domain tables or system errors to the employee.

## Salla components / APIs to use

- Salla storefront login component for customer login/mobile OTP.
- Salla profile/contact update for the email change.
- Salla verify component/modal with email verification for the OTP step.
- `customer.updated` as the backend trigger after customer profile/contact update.

## Google backend contract

Prepared endpoint:

`POST /webhooks/salla-corporate`

Expected event:

`customer.updated`

Security:

`X-Salla-Signature` verified with HMAC-SHA256 using the configured webhook secret.

Processing:

1. Read customer ID from event.
2. Fetch `/customers/{customer}` from Salla Merchant API.
3. Read current Salla profile email/mobile.
4. Match email domain to `corporate_company_domains`.
5. Upsert `corporate_members` using Salla Customer ID.
6. When live mode is enabled, ensure the company Salla Customer Group exists.
7. Add the customer to the group.
8. Keep failed writes as `verified_pending_sync` for safe retry.

## Launch flags

Keep:

`CORPORATE_SALLA_PROFILE_MODE=true`

Keep until E2E test passes:

`CORPORATE_LIVE=false`

Then enable:

`CORPORATE_LIVE=true`

## Do not implement

- Google OTP for mobile.
- Google/SMTP OTP for corporate email.
- Second Corporate account/password.
- Asking the logged-in customer to re-enter the mobile number.
- Direct Corporate activation based only on an unverified form email.
