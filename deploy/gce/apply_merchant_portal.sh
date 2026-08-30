#!/usr/bin/env bash
set -euo pipefail

REPO=/opt/pakgat-voucher-system
ENV_FILE=/etc/pakgat/pakgat.env
SERVICE=pakgat-voucher
BRANCH=gce-migration

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "Run this script as root." >&2
  exit 1
fi

if [[ ! -d "$REPO/.git" ]]; then
  echo "Repository not found at $REPO" >&2
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Environment file not found at $ENV_FILE" >&2
  exit 1
fi

command -v openssl >/dev/null 2>&1 || {
  echo "openssl is required to generate MERCHANT_PORTAL_SECRET" >&2
  exit 1
}

umask 077

# Pull only a fast-forward update so deployment never rewrites server history.
sudo -u pakgat git -C "$REPO" fetch origin "$BRANCH"
sudo -u pakgat git -C "$REPO" checkout "$BRANCH"
sudo -u pakgat git -C "$REPO" pull --ff-only origin "$BRANCH"

# Add the dedicated portal secret once and preserve it on later deployments.
if ! grep -Eq '^MERCHANT_PORTAL_SECRET=.+$' "$ENV_FILE"; then
  SECRET="$(openssl rand -hex 32)"
  printf '\nMERCHANT_PORTAL_SECRET=%s\n' "$SECRET" >> "$ENV_FILE"
fi
chmod 600 "$ENV_FILE"
chown root:root "$ENV_FILE"

# Keep dependencies current, then restart the existing production service.
sudo -u pakgat "$REPO/.venv/bin/pip" install -r "$REPO/requirements.txt"
systemctl restart "$SERVICE"

for _ in {1..15}; do
  if systemctl is-active --quiet "$SERVICE" && curl -fsS http://127.0.0.1:8000/merchant | grep -q 'بوابة شركاء Pakgat'; then
    break
  fi
  sleep 1
done

systemctl is-active --quiet "$SERVICE" || {
  systemctl status "$SERVICE" --no-pager || true
  exit 1
}

curl -fsS http://127.0.0.1:8000/merchant | grep -q 'بوابة شركاء Pakgat' || {
  echo "Merchant portal local health check failed." >&2
  journalctl -u "$SERVICE" -n 80 --no-pager || true
  exit 1
}

echo "MERCHANT_PORTAL_DEPLOY_OK"
echo "COMMIT=$(sudo -u pakgat git -C "$REPO" rev-parse HEAD)"
echo "LOCAL_URL=http://127.0.0.1:8000/merchant"
