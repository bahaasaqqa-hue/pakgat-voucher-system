# Pakgat Voucher System — Always-On VM Deployment

This deployment keeps the current Pakgat FastAPI application running continuously with systemd, Nginx, and a local PostgreSQL database.

## Target VM

Recommended baseline:
- Ubuntu 24.04 LTS
- 1 GB RAM minimum (the bootstrap script adds 2 GB swap)
- 20–30 GB persistent disk
- One stable hostname: `voucher.pakgat.com`

> The application remains bound to `127.0.0.1:8000`; only Nginx or a secure tunnel should expose it publicly.

## 1. Bootstrap the VM

```bash
sudo -i
apt-get update && apt-get install -y git
git clone --branch gce-migration https://github.com/bahaasaqqa-hue/pakgat-voucher-system.git /opt/pakgat-voucher-system
bash /opt/pakgat-voucher-system/deploy/gce/bootstrap.sh
```

## 2. Create PostgreSQL database and user

Choose a strong random password and replace `CHANGE_DB_PASSWORD` below.

```bash
sudo -u postgres psql
```

Then run:

```sql
CREATE USER pakgat WITH PASSWORD 'CHANGE_DB_PASSWORD';
CREATE DATABASE pakgat_voucher OWNER pakgat;
\q
```

Do not expose PostgreSQL port 5432 to the public internet.

## 3. Configure environment

```bash
sudo cp /opt/pakgat-voucher-system/deploy/gce/pakgat.env.example /etc/pakgat/pakgat.env
sudo nano /etc/pakgat/pakgat.env
sudo chmod 600 /etc/pakgat/pakgat.env
sudo chown root:root /etc/pakgat/pakgat.env
```

Copy the existing production values from Render for Salla, admin, WhatsLoop and SMTP secrets. Keep `ADMIN_SECRET` unchanged if it is already used by production.

Set:

```text
PUBLIC_BASE_URL=https://voucher.pakgat.com
DATABASE_URL=postgresql://pakgat:<DB_PASSWORD>@127.0.0.1:5432/pakgat_voucher
```

## 4. Start and verify locally

```bash
sudo systemctl start pakgat-voucher
sudo systemctl restart nginx
sudo systemctl status pakgat-voucher --no-pager
curl -I http://127.0.0.1:8000/
```

Logs:

```bash
journalctl -u pakgat-voucher -f
```

The service uses `Restart=always`, so it restarts after application crashes and starts automatically after a VM reboot.

## 5. Public hostname and HTTPS

Point `voucher.pakgat.com` to the selected ingress method. If using a public IPv4 on the VM, enable HTTP/HTTPS and then run:

```bash
sudo certbot --nginx -d voucher.pakgat.com
```

If using Cloudflare Tunnel, keep inbound ports closed and publish `voucher.pakgat.com` to `http://127.0.0.1:8000` through the tunnel instead of exposing the VM directly.

## 6. Salla cutover — only after testing

Do not remove the current Render endpoints until the new VM passes tests.

After the new hostname is confirmed:
1. Update the Pakgat/Salla webhook target to `https://voucher.pakgat.com/webhooks/salla`.
2. If the OAuth callback uses the public base URL, update the Salla app callback to the new hostname.
3. Run one test voucher purchase.
4. Verify voucher creation, QR opening, merchant redemption, WhatsApp notification, and audit logging.
5. Keep Render unchanged for rollback until the new deployment has been stable.

## 7. Database migration from Render (if the old DB becomes accessible)

Export:

```bash
pg_dump "$OLD_RENDER_DATABASE_URL" -Fc -f pakgat-render.dump
```

Restore on the VM:

```bash
pg_restore --clean --if-exists --no-owner -d "postgresql://pakgat:<DB_PASSWORD>@127.0.0.1:5432/pakgat_voucher" pakgat-render.dump
sudo systemctl restart pakgat-voucher
```

Never commit database dumps or `.env` files to GitHub.

## 8. Updating later

```bash
cd /opt/pakgat-voucher-system
git fetch origin
git pull --ff-only origin gce-migration
.venv/bin/pip install -r requirements.txt
sudo systemctl restart pakgat-voucher
```
# Customer notification outbox

The application creates `customer_notifications` rows atomically with voucher issuance and redemption. Verify this first on staging. Install the service and timer files only after a simulated failed WhatsLoop delivery remains retryable and a later run marks it sent.

```bash
sudo install -m 0644 deploy/gce/pakgat-customer-notifications.service /etc/systemd/system/
sudo install -m 0644 deploy/gce/pakgat-customer-notifications.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pakgat-customer-notifications.timer
sudo systemctl list-timers pakgat-customer-notifications.timer
```

Rollback is non-destructive: disable the timer before rolling back application code. Leave the additive table in place so delivery history is retained.

```bash
sudo systemctl disable --now pakgat-customer-notifications.timer
```
