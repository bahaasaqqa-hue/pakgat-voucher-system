#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/pakgat-voucher-system"

if [ ! -d "$APP_DIR/.git" ]; then
  echo "ERROR: $APP_DIR is missing. Deploy the voucher system first." >&2
  exit 1
fi

sudo -u pakgat git -C "$APP_DIR" fetch origin
sudo -u pakgat git -C "$APP_DIR" checkout gce-migration
sudo -u pakgat git -C "$APP_DIR" pull --ff-only origin gce-migration

install -m 0644 "$APP_DIR/deploy/gce/pakgat-ai-monitor.service" /etc/systemd/system/pakgat-ai-monitor.service
install -m 0644 "$APP_DIR/deploy/gce/pakgat-ai-monitor.timer" /etc/systemd/system/pakgat-ai-monitor.timer
install -m 0750 "$APP_DIR/deploy/gce/pakgat-db-backup.sh" "$APP_DIR/deploy/gce/pakgat-db-backup.sh"
install -m 0644 "$APP_DIR/deploy/gce/pakgat-db-backup.service" /etc/systemd/system/pakgat-db-backup.service
install -m 0644 "$APP_DIR/deploy/gce/pakgat-db-backup.timer" /etc/systemd/system/pakgat-db-backup.timer

systemctl daemon-reload
systemctl restart pakgat-voucher
systemctl enable --now pakgat-ai-monitor.timer
systemctl enable --now pakgat-db-backup.timer

# Allow the application a little time to import all AI Company modules and create tables.
for _ in $(seq 1 15); do
  if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

curl -fsS http://127.0.0.1:8000/health >/dev/null
curl -fsS http://127.0.0.1:8000/company/health
printf '\n'
systemctl --no-pager --full status pakgat-ai-monitor.timer | sed -n '1,10p'
systemctl --no-pager --full status pakgat-db-backup.timer | sed -n '1,10p'

echo
printf '%s\n' 'Pakgat AI Company GCE installation completed.'
printf '%s\n' 'Dashboard: https://voucher.pakgat.com/admin/company'
printf '%s\n' 'Systems: https://voucher.pakgat.com/admin/company/systems'
printf '%s\n' 'Health: https://voucher.pakgat.com/company/health'
