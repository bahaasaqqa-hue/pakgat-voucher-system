# Pakgat Voucher System v3.0

FastAPI voucher and QR service for Pakgat.

## Included
- Voucher creation, verification, QR and atomic redemption
- PostgreSQL persistence
- Admin dashboard and manual voucher creation
- Audit log at `/admin/audit`
- Salla readiness page at `/admin/integrations`
- Salla webhook at `/webhooks/salla`
- Customer and merchant terms

## Render start command
```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

## Required environment variables
- `DATABASE_URL`
- `PUBLIC_BASE_URL`
- `ADMIN_USERNAME`
- `ADMIN_PASSWORD`
- `ADMIN_SECRET`
- `SALLA_WEBHOOK_SECRET`
- `VOUCHER_PRODUCT_IDS` (comma-separated Salla product IDs)
- `MERCHANT_CODES` (JSON, e.g. `{"Pakgat":"1234","*":"9999"}`)

## Optional email variables
- `SMTP_HOST`
- `SMTP_PORT` (default `587`)
- `SMTP_USER`
- `SMTP_PASSWORD`
- `SMTP_FROM`
- `SMTP_USE_TLS` (default `true`)


## v3.0 changes
- Dashboard pagination (25 vouchers per page)
- Audit logging for API/admin/Salla voucher creation
- Salla webhook rejection and ignore logging
- Correct SMTP readiness check (`SMTP_USER`)
- No hard-coded default Salla product ID
