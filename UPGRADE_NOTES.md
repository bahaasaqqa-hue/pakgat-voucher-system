# Pakgat Voucher System 3.0

## Included in this release

- Admin dashboard with totals, search, status filters, and pagination.
- Voucher creation, verification QR, merchant/admin redemption, and duplicate-use protection.
- Audit log with Arabic action labels.
- Salla integration status page.
- Salla webhook logging for received, ignored, and completed events.
- Fixed SMTP readiness check to use `SMTP_USER`, matching the mail sender.
- Added administration security readiness check for `ADMIN_PASSWORD` and `ADMIN_SECRET`.
- Automatic audit entry when a voucher is created.
- Render-compatible `main.py` entry point retained.

## Required Render variables

- `DATABASE_URL`
- `PUBLIC_BASE_URL=https://pakgat-voucher-system.onrender.com`
- `ADMIN_USERNAME`
- `ADMIN_PASSWORD`
- `ADMIN_SECRET`
- `COOKIE_SECURE=true`
- `SALLA_WEBHOOK_SECRET`
- `VOUCHER_PRODUCT_IDS`
- `DEFAULT_VALIDITY_DAYS=7`

Optional email variables:

- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USER`
- `SMTP_PASSWORD`
- `SMTP_FROM`
