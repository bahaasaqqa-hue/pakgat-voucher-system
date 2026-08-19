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

systemctl daemon-reload
systemctl restart pakgat-voucher
systemctl enable --now pakgat-ai-monitor.timer

sleep 3
curl -fsS http://127.0.0.1:8000/health >/dev/null
curl -fsS http://127.0.0.1:8000/company/health
printf '\n'
systemctl --no-pager --full status pakgat-ai-monitor.timer | sed -n '1,12p'

echo
printf '%s\n' 'Pakgat AI Company GCE installation completed.'
printf '%s\n' 'Dashboard: https://voucher.pakgat.com/admin/company'
printf '%s\n' 'Health: https://voucher.pakgat.com/company/health'
