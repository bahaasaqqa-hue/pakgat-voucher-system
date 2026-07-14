# Pakgat Voucher System

FastAPI + PostgreSQL voucher/QR system for Pakgat.

## Main URLs

- `/docs` Swagger API
- `/admin/login` Admin login
- `/admin` Admin dashboard
- `/v/{token}` Customer voucher page
- `/webhooks/salla` Salla payment webhook

## Required Render environment variables

- `DATABASE_URL` (already provided by Render database)
- `PUBLIC_BASE_URL=https://pakgat-voucher-system.onrender.com`
- `ADMIN_USERNAME=admin` (or another username)
- `ADMIN_PASSWORD=<strong password>`
- `ADMIN_SECRET=<long random secret>`
- `MERCHANT_CODES={"Pakgat":"123456","*":"123456"}`
- `SALLA_WEBHOOK_SECRET=<Salla webhook secret>`
- `VOUCHER_PRODUCT_IDS=782332771` (comma-separated)
- `DEFAULT_VALIDITY_DAYS=7`

Optional email variables:

- `SMTP_HOST`
- `SMTP_PORT=587`
- `SMTP_USER`
- `SMTP_PASSWORD`
- `SMTP_FROM`

## Run locally

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```
