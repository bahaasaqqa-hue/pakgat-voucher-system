#!/usr/bin/env bash
set -u

REPO="/opt/pakgat-voucher-system"
BRANCH="feat/sadq-dynamic-auth-webhook"
COMMIT="90f5c79a90f08855188bce2aaa9c0b40b77cb674"
EXPECTED_TEMPLATE_SHA="3c53695bd73adb417be6fc47bb04792896c6b50fc2a424fd0c5b22ea16aebdc0"
PY="$REPO/.venv/bin/python"
STAMP="$(date +%Y%m%d-%H%M%S)"
STAGE="/tmp/pakgat-final-contract-$STAMP"
BACKUP="/tmp/pakgat-final-contract-backup-$STAMP"
MUTATED=0

FILES=(
  "app/merchant_contract_pdf.py"
  "app/assets/merchant_contract_template_00.b64"
  "app/assets/merchant_contract_template_01.b64"
  "app/assets/merchant_contract_template_02.b64"
  "app/assets/merchant_contract_template_03a1.b64"
  "app/assets/merchant_contract_template_03a2.b64"
  "app/assets/merchant_contract_template_03b.b64"
  "app/assets/merchant_contract_template_03c_1.b64"
  "app/assets/merchant_contract_template_03c_2.b64"
  "app/assets/merchant_contract_template_04_1.b64"
  "app/assets/merchant_contract_template_04_2.b64"
  "app/assets/merchant_contract_template_05_1.b64"
  "app/assets/merchant_contract_template_05_2.b64"
  "app/assets/merchant_contract_template_06_1.b64"
  "app/assets/merchant_contract_template_06_2.b64"
  "app/assets/merchant_contract_template_07_1.b64"
  "app/assets/merchant_contract_template_07_2.b64"
)

PROTECTED=(
  "main.py"
  "app/jood_identity.py"
  "app/jood_outbound.py"
  "app/jood_policy.py"
  "app/jood_whatsapp_campaign.py"
  "app/jood_whatsapp_campaign_ui.py"
  "app/jood_whatsapp_context.py"
  "app/whatsloop_inbound.py"
)

fail() {
  echo "FINAL_CONTRACT_DEPLOY_FAILED: $1" >&2
  exit "${2:-1}"
}

rollback() {
  if [ "$MUTATED" -ne 1 ]; then
    return 0
  fi
  echo "FINAL_CONTRACT_ROLLBACK_BEGIN"
  for rel in "${FILES[@]}"; do
    rm -f "$REPO/$rel" >/dev/null 2>&1 || true
  done
  if [ -d "$BACKUP/files" ]; then
    cp -a "$BACKUP/files/." "$REPO/" >/dev/null 2>&1 || true
  fi
  chown -R pakgat:pakgat "$REPO/app" >/dev/null 2>&1 || true
  systemctl restart pakgat-voucher >/dev/null 2>&1 || true
  echo "FINAL_CONTRACT_ROLLBACK_COMPLETE"
}

[ -d "$REPO/.git" ] || fail "production repository missing"
[ -x "$PY" ] || fail "production python missing"
command -v libreoffice >/dev/null 2>&1 || command -v soffice >/dev/null 2>&1 || fail "LibreOffice missing"

for rel in "${PROTECTED[@]}"; do
  [ -f "$REPO/$rel" ] || fail "protected file missing: $rel"
done

rm -rf "$STAGE" "$BACKUP"
mkdir -p "$STAGE/app/assets" "$STAGE/tests" "$BACKUP/files"

sudo -u pakgat git -C "$REPO" fetch origin "$BRANCH" || fail "git fetch failed"
sudo -u pakgat git -C "$REPO" cat-file -e "$COMMIT^{commit}" || fail "pinned contract commit is unavailable"

for rel in "${FILES[@]}"; do
  mkdir -p "$STAGE/$(dirname "$rel")"
  sudo -u pakgat git -C "$REPO" show "$COMMIT:$rel" > "$STAGE/$rel" || fail "could not stage $rel"
done
sudo -u pakgat git -C "$REPO" show "$COMMIT:tests/test_merchant_contract_pdf.py" > "$STAGE/tests/test_merchant_contract_pdf.py" || fail "could not stage contract test"
: > "$STAGE/app/__init__.py"

"$PY" -m py_compile "$STAGE/app/merchant_contract_pdf.py" || fail "staged compile failed"
(
  cd "$STAGE" || exit 1
  export DATABASE_URL="sqlite:///:memory:"
  export PYTHONPATH="$STAGE"
  "$PY" tests/test_merchant_contract_pdf.py -v
) || fail "staged contract tests failed"
echo "FINAL_CONTRACT_STAGED_TESTS_OK"

STAGED_SHA="$(cd "$STAGE" && PYTHONPATH="$STAGE" "$PY" - <<'PY'
import hashlib
from app import merchant_contract_pdf as m
print(hashlib.sha256(m._template_bytes()).hexdigest())
PY
)" || fail "could not hash staged template"
[ "$STAGED_SHA" = "$EXPECTED_TEMPLATE_SHA" ] || fail "staged template checksum mismatch"
echo "FINAL_CONTRACT_TEMPLATE_SHA_OK=$STAGED_SHA"

: > "$BACKUP/existing.txt"
for rel in "${FILES[@]}"; do
  if [ -f "$REPO/$rel" ]; then
    mkdir -p "$BACKUP/files/$(dirname "$rel")"
    cp -a "$REPO/$rel" "$BACKUP/files/$rel" || fail "backup failed: $rel"
    printf '%s\n' "$rel" >> "$BACKUP/existing.txt"
  fi
done

PROTECTED_ABS=()
for rel in "${PROTECTED[@]}"; do PROTECTED_ABS+=("$REPO/$rel"); done
sha256sum "${PROTECTED_ABS[@]}" > "$BACKUP/protected.before" || fail "protected pre-hash failed"

MUTATED=1
trap 'rc=$?; if [ "$rc" -ne 0 ]; then rollback; fi' EXIT

for rel in "${FILES[@]}"; do
  mkdir -p "$REPO/$(dirname "$rel")"
  install -m 0644 -o pakgat -g pakgat "$STAGE/$rel" "$REPO/$rel" || { rollback; MUTATED=0; fail "install failed: $rel"; }
done

(
  cd "$REPO" || exit 1
  export DATABASE_URL="sqlite:///:memory:"
  export PYTHONPATH="$REPO"
  "$PY" "$STAGE/tests/test_merchant_contract_pdf.py" -v
) || { rollback; MUTATED=0; fail "production-target contract tests failed"; }
echo "FINAL_CONTRACT_PRODUCTION_TESTS_OK"

PROD_SHA="$(cd "$REPO" && PYTHONPATH="$REPO" "$PY" - <<'PY'
import hashlib
from app import merchant_contract_pdf as m
print(hashlib.sha256(m._template_bytes()).hexdigest())
PY
)" || { rollback; MUTATED=0; fail "could not hash production template"; }
[ "$PROD_SHA" = "$EXPECTED_TEMPLATE_SHA" ] || { rollback; MUTATED=0; fail "production template checksum mismatch"; }
echo "FINAL_CONTRACT_PRODUCTION_SHA_OK=$PROD_SHA"

SMOKE_OUT="$(cd "$REPO" && PYTHONPATH="$REPO" "$PY" - <<'PY'
import hashlib
import time
from app import merchant_contract_pdf as m

data = m.ContractData(
    agreement_number="PKG-SMOKE-2026-09-01",
    agreement_date="01 / 09 / 2026",
    legal_name="شركة اختبار بكجات",
    commercial_registration="1000000000",
    activity="اختبار تقني",
    tax_number="300000000000003",
    bank_name="بنك الاختبار",
    iban="SA0000000000000000000000",
    national_address="الرياض",
    contact_phone="0500000000",
    contact_email="smoke@example.com",
    website="https://example.com",
    representative_name="ممثل اختبار",
    representative_title="مدير",
)
start = time.monotonic()
pdf = m.render_contract_pdf(data)
elapsed = time.monotonic() - start
if not pdf.startswith(b"%PDF"):
    raise SystemExit("not a PDF")
if len(pdf) < 50000:
    raise SystemExit("unexpectedly small PDF")
print(f"PDF_BYTES={len(pdf)}")
print(f"PDF_SECONDS={elapsed:.2f}")
print(f"PDF_SHA256={hashlib.sha256(pdf).hexdigest()}")
if elapsed >= 45:
    raise SystemExit("PDF conversion exceeded safe gateway budget")
PY
)"
SMOKE_RC=$?
if [ "$SMOKE_RC" -ne 0 ]; then
  rollback
  MUTATED=0
  fail "real production PDF smoke failed"
fi
printf '%s\n' "$SMOKE_OUT"
echo "FINAL_CONTRACT_REAL_PDF_OK"

sha256sum "${PROTECTED_ABS[@]}" > "$BACKUP/protected.after" || { rollback; MUTATED=0; fail "protected post-hash failed"; }
diff -u "$BACKUP/protected.before" "$BACKUP/protected.after" >/dev/null || { rollback; MUTATED=0; fail "protected Jood/WhatsLoop/main files changed unexpectedly"; }
echo "PROTECTED_SETTINGS_AND_ROUTING_UNCHANGED"

systemctl restart pakgat-voucher || { rollback; MUTATED=0; fail "service restart failed"; }
READY=0
for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do
  CODE="$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/merchant 2>/dev/null || true)"
  if [ "$CODE" = "200" ]; then READY=1; break; fi
  sleep 1
done
[ "$READY" -eq 1 ] || { rollback; MUTATED=0; fail "service readiness failed"; }

echo "FINAL_CONTRACT_SERVICE_OK"
echo "FINAL_CONTRACT_DEPLOY_OK"
echo "COMMIT=$COMMIT"
echo "CHANGED_ONLY=app/merchant_contract_pdf.py,referenced merchant_contract_template assets"
echo "BACKUP=$BACKUP"
MUTATED=0
trap - EXIT
