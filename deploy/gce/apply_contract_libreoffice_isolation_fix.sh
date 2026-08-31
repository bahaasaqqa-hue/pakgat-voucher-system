#!/usr/bin/env bash
set -u

REPO="/opt/pakgat-voucher-system"
BRANCH="feat/sadq-dynamic-auth-webhook"
PY="$REPO/.venv/bin/python"
TARGET="$REPO/app/merchant_contract_pdf.py"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="/tmp/merchant-contract-pdf-before-lo-fix-$STAMP.py"
STAGE="/tmp/merchant-contract-lo-fix-$STAMP"
MUTATED=0

fail() {
  echo "CONTRACT_LO_FIX_FAILED: $1" >&2
  exit "${2:-1}"
}

rollback() {
  if [ "$MUTATED" -ne 1 ]; then
    return 0
  fi
  echo "CONTRACT_LO_FIX_ROLLBACK_BEGIN"
  cp -a "$BACKUP" "$TARGET" >/dev/null 2>&1 || true
  chown pakgat:pakgat "$TARGET" 2>/dev/null || true
  systemctl restart pakgat-voucher >/dev/null 2>&1 || true
  echo "CONTRACT_LO_FIX_ROLLBACK_COMPLETE"
}

[ -x "$PY" ] || fail "production python missing"
[ -f "$TARGET" ] || fail "merchant_contract_pdf.py missing"
command -v libreoffice >/dev/null 2>&1 || command -v soffice >/dev/null 2>&1 || fail "LibreOffice missing"

rm -rf "$STAGE"
mkdir -p "$STAGE/app" "$STAGE/tests"
sudo -u pakgat git -C "$REPO" fetch origin "$BRANCH" || fail "git fetch failed"
sudo -u pakgat git -C "$REPO" show "origin/$BRANCH:app/merchant_contract_pdf.py" > "$STAGE/app/merchant_contract_pdf.py" || fail "could not stage PDF module"
sudo -u pakgat git -C "$REPO" show "origin/$BRANCH:tests/test_merchant_contract_pdf.py" > "$STAGE/tests/test_merchant_contract_pdf.py" || fail "could not stage PDF test"

"$PY" -m py_compile "$STAGE/app/merchant_contract_pdf.py" || fail "staged compile failed"
grep -q 'UserInstallation=' "$STAGE/app/merchant_contract_pdf.py" || fail "isolated LibreOffice profile missing from staged code"
grep -q 'timeout=40' "$STAGE/app/merchant_contract_pdf.py" || fail "bounded LibreOffice timeout missing from staged code"
echo "CONTRACT_LO_FIX_STAGED_OK"

cp -a "$TARGET" "$BACKUP" || fail "backup failed"
BEFORE_MAIN="$(sha256sum "$REPO/main.py" | awk '{print $1}')"
BEFORE_JOOD="$(sha256sum "$REPO/app/jood_whatsapp_context.py" | awk '{print $1}')"
BEFORE_WHATSLOOP="$(sha256sum "$REPO/app/whatsloop_inbound.py" | awk '{print $1}')"

MUTATED=1
trap 'rc=$?; if [ "$rc" -ne 0 ]; then rollback; fi' EXIT
cp "$STAGE/app/merchant_contract_pdf.py" "$TARGET" || { rollback; MUTATED=0; fail "copy failed"; }
chown pakgat:pakgat "$TARGET" 2>/dev/null || true

# Remove only stale Pakgat LibreOffice processes that are converting our merchant-agreement temp files.
STALE_BEFORE="$(pgrep -u pakgat -af 'libreoffice|soffice|oosplash' | grep 'merchant-agreement.docx' | wc -l || true)"
pkill -u pakgat -f 'merchant-agreement\.docx' 2>/dev/null || true
sleep 1
STALE_AFTER="$(pgrep -u pakgat -af 'libreoffice|soffice|oosplash' | grep 'merchant-agreement.docx' | wc -l || true)"
echo "CONTRACT_LO_STALE_PROCESSES_BEFORE=$STALE_BEFORE"
echo "CONTRACT_LO_STALE_PROCESSES_AFTER=$STALE_AFTER"

(
  cd "$REPO" || exit 1
  export DATABASE_URL="sqlite:///:memory:"
  export PYTHONPATH="$REPO"
  "$PY" "$STAGE/tests/test_merchant_contract_pdf.py" -v
) || { rollback; MUTATED=0; fail "targeted PDF tests failed"; }
echo "CONTRACT_LO_FIX_TESTS_OK"

# Real server-side LibreOffice smoke. This does not call Sadq and does not create an envelope.
SMOKE_OUT="$($PY - <<'PY'
import time
from app import merchant_contract_pdf as m

data = m.ContractData(
    agreement_number="PKG-SMOKE-2026-08-31",
    agreement_date="31 / 08 / 2026",
    legal_name="شركة اختبار بكجات",
    commercial_registration="1000000000",
    activity="اختبار تقني",
    tax_number="300000000000003",
    bank_name="بنك الاختبار",
    iban="SA0000000000000000000000",
    national_address="الرياض",
    contact_phone="0500000000",
    contact_email="smoke@example.com",
    website="",
    representative_name="ممثل اختبار",
    representative_title="مدير",
)
start = time.monotonic()
pdf = m.render_contract_pdf(data)
elapsed = time.monotonic() - start
if not pdf.startswith(b"%PDF"):
    raise SystemExit("not a PDF")
print(f"PDF_BYTES={len(pdf)}")
print(f"PDF_SECONDS={elapsed:.2f}")
if elapsed >= 45:
    raise SystemExit("PDF conversion exceeded safe gateway budget")
PY
)"
SMOKE_RC=$?
if [ "$SMOKE_RC" -ne 0 ]; then
  rollback
  MUTATED=0
  fail "real LibreOffice PDF smoke failed"
fi
printf '%s\n' "$SMOKE_OUT"
echo "CONTRACT_LO_REAL_PDF_OK"

AFTER_MAIN="$(sha256sum "$REPO/main.py" | awk '{print $1}')"
AFTER_JOOD="$(sha256sum "$REPO/app/jood_whatsapp_context.py" | awk '{print $1}')"
AFTER_WHATSLOOP="$(sha256sum "$REPO/app/whatsloop_inbound.py" | awk '{print $1}')"
[ "$BEFORE_MAIN" = "$AFTER_MAIN" ] || { rollback; MUTATED=0; fail "main.py changed unexpectedly"; }
[ "$BEFORE_JOOD" = "$AFTER_JOOD" ] || { rollback; MUTATED=0; fail "Jood context changed unexpectedly"; }
[ "$BEFORE_WHATSLOOP" = "$AFTER_WHATSLOOP" ] || { rollback; MUTATED=0; fail "WhatsLoop inbound changed unexpectedly"; }
echo "PROTECTED_SETTINGS_AND_ROUTING_UNCHANGED"

systemctl restart pakgat-voucher || { rollback; MUTATED=0; fail "service restart failed"; }
READY=0
for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do
  CODE="$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/merchant 2>/dev/null || true)"
  if [ "$CODE" = "200" ]; then READY=1; break; fi
  sleep 1
done
[ "$READY" -eq 1 ] || { rollback; MUTATED=0; fail "service readiness failed"; }

echo "CONTRACT_LO_FIX_SERVICE_OK"
echo "CONTRACT_LO_FIX_DEPLOY_OK"
echo "CHANGED_ONLY=app/merchant_contract_pdf.py"
echo "BACKUP=$BACKUP"
MUTATED=0
trap - EXIT
