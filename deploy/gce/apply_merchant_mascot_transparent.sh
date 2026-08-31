#!/usr/bin/env bash
set -u

REPO=/opt/pakgat-voucher-system
SERVICE=pakgat-voucher
TARGET=8400051b831ece80dfdbc6f42ffcd61a7e28fffe
FILE=app/merchant_onboarding_brand_assets.py
LIVE="$REPO/$FILE"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="/tmp/merchant-onboarding-brand-assets-before-transparent-mascot-$STAMP.py"
NEW_MASCOT="4c3a03f5-13ce-4309-ac36-a0b4fb850631-original.webp"
OLD_MASCOT="c939a862-0e1d-461b-ae95-7cad2dc9202a-original.webp"
LOGO="d2d7a36c-08de-4b6b-a8be-80490dbc0fc8-original.webp"
NAFATH="34e46b26-5825-429a-8567-c29175cbeb44-original.webp"

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
  fail "failed to install transparent mascot asset file"
}

chown pakgat:pakgat "$LIVE" || {
  rollback
  fail "chown failed"
}

sudo -u pakgat "$REPO/.venv/bin/python" -m py_compile "$LIVE" || {
  rollback
  fail "brand asset file compile failed"
}

grep -q "$NEW_MASCOT" "$LIVE" || {
  rollback
  fail "transparent mascot URL is missing from installed file"
}

if grep -q "$OLD_MASCOT" "$LIVE"; then
  rollback
  fail "old mascot URL is still present"
fi

if grep -q 'mix-blend-mode' "$LIVE"; then
  rollback
  fail "old mascot blend CSS is still present"
fi

echo "MERCHANT_TRANSPARENT_MASCOT_FILE_OK"

systemctl restart "$SERVICE" || {
  rollback
  fail "service restart failed"
}

READY=0
for _ in {1..20}; do
  if systemctl is-active --quiet "$SERVICE"; then
    PAGE="$(curl -fsS http://127.0.0.1:8000/merchant/register 2>/dev/null || true)"
    if grep -q "$NEW_MASCOT" <<<"$PAGE" \
      && grep -q "$LOGO" <<<"$PAGE" \
      && grep -q "$NAFATH" <<<"$PAGE" \
      && ! grep -q 'mix-blend-mode' <<<"$PAGE"; then
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
  fail "transparent mascot verification failed"
fi

echo "MERCHANT_TRANSPARENT_MASCOT_DEPLOY_OK"
echo "BACKUP=$BACKUP"
echo "CHANGED_ONLY=$FILE"
echo "PUBLIC_REGISTER=https://merchant.pakgat.com/merchant/register"
