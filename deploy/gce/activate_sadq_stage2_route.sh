#!/usr/bin/env bash
set -u

REPO="/opt/pakgat-voucher-system"
MAIN="$REPO/main.py"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="/tmp/main-before-sadq-stage2-route-$STAMP.py"
IMPORT_LINE="from app import merchant_onboarding_sadq_bridge as _merchant_onboarding_sadq_bridge  # noqa: F401 - signed Sadq contracts become pending Pakgat review"
ANCHOR="from app import merchant_onboarding_brand_assets as _merchant_onboarding_brand_assets  # noqa: F401 - official Pakgat logo and Nafath image"

fail() {
  echo "SADQ_STAGE2_ROUTE_ACTIVATION_FAILED: $1" >&2
  exit "${2:-1}"
}

[ -f "$MAIN" ] || fail "production main.py not found"
[ -f "$REPO/app/merchant_onboarding_sadq_bridge.py" ] || fail "Sadq bridge file is not deployed"
[ -f "$REPO/app/merchant_onboarding_sadq_start.py" ] || fail "Sadq start file is not deployed"

cp -a "$MAIN" "$BACKUP" || fail "could not back up main.py"
BEFORE_SHA="$(sha256sum "$MAIN" | awk '{print $1}')"

python3 - "$MAIN" "$ANCHOR" "$IMPORT_LINE" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
anchor = sys.argv[2]
import_line = sys.argv[3]
text = path.read_text(encoding="utf-8")

if import_line in text:
    print("SADQ_STAGE2_ROUTE_IMPORT_ALREADY_PRESENT=YES")
    raise SystemExit(0)

if text.count(anchor) != 1:
    raise SystemExit(f"expected exactly one onboarding brand-assets anchor, found {text.count(anchor)}")

text = text.replace(anchor, anchor + "\n" + import_line, 1)
path.write_text(text, encoding="utf-8")
print("SADQ_STAGE2_ROUTE_IMPORT_ADDED=YES")
PY
PATCH_RC=$?
if [ "$PATCH_RC" -ne 0 ]; then
  cp -a "$BACKUP" "$MAIN" >/dev/null 2>&1 || true
  fail "could not insert the Sadq bridge import; main.py restored"
fi

# Verify the only textual change is the one import line.
python3 - "$BACKUP" "$MAIN" "$IMPORT_LINE" <<'PY'
from pathlib import Path
import sys
before = Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
after = Path(sys.argv[2]).read_text(encoding="utf-8").splitlines()
line = sys.argv[3]
if line in before:
    if before != after:
        raise SystemExit("main.py was already activated but changed unexpectedly")
else:
    expected = list(before)
    anchor_index = next(i for i, value in enumerate(expected) if "merchant_onboarding_brand_assets as _merchant_onboarding_brand_assets" in value)
    expected.insert(anchor_index + 1, line)
    if after != expected:
        raise SystemExit("main.py changed beyond the single Sadq import")
print("MAIN_SINGLE_LINE_CHANGE_OK")
PY
VERIFY_RC=$?
if [ "$VERIFY_RC" -ne 0 ]; then
  cp -a "$BACKUP" "$MAIN" >/dev/null 2>&1 || true
  fail "main.py scope verification failed; restored backup"
fi

chown pakgat:pakgat "$MAIN" 2>/dev/null || true
/opt/pakgat-voucher-system/.venv/bin/python -m py_compile "$MAIN" || {
  cp -a "$BACKUP" "$MAIN" >/dev/null 2>&1 || true
  chown pakgat:pakgat "$MAIN" 2>/dev/null || true
  fail "main.py compile failed; restored backup"
}
echo "MAIN_COMPILE_OK"

if ! systemctl restart pakgat-voucher; then
  cp -a "$BACKUP" "$MAIN" >/dev/null 2>&1 || true
  chown pakgat:pakgat "$MAIN" 2>/dev/null || true
  systemctl restart pakgat-voucher >/dev/null 2>&1 || true
  fail "service restart failed; restored backup"
fi

READY=0
for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do
  CODE="$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/merchant 2>/dev/null || true)"
  if [ "$CODE" = "200" ]; then
    READY=1
    break
  fi
  sleep 1
done
if [ "$READY" -ne 1 ]; then
  cp -a "$BACKUP" "$MAIN" >/dev/null 2>&1 || true
  chown pakgat:pakgat "$MAIN" 2>/dev/null || true
  systemctl restart pakgat-voucher >/dev/null 2>&1 || true
  fail "service readiness failed; restored backup"
fi

grep -Fqx "$IMPORT_LINE" "$MAIN" || fail "Sadq bridge import missing after restart"
AFTER_SHA="$(sha256sum "$MAIN" | awk '{print $1}')"

echo "SADQ_STAGE2_ROUTE_SERVICE_OK"
echo "SADQ_STAGE2_ROUTE_ACTIVATED=YES"
echo "CHANGED_ONLY=main.py::one_import_line"
echo "BEFORE_SHA256=$BEFORE_SHA"
echo "AFTER_SHA256=$AFTER_SHA"
echo "BACKUP=$BACKUP"
echo "NEXT=https://merchant.pakgat.com/merchant/onboarding"
