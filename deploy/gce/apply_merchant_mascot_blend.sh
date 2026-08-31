#!/usr/bin/env bash
set -u

REPO=/opt/pakgat-voucher-system
SERVICE=pakgat-voucher
TARGET=e3fb51ab69dc56b5707a0d2fa679f4eb066c753e
FILE=app/merchant_onboarding_brand_assets.py
LIVE="$REPO/$FILE"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="/tmp/merchant-onboarding-brand-assets-before-blend-$STAMP.py"
MASCOT="c939a862-0e1d-461b-ae95-7cad2dc9202a-original.webp"

fail() {
  echo "DEPLOY_FAILED: $*" >&2
  exit 1
}

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  fail "Run as root"
fi

[[ -d "$REPO/.git" ]] || fail "Repository not found: $REPO"
[[ -f "$LIVE" ]] || fail "Brand asset file not found: $LIVE"
command -v curl >/dev/null 2>&1 || fail "curl is required"

cp -a "$LIVE" "$BACKUP" || fail "Could not create backup"

rollback() {
  echo "ROLLBACK_START"
  cp -a "$BACKUP" "$LIVE" 2>/dev/null || true
  chown pakgat:pakgat "$LIVE" 2>/dev/null || true
  systemctl restart "$SERVICE" >/dev/null 2>&1 || true
  echo "ROLLBACK_DONE"
}

sudo -u pakgat git -C "$REPO" fetch origin gce-migration || {
  rollback
  fail "git fetch failed"
}

sudo -u pakgat git -C "$REPO" cat-file -e "$TARGET^{commit}" || {
  rollback
  fail "target commit is unavailable"
}

sudo -u pakgat git -C "$REPO" show "$TARGET:$FILE" > "$LIVE" || {
  rollback
  fail "failed to install mascot blend file"
}

chown pakgat:pakgat "$LIVE" || {
  rollback
  fail "chown failed"
}

sudo -u pakgat "$REPO/.venv/bin/python" -m py_compile "$LIVE" || {
  rollback
  fail "brand asset file compile failed"
}

grep -q 'mix-blend-mode:multiply' "$LIVE" || {
  rollback
  fail "mascot blend CSS is missing from installed file"
}

grep -q "$MASCOT" "$LIVE" || {
  rollback
  fail "mascot URL is missing from installed file"
}

echo "MERCHANT_MASCOT_BLEND_FILE_OK"

systemctl restart "$SERVICE" || {
  rollback
  fail "service restart failed"
}

READY=0
for _ in {1..20}; do
  if systemctl is-active --quiet "$SERVICE"; then
    PAGE="$(curl -fsS http://127.0.0.1:8000/merchant/register 2>/dev/null || true)"
    if grep -q "$MASCOT" <<<"$PAGE" \
      && grep -q 'mix-blend-mode:multiply' <<<"$PAGE"; then
      READY=1
      break
    fi
  fi
  sleep 1
done

if [[ "$READY" -ne 1 ]]; then
  systemctl status "$SERVICE" --no-pager || true
  journalctl -u "$SERVICE" -n 60 --no-pager || true
  rollback
  fail "merchant mascot blend verification failed"
fi

echo "MERCHANT_MASCOT_BLEND_DEPLOY_OK"
echo "BACKUP=$BACKUP"
echo "CHANGED_ONLY=$FILE"
echo "PUBLIC_REGISTER=https://merchant.pakgat.com/merchant/register"
