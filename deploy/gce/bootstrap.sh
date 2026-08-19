#!/usr/bin/env bash
set -euo pipefail

APP_USER="pakgat"
APP_DIR="/opt/pakgat-voucher-system"
REPO_URL="https://github.com/bahaasaqqa-hue/pakgat-voucher-system.git"
BRANCH="gce-migration"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y \
  git nginx postgresql postgresql-contrib \
  python3 python3-venv python3-pip \
  certbot python3-certbot-nginx curl ufw

# Small e2-micro instances benefit from swap to avoid OOM during package installs/restarts.
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

if ! id -u "$APP_USER" >/dev/null 2>&1; then
  useradd --system --create-home --shell /bin/bash "$APP_USER"
fi

mkdir -p /etc/pakgat
chmod 750 /etc/pakgat

if [ ! -d "$APP_DIR/.git" ]; then
  git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
else
  git -C "$APP_DIR" fetch origin
  git -C "$APP_DIR" checkout "$BRANCH"
  git -C "$APP_DIR" pull --ff-only origin "$BRANCH"
fi

chown -R "$APP_USER:$APP_USER" "$APP_DIR"

sudo -u "$APP_USER" python3 -m venv "$APP_DIR/.venv"
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --upgrade pip wheel
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

install -m 0644 "$APP_DIR/deploy/gce/pakgat-voucher.service" /etc/systemd/system/pakgat-voucher.service
install -m 0644 "$APP_DIR/deploy/gce/nginx.conf" /etc/nginx/sites-available/pakgat-voucher
ln -sfn /etc/nginx/sites-available/pakgat-voucher /etc/nginx/sites-enabled/pakgat-voucher
rm -f /etc/nginx/sites-enabled/default

ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable

nginx -t
systemctl daemon-reload
systemctl enable nginx postgresql pakgat-voucher

echo
printf '%s\n' 'Bootstrap complete.'
printf '%s\n' 'NEXT:'
printf '%s\n' '1) Create PostgreSQL database/user.'
printf '%s\n' '2) Copy deploy/gce/pakgat.env.example to /etc/pakgat/pakgat.env and fill secrets.'
printf '%s\n' '3) systemctl start pakgat-voucher && systemctl restart nginx'
printf '%s\n' '4) Point DNS to this VM, then run certbot --nginx -d voucher.pakgat.com'
