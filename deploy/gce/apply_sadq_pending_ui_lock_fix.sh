#!/usr/bin/env bash
set -u

REPO="/opt/pakgat-voucher-system"
BRANCH="feat/sadq-dynamic-auth-webhook"
PY="$REPO/.venv/bin/python"
TARGET="$REPO/app/merchant_onboarding_sadq_start.py"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="/tmp/merchant-onboarding-sadq-start-before-pending-ui-$STAMP.py"
STAGE="/tmp/pakgat-sadq-pending-ui-$STAMP"
MUTATED=0

fail() {
  echo "SADQ_PENDING_UI_FIX_FAILED: $1" >&2
  exit "${2:-1}"
}

rollback() {
  if [ "$MUTATED" -ne 1 ]; then
    return 0
  fi
  echo "SADQ_PENDING_UI_ROLLBACK_BEGIN"
  cp -a "$BACKUP" "$TARGET" >/dev/null 2>&1 || true
  chown pakgat:pakgat "$TARGET" 2>/dev/null || true
  systemctl restart pakgat-voucher >/dev/null 2>&1 || true
  echo "SADQ_PENDING_UI_ROLLBACK_COMPLETE"
}

[ -x "$PY" ] || fail "production python missing"
[ -f "$TARGET" ] || fail "merchant_onboarding_sadq_start.py missing"

rm -rf "$STAGE"
mkdir -p "$STAGE/app" "$STAGE/tests"

sudo -u pakgat git -C "$REPO" fetch origin "$BRANCH" || fail "git fetch failed"
sudo -u pakgat git -C "$REPO" show "origin/$BRANCH:app/merchant_onboarding_sadq_start.py" > "$STAGE/app/merchant_onboarding_sadq_start.py" || fail "could not stage module"
sudo -u pakgat git -C "$REPO" show "origin/$BRANCH:tests/test_merchant_onboarding_sadq_start.py" > "$STAGE/tests/test_merchant_onboarding_sadq_start.py" || fail "could not stage test"

"$PY" -m py_compile "$STAGE/app/merchant_onboarding_sadq_start.py" || fail "staged compile failed"
grep -q 'def _is_sadq_pending' "$STAGE/app/merchant_onboarding_sadq_start.py" || fail "pending guard missing"
grep -q 'def _sadq_pending_page' "$STAGE/app/merchant_onboarding_sadq_start.py" || fail "pending page missing"
grep -q 'def resume_sadq_signing' "$STAGE/app/merchant_onboarding_sadq_start.py" || fail "safe resume helper missing"
grep -q '/merchant/onboarding/sadq/resume' "$STAGE/app/merchant_onboarding_sadq_start.py" || fail "safe resume route missing"
grep -q 'onboarding._onboarding_page = _sadq_aware_onboarding_page' "$STAGE/app/merchant_onboarding_sadq_start.py" || fail "pending page override missing"
echo "SADQ_PENDING_UI_STAGED_OK"

(
  cd "$REPO" || exit 1
  export DATABASE_URL="sqlite:///:memory:"
  export MERCHANT_PORTAL_SECRET="test-only-merchant-portal-secret"
  export PYTHONPATH="$REPO"
  export STAGED_SADQ_START="$STAGE/app/merchant_onboarding_sadq_start.py"
  export STAGED_TEST="$STAGE/tests/test_merchant_onboarding_sadq_start.py"
  "$PY" - <<'PY'
import importlib.util
import os
import runpy
import sys

import app

module_name = "app.merchant_onboarding_sadq_start"
module_path = os.environ["STAGED_SADQ_START"]
spec = importlib.util.spec_from_file_location(module_name, module_path)
if spec is None or spec.loader is None:
    raise SystemExit("could not load staged Sadq onboarding module")
module = importlib.util.module_from_spec(spec)
sys.modules[module_name] = module
setattr(app, "merchant_onboarding_sadq_start", module)
spec.loader.exec_module(module)
print("SADQ_PENDING_UI_STAGED_MODULE_LOADED=YES")

staged_test = os.environ["STAGED_TEST"]
sys.argv = [staged_test, "-v"]
runpy.run_path(staged_test, run_name="__main__")
PY
) || fail "targeted Sadq onboarding tests failed"
echo "SADQ_PENDING_UI_TARGETED_TESTS_OK"

cp -a "$TARGET" "$BACKUP" || fail "backup failed"
BEFORE_MAIN="$(sha256sum "$REPO/main.py" | awk '{print $1}')"
BEFORE_JOOD="$(sha256sum "$REPO/app/jood_whatsapp_context.py" | awk '{print $1}')"
BEFORE_WHATSLOOP="$(sha256sum "$REPO/app/whatsloop_inbound.py" | awk '{print $1}')"
BEFORE_BRIDGE="$(sha256sum "$REPO/app/merchant_onboarding_sadq_bridge.py" | awk '{print $1}')"

MUTATED=1
trap 'rc=$?; if [ "$rc" -ne 0 ]; then rollback; fi' EXIT
cp "$STAGE/app/merchant_onboarding_sadq_start.py" "$TARGET" || { rollback; MUTATED=0; fail "copy failed"; }
chown pakgat:pakgat "$TARGET" 2>/dev/null || true
"$PY" -m py_compile "$TARGET" || { rollback; MUTATED=0; fail "production compile failed"; }

AFTER_MAIN="$(sha256sum "$REPO/main.py" | awk '{print $1}')"
AFTER_JOOD="$(sha256sum "$REPO/app/jood_whatsapp_context.py" | awk '{print $1}')"
AFTER_WHATSLOOP="$(sha256sum "$REPO/app/whatsloop_inbound.py" | awk '{print $1}')"
AFTER_BRIDGE="$(sha256sum "$REPO/app/merchant_onboarding_sadq_bridge.py" | awk '{print $1}')"
[ "$BEFORE_MAIN" = "$AFTER_MAIN" ] || { rollback; MUTATED=0; fail "main.py changed unexpectedly"; }
[ "$BEFORE_JOOD" = "$AFTER_JOOD" ] || { rollback; MUTATED=0; fail "Jood context changed unexpectedly"; }
[ "$BEFORE_WHATSLOOP" = "$AFTER_WHATSLOOP" ] || { rollback; MUTATED=0; fail "WhatsLoop inbound changed unexpectedly"; }
[ "$BEFORE_BRIDGE" = "$AFTER_BRIDGE" ] || { rollback; MUTATED=0; fail "Sadq bridge changed unexpectedly"; }
echo "PROTECTED_SETTINGS_AND_ROUTING_UNCHANGED"

systemctl restart pakgat-voucher || { rollback; MUTATED=0; fail "service restart failed"; }
READY=0
for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do
  CODE="$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/merchant 2>/dev/null || true)"
  if [ "$CODE" = "200" ]; then
    READY=1
    break
  fi
  sleep 1
done
[ "$READY" -eq 1 ] || { rollback; MUTATED=0; fail "service readiness failed"; }
echo "SADQ_PENDING_UI_SERVICE_OK"

# Render the real current pending application using production configuration.
# This is read-only and does not call Sadq or mutate the database.
set -a
. /etc/pakgat/pakgat.env
set +a
cd "$REPO" || { rollback; MUTATED=0; fail "cannot enter repo"; }
SMOKE_OUT="$($PY - <<'PY'
import main  # load production import order and UI overrides
from sqlalchemy import select
from app.application import SessionLocal
from app import merchant_finance as finance
from app import merchant_onboarding as onboarding

resume_routes = []
for route in main.app.routes:
    methods = getattr(route, "methods", set()) or set()
    if getattr(route, "path", "") == "/merchant/onboarding/sadq/resume" and "POST" in methods:
        resume_routes.append(route)
if len(resume_routes) != 1:
    raise SystemExit(f"expected one Sadq resume POST route, found {len(resume_routes)}")
print("SADQ_RESUME_ROUTE_INSTALLED=YES")

db = SessionLocal()
try:
    application = db.scalar(
        select(onboarding.MerchantOnboardingApplication)
        .where(onboarding.MerchantOnboardingApplication.status == "sadq_pending")
        .order_by(onboarding.MerchantOnboardingApplication.id.desc())
        .limit(1)
    )
    if application is None:
        raise SystemExit("no sadq_pending application found")
    merchant = db.get(finance.Merchant, application.merchant_id)
    if merchant is None:
        raise SystemExit("pending merchant missing")
    html = onboarding._onboarding_page(db, merchant)
    required = (
        "بانتظار إكمال التحقق والتوقيع",
        "تم إنشاء اتفاقية الشراكة وإرسالها للتوثيق",
        "متابعة التحقق والتوقيع عبر صادق",
        "action='/merchant/onboarding/sadq/resume'",
        "تحديث حالة الطلب",
    )
    for text in required:
        if text not in html:
            raise SystemExit(f"missing pending UI text: {text}")
    forbidden = (
        "action='/merchant/onboarding/submit'",
        "action='/merchant/onboarding/profile'",
        "action='/merchant/onboarding/documents'",
        "يوجد عقد قائم لا يمكن استبداله من التسجيل",
    )
    for text in forbidden:
        if text in html:
            raise SystemExit(f"unsafe pending UI control remains: {text}")
    print("CURRENT_APPLICATION_ID=", application.id)
    print("CURRENT_PENDING_UI_LOCKED=YES")
    print("CURRENT_PENDING_RESUME_BUTTON=YES")
finally:
    db.close()
PY
)"
SMOKE_RC=$?
if [ "$SMOKE_RC" -ne 0 ]; then
  rollback
  MUTATED=0
  fail "production pending UI smoke failed"
fi
printf '%s\n' "$SMOKE_OUT"

echo "SADQ_PENDING_UI_FIX_DEPLOY_OK"
echo "CHANGED_ONLY=app/merchant_onboarding_sadq_start.py"
echo "BACKUP=$BACKUP"
MUTATED=0
trap - EXIT
