#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/pakgat-voucher-system"
REF="${1:-origin/feat/jood-company-ai-omnichannel}"
VERIFY_DIR="/tmp/pakgat-jood-verify-$$"
VENV_PY="$APP_DIR/.venv/bin/python"

cleanup() {
  if [ -d "$VERIFY_DIR" ]; then
    sudo -u pakgat git -C "$APP_DIR" worktree remove --force "$VERIFY_DIR" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

if [ ! -x "$VENV_PY" ]; then
  echo "ERROR: production virtualenv Python not found" >&2
  exit 1
fi
if [ ! -r /etc/pakgat/pakgat.env ]; then
  echo "ERROR: /etc/pakgat/pakgat.env is not readable" >&2
  exit 1
fi

sudo -u pakgat git -C "$APP_DIR" fetch origin
sudo -u pakgat git -C "$APP_DIR" worktree add --detach "$VERIFY_DIR" "$REF" >/dev/null

set -a
# shellcheck disable=SC1091
source /etc/pakgat/pakgat.env
set +a

cd "$VERIFY_DIR"

echo "[1/4] Python compile"
sudo -u pakgat env PYTHONPATH="$VERIFY_DIR" \
  "$VENV_PY" -m py_compile \
  "$VERIFY_DIR/main.py" \
  "$VERIFY_DIR"/app/jood*.py \
  "$VERIFY_DIR"/app/whatsloop_inbound*.py \
  "$VERIFY_DIR/app/whatsloop_security.py"

echo "[2/4] Full application import"
sudo -u pakgat env \
  PYTHONPATH="$VERIFY_DIR" \
  DATABASE_URL="$DATABASE_URL" \
  ADMIN_PASSWORD="${ADMIN_PASSWORD:-}" \
  ADMIN_SECRET="${ADMIN_SECRET:-}" \
  PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-${BASE_URL:-https://voucher.pakgat.com}}" \
  WHATSLOOP_API_BASE_URL="${WHATSLOOP_API_BASE_URL:-}" \
  WHATSLOOP_API_TOKEN="${WHATSLOOP_API_TOKEN:-}" \
  "$VENV_PY" -c 'import main; print("APP_IMPORT_OK routes=" + str(len(main.app.routes)))'

echo "[3/4] Jood regression tests"
sudo -u pakgat env \
  PYTHONPATH="$VERIFY_DIR" \
  DATABASE_URL="$DATABASE_URL" \
  ADMIN_PASSWORD="${ADMIN_PASSWORD:-}" \
  ADMIN_SECRET="${ADMIN_SECRET:-}" \
  PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-${BASE_URL:-https://voucher.pakgat.com}}" \
  WHATSLOOP_API_BASE_URL="${WHATSLOOP_API_BASE_URL:-}" \
  WHATSLOOP_API_TOKEN="${WHATSLOOP_API_TOKEN:-}" \
  "$VENV_PY" -m unittest discover -s tests -p 'test_jood_*.py' -v

echo "[4/4] Safety diff"
if sudo -u pakgat git -C "$VERIFY_DIR" diff --name-only "origin/gce-migration...HEAD" | grep -Eq '^(app/application\.py|app/gce_entry\.py|deploy/gce/pakgat-db-backup\.sh)$'; then
  echo "ERROR: protected voucher/backup files changed" >&2
  sudo -u pakgat git -C "$VERIFY_DIR" diff --name-only "origin/gce-migration...HEAD"
  exit 1
fi

echo "JOOD_FEATURE_VERIFY=PASS"
