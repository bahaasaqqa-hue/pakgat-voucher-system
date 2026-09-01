#!/usr/bin/env bash
set -u

REPO="/opt/pakgat-voucher-system"
BRANCH="feat/sadq-dynamic-auth-webhook"
PY="$REPO/.venv/bin/python"
NGINX_CONF="/etc/nginx/sites-available/pakgat-merchant"
STAMP="$(date +%Y%m%d-%H%M%S)"
STAGE="/tmp/pakgat-sadq-stage2-$STAMP"
BACKUP="/tmp/pakgat-sadq-stage2-backup-$STAMP"
MUTATED=0

FILES=(
  "app/sadq_client.py"
  "app/merchant_contract_pdf.py"
  "app/merchant_onboarding_sadq_start.py"
  "app/merchant_onboarding_sadq_bridge.py"
  "app/assets/merchant_contract_template_00.b64"
  "app/assets/merchant_contract_template_01.b64"
  "app/assets/merchant_contract_template_02.b64"
  "app/assets/merchant_contract_template_03a.b64"
  "app/assets/merchant_contract_template_03b.b64"
  "app/assets/merchant_contract_template_03c.b64"
  "app/assets/merchant_contract_template_04.b64"
  "app/assets/merchant_contract_template_05.b64"
  "app/assets/merchant_contract_template_06.b64"
  "app/assets/merchant_contract_template_07.b64"
)
TEST_FILES=(
  "tests/test_merchant_contract_pdf.py"
  "tests/test_sadq_signing_client.py"
  "tests/test_merchant_onboarding_sadq_start.py"
)
PROTECTED=(
  "app/jood_identity.py"
  "app/jood_outbound.py"
  "app/jood_policy.py"
  "app/jood_whatsapp_campaign.py"
  "app/jood_whatsapp_campaign_ui.py"
  "app/jood_whatsapp_context.py"
  "app/whatsloop_inbound.py"
  "main.py"
)

fail() {
  echo "SADQ_STAGE2_DEPLOY_FAILED: $1" >&2
  exit "${2:-1}"
}

rollback() {
  if [ "$MUTATED" -ne 1 ]; then
    return 0
  fi
  echo "SADQ_STAGE2_ROLLBACK_BEGIN"
  for path in "${FILES[@]}"; do
    if [ -f "$BACKUP/files/$path" ]; then
      mkdir -p "$REPO/$(dirname "$path")"
      cp -a "$BACKUP/files/$path" "$REPO/$path"
      chown pakgat:pakgat "$REPO/$path" 2>/dev/null || true
    elif grep -Fxq "$path" "$BACKUP/new-files.txt" 2>/dev/null; then
      rm -f "$REPO/$path"
    fi
  done
  if [ -f "$BACKUP/pakgat-merchant.nginx" ]; then
    cp -a "$BACKUP/pakgat-merchant.nginx" "$NGINX_CONF"
    nginx -t >/dev/null 2>&1 && systemctl reload nginx >/dev/null 2>&1 || true
  fi
  systemctl restart pakgat-voucher >/dev/null 2>&1 || true
  echo "SADQ_STAGE2_ROLLBACK_COMPLETE"
}

# Preflight must finish before any production mutation.
[ -d "$REPO/.git" ] || fail "repository not found"
[ -x "$PY" ] || fail "production virtualenv python not found"
[ -f "$NGINX_CONF" ] || fail "merchant nginx config not found"
if command -v libreoffice >/dev/null 2>&1; then
  CONVERTER="$(command -v libreoffice)"
elif command -v soffice >/dev/null 2>&1; then
  CONVERTER="$(command -v soffice)"
else
  fail "LibreOffice/soffice is required before enabling real agreement PDF generation" 2
fi
echo "SADQ_STAGE2_PDF_CONVERTER_OK=$CONVERTER"

rm -rf "$STAGE" "$BACKUP"
mkdir -p "$STAGE" "$BACKUP/files"
: > "$BACKUP/new-files.txt"

sudo -u pakgat git -C "$REPO" fetch origin "$BRANCH" || fail "git fetch failed"

for path in "${FILES[@]}" "${TEST_FILES[@]}"; do
  mkdir -p "$STAGE/$(dirname "$path")"
  if ! sudo -u pakgat git -C "$REPO" show "origin/$BRANCH:$path" > "$STAGE/$path"; then
    fail "could not stage $path"
  fi
done

echo "SADQ_STAGE2_SOURCE_STAGED"

# Compile staged Python before touching production.
for path in app/sadq_client.py app/merchant_contract_pdf.py app/merchant_onboarding_sadq_start.py app/merchant_onboarding_sadq_bridge.py; do
  "$PY" -m py_compile "$STAGE/$path" || fail "staged compile failed for $path"
done

echo "SADQ_STAGE2_STAGED_COMPILE_OK"

# Snapshot protected WhatsApp/Jood/main files byte-for-byte.
: > "$BACKUP/protected-before.sha256"
for path in "${PROTECTED[@]}"; do
  [ -f "$REPO/$path" ] || fail "protected file missing: $path"
  sha256sum "$REPO/$path" >> "$BACKUP/protected-before.sha256" || fail "could not hash $path"
done

# Backup only files this rollout may replace.
for path in "${FILES[@]}"; do
  if [ -f "$REPO/$path" ]; then
    mkdir -p "$BACKUP/files/$(dirname "$path")"
    cp -a "$REPO/$path" "$BACKUP/files/$path" || fail "backup failed for $path"
  else
    echo "$path" >> "$BACKUP/new-files.txt"
  fi
done
cp -a "$NGINX_CONF" "$BACKUP/pakgat-merchant.nginx" || fail "nginx backup failed"

MUTATED=1
trap 'rc=$?; if [ "$rc" -ne 0 ]; then rollback; fi' EXIT

# Apply only the explicit Sadq/onboarding files.
for path in "${FILES[@]}"; do
  mkdir -p "$REPO/$(dirname "$path")"
  cp "$STAGE/$path" "$REPO/$path" || { rollback; MUTATED=0; fail "copy failed for $path"; }
  chown pakgat:pakgat "$REPO/$path" 2>/dev/null || true
done

# Targeted regression with test-only environment; no provider calls are made.
# Run the exact staged test files so deployment validation cannot silently use stale production tests.
(
  cd "$REPO" || exit 1
  export DATABASE_URL="sqlite:///:memory:"
  export MERCHANT_PORTAL_SECRET="test-only-merchant-portal-secret"
  export ADMIN_PASSWORD="test-only-password"
  export ADMIN_SECRET="test-only-admin-secret"
  export PUBLIC_BASE_URL="https://example.test"
  export WHATSLOOP_API_BASE_URL="https://example.test/api/v1"
  export WHATSLOOP_API_TOKEN="test-only-whatsloop-token"
  export PYTHONPATH="$REPO"
  "$PY" "$STAGE/tests/test_merchant_contract_pdf.py" -v &&
  "$PY" "$STAGE/tests/test_sadq_signing_client.py" -v &&
  "$PY" "$STAGE/tests/test_merchant_onboarding_sadq_start.py" -v
)
TEST_RC=$?
if [ "$TEST_RC" -ne 0 ]; then
  rollback
  MUTATED=0
  fail "targeted tests failed and files were rolled back"
fi
echo "SADQ_STAGE2_TARGETED_TESTS_OK"

# Fix the merchant upload gateway limit. The application still enforces 10 MB per file.
"$PY" - "$NGINX_CONF" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
text = p.read_text(encoding="utf-8")
needle = "    server_name merchant.pakgat.com;\n"
pos = text.find(needle)
if pos < 0:
    raise SystemExit("merchant server_name not found")
insert_at = pos + len(needle)
server_end = text.find("\n}", insert_at)
if server_end < 0:
    raise SystemExit("merchant TLS server block end not found")
block = text[pos:server_end]
if "client_max_body_size" not in block:
    text = text[:insert_at] + "\n    client_max_body_size 50m;\n" + text[insert_at:]
p.write_text(text, encoding="utf-8")
PY
NGINX_PATCH_RC=$?
if [ "$NGINX_PATCH_RC" -ne 0 ]; then
  rollback
  MUTATED=0
  fail "could not update merchant upload limit"
fi
if ! nginx -t; then
  rollback
  MUTATED=0
  fail "nginx validation failed and rollout was rolled back"
fi
if ! systemctl reload nginx; then
  rollback
  MUTATED=0
  fail "nginx reload failed and rollout was rolled back"
fi
grep -q 'client_max_body_size 50m;' "$NGINX_CONF" || { rollback; MUTATED=0; fail "merchant upload limit verification failed"; }
echo "MERCHANT_UPLOAD_LIMIT_50M_OK"

# Protected files must remain byte-identical.
: > "$BACKUP/protected-after.sha256"
for path in "${PROTECTED[@]}"; do
  sha256sum "$REPO/$path" >> "$BACKUP/protected-after.sha256" || { rollback; MUTATED=0; fail "could not re-hash $path"; }
done
if ! cmp -s "$BACKUP/protected-before.sha256" "$BACKUP/protected-after.sha256"; then
  rollback
  MUTATED=0
  fail "protected Jood/WhatsLoop/main files changed unexpectedly"
fi
echo "PROTECTED_SETTINGS_AND_ROUTING_UNCHANGED"

if ! systemctl restart pakgat-voucher; then
  rollback
  MUTATED=0
  fail "pakgat-voucher restart failed and rollout was rolled back"
fi

READY=0
for _ in 1 2 3 4 5 6 7 8 9 10; do
  CODE="$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/merchant 2>/dev/null || true)"
  if [ "$CODE" = "200" ]; then
    READY=1
    break
  fi
  sleep 1
done
if [ "$READY" -ne 1 ]; then
  rollback
  MUTATED=0
  fail "merchant service readiness failed and rollout was rolled back"
fi

echo "SADQ_STAGE2_SERVICE_OK"
echo "SADQ_STAGE2_BUTTON_ROUTE_INSTALLED=YES"
echo "SADQ_STAGE2_DEPLOY_OK"
echo "BACKUP=$BACKUP"
echo "CHANGED_ONLY=app/sadq_client.py,app/merchant_contract_pdf.py,app/merchant_onboarding_sadq_start.py,app/merchant_onboarding_sadq_bridge.py,app/assets/merchant_contract_template_*.b64,/etc/nginx/sites-available/pakgat-merchant"
echo "NEXT=https://merchant.pakgat.com/merchant/onboarding"
MUTATED=0
trap - EXIT
