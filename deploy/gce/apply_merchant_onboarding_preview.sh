#!/usr/bin/env bash
set -u

REPO=/opt/pakgat-voucher-system
SERVICE=pakgat-voucher
TARGET=fc44fbab04cc7762cbfab98455544f4916c97653
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="/tmp/pakgat-merchant-onboarding-preview-$STAMP"

fail() {
  echo "DEPLOY_FAILED: $*" >&2
  exit 1
}

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  fail "Run as root"
fi

[[ -d "$REPO/.git" ]] || fail "Repository not found: $REPO"
command -v curl >/dev/null 2>&1 || fail "curl is required"

mkdir -p "$BACKUP"

FILES=(
  app/merchant_contract_admin_actions.py
  app/merchant_contracts.py
  app/merchant_onboarding.py
  app/merchant_onboarding_ui.py
  main.py
)

for f in "${FILES[@]}"; do
  if [[ -e "$REPO/$f" ]]; then
    mkdir -p "$BACKUP/$(dirname "$f")"
    cp -a "$REPO/$f" "$BACKUP/$f"
  else
    mkdir -p "$BACKUP/$(dirname "$f")"
    : > "$BACKUP/$f.absent"
  fi
done

rollback() {
  echo "ROLLBACK_START"
  for f in "${FILES[@]}"; do
    if [[ -e "$BACKUP/$f.absent" ]]; then
      rm -f "$REPO/$f"
    elif [[ -e "$BACKUP/$f" ]]; then
      cp -a "$BACKUP/$f" "$REPO/$f"
    fi
  done
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

for f in app/merchant_contract_admin_actions.py app/merchant_contracts.py app/merchant_onboarding.py app/merchant_onboarding_ui.py; do
  mkdir -p "$REPO/$(dirname "$f")"
  sudo -u pakgat git -C "$REPO" show "$TARGET:$f" > "$REPO/$f" || {
    rollback
    fail "failed to materialize $f"
  }
done

python3 - "$REPO/main.py" <<'PY' || {
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")

contract_anchor = "from app import merchant_contracts as _merchant_contracts  # noqa: F401 - Sadq merchant contract lifecycle and delivery audit\n_merchant_contracts.ensure_merchant_contract_schema()\n"
contract_insert = contract_anchor + "from app import merchant_contract_admin_actions as _merchant_contract_admin_actions  # noqa: F401 - post-Sadq merchant review actions\n_merchant_contracts.merchant_contract_summary_html = _merchant_contract_admin_actions.merchant_contract_summary_html\n"
if "merchant_contract_admin_actions as _merchant_contract_admin_actions" not in text:
    if contract_anchor not in text:
        raise SystemExit("merchant contract anchor not found in main.py")
    text = text.replace(contract_anchor, contract_insert, 1)

portal_anchor = "from app import merchant_portal as _merchant_portal  # noqa: F401 - public merchant WhatsApp OTP portal\n_merchant_portal.ensure_merchant_portal_schema()\n"
onboarding_insert = portal_anchor + "from app import merchant_onboarding as _merchant_onboarding  # noqa: F401 - self-service merchant registration, documents and review lifecycle\n_merchant_onboarding.ensure_merchant_onboarding_schema()\n"
if "merchant_onboarding as _merchant_onboarding" not in text:
    if portal_anchor not in text:
        raise SystemExit("merchant portal anchor not found in main.py")
    text = text.replace(portal_anchor, onboarding_insert, 1)

ui_anchor = "from app import merchant_onboarding as _merchant_onboarding  # noqa: F401 - self-service merchant registration, documents and review lifecycle\n_merchant_onboarding.ensure_merchant_onboarding_schema()\n"
ui_insert = ui_anchor + "from app import merchant_onboarding_ui as _merchant_onboarding_ui  # noqa: F401 - friendly partner registration presentation\n"
if "merchant_onboarding_ui as _merchant_onboarding_ui" not in text:
    if ui_anchor not in text:
        raise SystemExit("merchant onboarding anchor not found in main.py")
    text = text.replace(ui_anchor, ui_insert, 1)

# Preview release intentionally does NOT register the global Sadq bridge.
text = text.replace("from app import merchant_onboarding_sadq_bridge as _merchant_onboarding_sadq_bridge  # noqa: F401 - signed Sadq contracts become pending Pakgat review\n", "")

path.write_text(text, encoding="utf-8")
PY
  rollback
  fail "main.py patch failed"
}

chown pakgat:pakgat \
  "$REPO/app/merchant_contract_admin_actions.py" \
  "$REPO/app/merchant_contracts.py" \
  "$REPO/app/merchant_onboarding.py" \
  "$REPO/app/merchant_onboarding_ui.py" \
  "$REPO/main.py" || {
  rollback
  fail "chown failed"
}

install -d -m 0750 -o pakgat -g pakgat /var/lib/pakgat/merchant-documents || {
  rollback
  fail "document directory setup failed"
}

sudo -u pakgat "$REPO/.venv/bin/python" -m compileall -q \
  "$REPO/main.py" \
  "$REPO/app/merchant_contract_admin_actions.py" \
  "$REPO/app/merchant_contracts.py" \
  "$REPO/app/merchant_onboarding.py" \
  "$REPO/app/merchant_onboarding_ui.py" || {
  rollback
  fail "compile failed"
}

systemctl restart "$SERVICE" || {
  rollback
  fail "service restart failed"
}

READY=0
for _ in {1..20}; do
  if systemctl is-active --quiet "$SERVICE"; then
    PAGE="$(curl -fsS http://127.0.0.1:8000/merchant/register 2>/dev/null || true)"
    if grep -q 'عقد الشراكة مع بكجات' <<<"$PAGE" && grep -q 'التحقق عبر نفاذ' <<<"$PAGE"; then
      READY=1
      break
    fi
  fi
  sleep 1
done

if [[ "$READY" -ne 1 ]]; then
  systemctl status "$SERVICE" --no-pager || true
  journalctl -u "$SERVICE" -n 80 --no-pager || true
  rollback
  fail "merchant onboarding health check failed"
fi

curl -fsS http://127.0.0.1:8000/merchant 2>/dev/null | grep -q 'Pakgat' || {
  rollback
  fail "existing merchant portal health check failed"
}

echo "MERCHANT_ONBOARDING_UI_DEPLOY_OK"
echo "BACKUP=$BACKUP"
echo "LOCAL_REGISTER=http://127.0.0.1:8000/merchant/register"
echo "PUBLIC_REGISTER=https://merchant.pakgat.com/merchant/register"
