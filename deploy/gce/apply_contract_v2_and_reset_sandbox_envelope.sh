#!/usr/bin/env bash
set -u

REPO="/opt/pakgat-voucher-system"
BRANCH="feat/sadq-dynamic-auth-webhook"
PY="$REPO/.venv/bin/python"
SERVICE="pakgat-voucher"
EXPECTED_APPLICATION_ID="2"
EXPECTED_AGREEMENT="PKG-MA-2026-08-0001"
EXPECTED_OLD_DOCUMENT_ID="dae9d097-d7ca-4543-a2be-37f69a295244"
EXPECTED_OLD_ENVELOPE_ID="9500c022-af56-4254-bf2c-cc8becba7ba7"
STAMP="$(date +%Y%m%d-%H%M%S)"
STAGE="/tmp/pakgat-contract-v2-stage-$STAMP"
BACKUP="/tmp/pakgat-contract-v2-backup-$STAMP"
SMOKE_PDF="/tmp/pakgat-contract-v2-smoke-$STAMP.pdf"
MUTATED=0

DEPLOY_FILES=(
  "app/merchant_contract_pdf.py"
  "app/assets/merchant_contract_v2_00.b64"
  "app/assets/merchant_contract_v2_01.b64"
  "app/assets/merchant_contract_v2_02.b64"
  "app/assets/merchant_contract_v2_03a.b64"
  "app/assets/merchant_contract_v2_03b.b64"
  "app/assets/merchant_contract_v2_04.b64"
)

PROTECTED_FILES=(
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
  echo "CONTRACT_V2_SANDBOX_RESET_FAILED: $1" >&2
  exit "${2:-1}"
}

protected_hashes() {
  local rel
  for rel in "${PROTECTED_FILES[@]}"; do
    [ -f "$REPO/$rel" ] || return 1
    printf '%s=%s\n' "$rel" "$(sha256sum "$REPO/$rel" | awk '{print $1}')"
  done
}

rollback_files() {
  local rel target saved
  if [ "$MUTATED" -ne 1 ]; then
    return 0
  fi
  echo "CONTRACT_V2_FILE_ROLLBACK_BEGIN"
  for rel in "${DEPLOY_FILES[@]}"; do
    target="$REPO/$rel"
    saved="$BACKUP/$rel"
    if [ -f "$saved" ]; then
      mkdir -p "$(dirname "$target")" >/dev/null 2>&1 || true
      cp -a "$saved" "$target" >/dev/null 2>&1 || true
      chown pakgat:pakgat "$target" >/dev/null 2>&1 || true
    else
      rm -f "$target" >/dev/null 2>&1 || true
    fi
  done
  systemctl restart "$SERVICE" >/dev/null 2>&1 || true
  echo "CONTRACT_V2_FILE_ROLLBACK_COMPLETE"
}

[ -x "$PY" ] || fail "production python missing"
[ -f "/etc/pakgat/pakgat.env" ] || fail "production environment file missing"

rm -rf "$STAGE" "$BACKUP"
mkdir -p "$STAGE/app/assets" "$STAGE/tests" "$BACKUP/app/assets" || fail "could not create staging directories"
printf '' > "$STAGE/app/__init__.py"

sudo -u pakgat git -C "$REPO" fetch origin "$BRANCH" || fail "git fetch failed"

for rel in "${DEPLOY_FILES[@]}"; do
  mkdir -p "$STAGE/$(dirname "$rel")" || fail "could not create staged path for $rel"
  sudo -u pakgat git -C "$REPO" show "origin/$BRANCH:$rel" > "$STAGE/$rel" || fail "could not stage $rel"
done
sudo -u pakgat git -C "$REPO" show "origin/$BRANCH:tests/test_merchant_contract_pdf.py" > "$STAGE/tests/test_merchant_contract_pdf.py" || fail "could not stage contract tests"

"$PY" -m py_compile "$STAGE/app/merchant_contract_pdf.py" || fail "staged contract module compile failed"
(
  cd "$STAGE" || exit 1
  export PYTHONPATH="$STAGE"
  "$PY" "$STAGE/tests/test_merchant_contract_pdf.py" -v
) || fail "staged contract v2 tests failed"
echo "CONTRACT_V2_STAGED_TESTS_OK"

BEFORE_PROTECTED="$(protected_hashes)" || fail "could not hash protected files"

for rel in "${DEPLOY_FILES[@]}"; do
  if [ -f "$REPO/$rel" ]; then
    mkdir -p "$BACKUP/$(dirname "$rel")" || fail "could not create backup path for $rel"
    cp -a "$REPO/$rel" "$BACKUP/$rel" || fail "could not back up $rel"
  fi
done

MUTATED=1
trap 'rc=$?; if [ "$rc" -ne 0 ]; then rollback_files; fi' EXIT

for rel in "${DEPLOY_FILES[@]}"; do
  mkdir -p "$(dirname "$REPO/$rel")" || { rollback_files; MUTATED=0; fail "could not create production path for $rel"; }
  cp "$STAGE/$rel" "$REPO/$rel" || { rollback_files; MUTATED=0; fail "could not deploy $rel"; }
  chown pakgat:pakgat "$REPO/$rel" 2>/dev/null || true
done

"$PY" -m py_compile "$REPO/app/merchant_contract_pdf.py" || { rollback_files; MUTATED=0; fail "production contract module compile failed"; }

AFTER_PROTECTED="$(protected_hashes)" || { rollback_files; MUTATED=0; fail "could not re-hash protected files"; }
[ "$BEFORE_PROTECTED" = "$AFTER_PROTECTED" ] || { rollback_files; MUTATED=0; fail "protected settings or routing changed unexpectedly"; }
echo "PROTECTED_SETTINGS_AND_ROUTING_UNCHANGED"

systemctl restart "$SERVICE" || { rollback_files; MUTATED=0; fail "service restart failed"; }
READY=0
for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do
  CODE="$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/merchant 2>/dev/null || true)"
  if [ "$CODE" = "200" ]; then
    READY=1
    break
  fi
  sleep 1
done
[ "$READY" -eq 1 ] || { rollback_files; MUTATED=0; fail "service readiness failed"; }
echo "CONTRACT_V2_SERVICE_OK"

set -a
. /etc/pakgat/pakgat.env
set +a
export CONTRACT_V2_SMOKE_PDF="$SMOKE_PDF"
export EXPECTED_APPLICATION_ID EXPECTED_AGREEMENT EXPECTED_OLD_DOCUMENT_ID EXPECTED_OLD_ENVELOPE_ID

cd "$REPO" || { rollback_files; MUTATED=0; fail "cannot enter production repo"; }

SMOKE_OUT="$($PY - <<'PY'
import os
import re
from pathlib import Path
from sqlalchemy import select

from app.application import SessionLocal
from app import merchant_finance as finance
from app import merchant_onboarding as onboarding
from app import merchant_onboarding_sadq_start as sadq_start
from app import merchant_contract_pdf

expected_application_id = int(os.environ["EXPECTED_APPLICATION_ID"])
expected_agreement = os.environ["EXPECTED_AGREEMENT"]
expected_document = os.environ["EXPECTED_OLD_DOCUMENT_ID"]
expected_envelope = os.environ["EXPECTED_OLD_ENVELOPE_ID"]
output_path = Path(os.environ["CONTRACT_V2_SMOKE_PDF"])

db = SessionLocal()
try:
    application = db.get(onboarding.MerchantOnboardingApplication, expected_application_id)
    if application is None:
        raise SystemExit("TEST_APPLICATION_NOT_FOUND")
    if application.status != "sadq_pending":
        raise SystemExit("TEST_APPLICATION_NOT_SADQ_PENDING")
    merchant = db.get(finance.Merchant, application.merchant_id)
    if merchant is None:
        raise SystemExit("TEST_MERCHANT_NOT_FOUND")
    if merchant.status != "pending":
        raise SystemExit("TEST_MERCHANT_NOT_PENDING")
    contract = db.scalar(
        select(finance.MerchantContract)
        .where(
            finance.MerchantContract.merchant_id == merchant.id,
            finance.MerchantContract.agreement_number == expected_agreement,
        )
        .limit(1)
    )
    if contract is None:
        raise SystemExit("TEST_CONTRACT_NOT_FOUND")
    if contract.status != "sadq_pending":
        raise SystemExit("TEST_CONTRACT_NOT_SADQ_PENDING")
    if str(contract.sadq_document_id or "") != expected_document:
        raise SystemExit("OLD_SADQ_DOCUMENT_ID_CHANGED_ABORT")
    if str(contract.sadq_transaction_id or "") != expected_envelope:
        raise SystemExit("OLD_SADQ_ENVELOPE_ID_CHANGED_ABORT")

    pdf = merchant_contract_pdf.render_contract_pdf(
        sadq_start._contract_data(merchant, application, contract)
    )
    output_path.write_bytes(pdf)
    pages = len(re.findall(rb"/Type\s*/Page\b", pdf))
    print(f"CONTRACT_V2_PROD_PDF_BYTES={len(pdf)}")
    print(f"CONTRACT_V2_PROD_PDF_PAGES={pages}")
    print(f"AGREEMENT={contract.agreement_number}")
finally:
    db.close()
PY
)"
SMOKE_RC=$?
if [ "$SMOKE_RC" -ne 0 ]; then
  printf '%s\n' "$SMOKE_OUT"
  rollback_files
  MUTATED=0
  fail "production v2 PDF smoke failed before Sadq"
fi
printf '%s\n' "$SMOKE_OUT"
PDF_PAGES="$(printf '%s\n' "$SMOKE_OUT" | awk -F= '/^CONTRACT_V2_PROD_PDF_PAGES=/{print $2}' | tail -n 1 | tr -d '[:space:]')"
if [ "$PDF_PAGES" != "4" ]; then
  rollback_files
  MUTATED=0
  fail "production PDF is $PDF_PAGES pages, expected exactly 4; Sadq was not called"
fi
echo "CONTRACT_V2_PROD_PDF_GATE_OK"

# The exact four-page PDF that passed the production gate above is the file sent
# to Sadq. The current test contract is hard-gated again before any DB mutation.
REPLACE_OUT="$($PY - <<'PY'
import os
from pathlib import Path
from sqlalchemy import select

from app import application as core
from app.application import SessionLocal
from app import merchant_finance as finance
from app import merchant_onboarding as onboarding
from app import merchant_onboarding_sadq_start as sadq_start
from app import sadq_client

expected_application_id = int(os.environ["EXPECTED_APPLICATION_ID"])
expected_agreement = os.environ["EXPECTED_AGREEMENT"]
expected_document = os.environ["EXPECTED_OLD_DOCUMENT_ID"]
expected_envelope = os.environ["EXPECTED_OLD_ENVELOPE_ID"]
pdf_path = Path(os.environ["CONTRACT_V2_SMOKE_PDF"])
pdf = pdf_path.read_bytes()
if not pdf.startswith(b"%PDF"):
    raise SystemExit("VERIFIED_PDF_MISSING")

new_document_id = ""
new_envelope_id = ""
db = SessionLocal()
try:
    application = db.get(onboarding.MerchantOnboardingApplication, expected_application_id)
    if application is None or application.status != "sadq_pending":
        raise SystemExit("TEST_APPLICATION_STATE_CHANGED_ABORT")
    merchant = db.get(finance.Merchant, application.merchant_id)
    if merchant is None or merchant.status != "pending":
        raise SystemExit("TEST_MERCHANT_STATE_CHANGED_ABORT")
    contract = db.scalar(
        select(finance.MerchantContract)
        .where(
            finance.MerchantContract.merchant_id == merchant.id,
            finance.MerchantContract.agreement_number == expected_agreement,
        )
        .limit(1)
    )
    if contract is None or contract.status != "sadq_pending":
        raise SystemExit("TEST_CONTRACT_STATE_CHANGED_ABORT")
    if str(contract.sadq_document_id or "") != expected_document:
        raise SystemExit("OLD_SADQ_DOCUMENT_ID_CHANGED_ABORT")
    if str(contract.sadq_transaction_id or "") != expected_envelope:
        raise SystemExit("OLD_SADQ_ENVELOPE_ID_CHANGED_ABORT")

    provider = sadq_client.get_default_client(reset=True)
    envelope = provider.initiate_base64_pdf(pdf, f"{expected_agreement}.pdf")
    new_document_id = envelope.document_id
    new_envelope_id = envelope.envelope_id

    # Prove the new document can issue the Nafath-authenticated invitation before
    # changing Pakgat's stored provider identifiers.
    sadq_start._send_nafath_invitation(
        provider,
        merchant,
        application,
        new_document_id,
    )
    status_payload = provider._authorized_json(
        "GET",
        f"/api/v1/envelopes/{new_envelope_id}/status",
    )
    data = status_payload.get("data") or {}
    provider_status = str(data.get("status") or "").strip()
    if not provider_status:
        raise RuntimeError("NEW_SADQ_ENVELOPE_STATUS_MISSING")

    # Only this existing test-contract row is repointed. Merchant/application
    # profile data are not modified.
    contract.sadq_document_id = new_document_id
    contract.sadq_transaction_id = new_envelope_id
    contract.status = "sadq_pending"
    contract.updated_at = core.now_utc()
    db.add(contract)
    db.flush()
    if str(contract.agreement_number or "") != expected_agreement:
        raise RuntimeError("AGREEMENT_NUMBER_CHANGED_ABORT")
    db.commit()

    print(f"OLD_SADQ_DOCUMENT_ID={expected_document}")
    print(f"OLD_SADQ_ENVELOPE_ID={expected_envelope}")
    print(f"NEW_SADQ_DOCUMENT_ID={new_document_id}")
    print(f"NEW_SADQ_ENVELOPE_ID={new_envelope_id}")
    print(f"NEW_ENVELOPE_STATUS={provider_status}")
    print("NEW_INVITATION_CREATED=YES")
    print("DB_COMMIT_COMPLETED=YES")
    print("CONTRACT_V2_SANDBOX_REPLACED=YES")
except BaseException as exc:
    db.rollback()
    if new_document_id:
        print(f"ORPHAN_NEW_SADQ_DOCUMENT_ID={new_document_id}")
    if new_envelope_id:
        print(f"ORPHAN_NEW_SADQ_ENVELOPE_ID={new_envelope_id}")
    if isinstance(exc, SystemExit):
        print(f"REPLACE_ABORT_REASON={exc.code}")
    else:
        print(f"REPLACE_ABORT_TYPE={type(exc).__name__}")
    raise
finally:
    db.close()
PY
)"
REPLACE_RC=$?
if [ "$REPLACE_RC" -ne 0 ]; then
  printf '%s\n' "$REPLACE_OUT"
  rollback_files
  MUTATED=0
  fail "Sadq Sandbox replacement did not complete; old Pakgat IDs remain unless DB_COMMIT_COMPLETED=YES is shown"
fi
printf '%s\n' "$REPLACE_OUT"

printf '%s\n' "$REPLACE_OUT" | grep -q '^CONTRACT_V2_SANDBOX_REPLACED=YES$' || fail "replacement success marker missing"
printf '%s\n' "$REPLACE_OUT" | grep -q '^DB_COMMIT_COMPLETED=YES$' || fail "database commit marker missing"

FINAL_PROTECTED="$(protected_hashes)" || fail "could not perform final protected hash check"
[ "$BEFORE_PROTECTED" = "$FINAL_PROTECTED" ] || fail "protected settings or routing changed after Sandbox replacement"
echo "PROTECTED_SETTINGS_AND_ROUTING_UNCHANGED_FINAL"
echo "OLD_SADQ_ENVELOPE_LEFT_UNUSED=YES"
echo "AGREEMENT=$EXPECTED_AGREEMENT"
echo "CHANGED_ONLY=app/merchant_contract_pdf.py,app/assets/merchant_contract_v2_*.b64,current_test_contract_sadq_ids"
echo "BACKUP=$BACKUP"
echo "NEXT=https://merchant.pakgat.com/merchant/onboarding"

MUTATED=0
trap - EXIT
