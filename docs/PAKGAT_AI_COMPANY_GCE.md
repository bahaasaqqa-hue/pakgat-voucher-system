# Pakgat AI Company — Google Compute Engine V1

Render is not part of the production architecture.

## Production layout

- Google Compute Engine: application runtime, CEO dashboard, Data Hub, monitoring worker.
- PostgreSQL on the Google VM: Voucher System data plus logically separated Pakgat AI Company tables.
- Nginx + Let's Encrypt: HTTPS reverse proxy.
- GitHub: source control and deployment history only.
- Salla: commerce/order event source.
- WhatsLoop: paid WhatsApp delivery provider.

## Services

- `pakgat-voucher.service`: FastAPI/Uvicorn production app.
- `pakgat-ai-monitor.timer`: runs the internal Pakgat AI monitor every five minutes.
- `pakgat-ai-monitor.service`: records health snapshots and internal alerts.

## URLs

- Voucher/admin: `https://voucher.pakgat.com/admin`
- Pakgat AI Company Control Center: `https://voucher.pakgat.com/admin/company`
- Voucher health: `https://voucher.pakgat.com/health`
- AI Company health: `https://voucher.pakgat.com/company/health`

## Data Hub V1 tables

- `company_metric_snapshots`
- `company_alerts`
- `company_tasks`

The existing voucher, Salla integration, WhatsLoop and local-partner tables remain in the same PostgreSQL instance for V1, as allowed by the Blueprint, while staying logically separated.

## Deployment

Run on the Google VM:

```bash
cd /opt/pakgat-voucher-system
sudo bash deploy/gce/install-ai-company.sh
```

The installer pulls `gce-migration`, restarts the app, installs/enables the monitor timer, verifies local health and prints the Control Center URL.

## Render retirement

Do not configure new Render services, databases, health checks or webhooks. Existing Render resources can be deleted after Salla production webhook publishing is confirmed on the Google URL and the final production smoke check passes.
