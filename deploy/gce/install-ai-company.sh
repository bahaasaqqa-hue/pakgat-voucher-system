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

# Ensure the approved Jood voice runtime is available before import/restart.
sudo -u pakgat "$APP_DIR/.venv/bin/pip" install --disable-pip-version-check -q "edge-tts==7.2.8"

# Safety gate: do not restart the live voucher service if a newly added AI,
# Corporate Benefits, Jood, WhatsLoop, or Salla integration module has a Python syntax error.
sudo -u pakgat "$APP_DIR/.venv/bin/python" -m py_compile \
  "$APP_DIR/main.py" \
  "$APP_DIR/app/salla_products_read_only.py" \
  "$APP_DIR"/app/ai_company*.py \
  "$APP_DIR"/app/corporate*.py \
  "$APP_DIR"/app/jood*.py \
  "$APP_DIR"/app/whatsloop_inbound*.py \
  "$APP_DIR/app/whatsloop_security.py"

# Import the fully assembled FastAPI app before touching the live service. This catches
# route/model/module registration failures that syntax compilation alone cannot detect.
(
  cd "$APP_DIR"
  sudo -u pakgat env PYTHONPATH=. "$APP_DIR/.venv/bin/python" -c \
    'import main; print("Jood app import OK; routes=" + str(len(main.app.routes)))'
)

# Jood deployment gate: run every focused Jood regression test before restart.
# This covers memory, Company AI routing, URL policy, outbound WhatsApp,
# call-window/cooldown behavior, voice-session helpers and bridge behavior.
(
  cd "$APP_DIR"
  sudo -u pakgat env PYTHONPATH=. "$APP_DIR/.venv/bin/python" \
    -m unittest discover -s tests -p 'test_jood_*.py' -q
)

install -m 0644 "$APP_DIR/deploy/gce/pakgat-ai-monitor.service" /etc/systemd/system/pakgat-ai-monitor.service
install -m 0644 "$APP_DIR/deploy/gce/pakgat-ai-monitor.timer" /etc/systemd/system/pakgat-ai-monitor.timer
chmod 0750 "$APP_DIR/deploy/gce/pakgat-db-backup.sh"
install -m 0644 "$APP_DIR/deploy/gce/pakgat-db-backup.service" /etc/systemd/system/pakgat-db-backup.service
install -m 0644 "$APP_DIR/deploy/gce/pakgat-db-backup.timer" /etc/systemd/system/pakgat-db-backup.timer

systemctl daemon-reload
systemctl restart pakgat-voucher
systemctl enable --now pakgat-ai-monitor.timer
systemctl enable --now pakgat-db-backup.timer

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
printf '%s\n' 'Pakgat AI Company + Corporate Benefits GCE installation completed.'
printf '%s\n' 'Dashboard: https://voucher.pakgat.com/admin/company'
printf '%s\n' 'Jood Control: https://voucher.pakgat.com/admin/company/jood/control'
printf '%s\n' 'Jood WhatsApp Campaigns: https://voucher.pakgat.com/admin/company/jood/whatsapp-campaigns'
printf '%s\n' 'Corporate Admin: https://voucher.pakgat.com/admin/company/corporate'
printf '%s\n' 'Corporate Public: https://voucher.pakgat.com/corporate (staging path until benefits.pakgat.com DNS/TLS is enabled)'
printf '%s\n' 'Health: https://voucher.pakgat.com/company/health'
