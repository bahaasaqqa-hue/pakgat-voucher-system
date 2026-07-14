# Pakgat Voucher System v4.0

FastAPI voucher and QR service for Pakgat with Salla OAuth, automatic voucher creation, email delivery, and multi-merchant configuration.

## Included

- Voucher creation, verification, QR, expiry, and atomic redemption
- PostgreSQL persistence and audit log
- Admin dashboard, search, filters, pagination, and manual voucher creation
- Salla OAuth authorization-code connection flow
- Encrypted storage of Salla access and refresh tokens
- Multi-merchant product IDs, merchant redemption code, and email preference
- Automatic voucher creation from paid Salla order webhooks
- Automatic email delivery when SMTP is configured
- Legacy single-store environment variables remain supported as fallback

## Render start command

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

## Required environment variables

- `DATABASE_URL`
- `PUBLIC_BASE_URL=https://pakgat-voucher-system.onrender.com`
- `ADMIN_USERNAME`
- `ADMIN_PASSWORD`
- `ADMIN_SECRET` (do not change after OAuth tokens are stored, because it encrypts them)
- `SALLA_CLIENT_ID`
- `SALLA_CLIENT_SECRET`
- `SALLA_WEBHOOK_SECRET`

## Salla OAuth variables

Defaults are included but can be overridden:

- `SALLA_AUTHORIZE_URL=https://accounts.salla.sa/oauth2/auth`
- `SALLA_TOKEN_URL=https://accounts.salla.sa/oauth2/token`
- `SALLA_API_BASE=https://api.salla.dev/admin/v2`
- `SALLA_REDIRECT_URI=https://pakgat-voucher-system.onrender.com/oauth/salla/callback`
- `SALLA_OAUTH_SCOPES=offline_access`

Register the exact redirect URI in the Salla application settings.

## Optional fallback variables

These keep the original single-store setup working until all merchants are connected through OAuth:

- `VOUCHER_PRODUCT_IDS` (comma-separated product IDs)
- `MERCHANT_CODES` (JSON, e.g. `{"Pakgat":"1234","*":"9999"}`)
- `DEFAULT_VALIDITY_DAYS=7`
- `COOKIE_SECURE=true`

## Email variables

- `SMTP_HOST`
- `SMTP_PORT` (default `587`)
- `SMTP_USER`
- `SMTP_PASSWORD`
- `SMTP_FROM`

## Admin workflow

1. Open `/admin/integrations`.
2. Choose **ربط متجر جديد**.
3. Approve the Salla OAuth request.
4. Open `/admin/merchants` and configure the merchant's voucher product IDs and redemption code.
5. Configure Salla to send paid-order webhooks to `/webhooks/salla`.

## Database migration

On startup, v4.0 automatically:

- Creates the `merchant_connections` table.
- Adds nullable `merchant_id` and `customer_email` columns to existing vouchers.
- Preserves all existing voucher and audit data.
