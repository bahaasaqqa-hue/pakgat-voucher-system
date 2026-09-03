#!/usr/bin/env bash
set -u

REPO=/opt/pakgat-voucher-system
TMP_SCRIPT="/tmp/pakgat-sadq-sandbox-smoke-$$.py"

fail() {
  echo "SADQ_SMOKE_RUNNER_FAILED: $*" >&2
  rm -f "$TMP_SCRIPT" 2>/dev/null || true
  exit 1
}

[[ -d "$REPO/.git" ]] || fail "Repository not found: $REPO"

sudo -u pakgat git -C "$REPO" fetch origin gce-migration || fail "git fetch failed"
sudo -u pakgat git -C "$REPO" show origin/gce-migration:scripts/sadq_sandbox_smoke.py > "$TMP_SCRIPT" || fail "could not materialize smoke script"
chmod 600 "$TMP_SCRIPT" || fail "could not protect temporary smoke script"

PYTHON="$REPO/.venv/bin/python"
[[ -x "$PYTHON" ]] || PYTHON=python3

"$PYTHON" -m py_compile "$TMP_SCRIPT" || fail "smoke script syntax check failed"

echo "SADQ_SMOKE_SCRIPT_READY"
echo "READ_ONLY=YES"
echo "NO_ENVELOPE_WILL_BE_CREATED=YES"
echo "NO_NAFATH_REQUEST_WILL_BE_SENT=YES"
echo "NO_SECRET_WILL_BE_PERSISTED=YES"
echo

"$PYTHON" "$TMP_SCRIPT"
RC=$?

rm -f "$TMP_SCRIPT" 2>/dev/null || true

echo
if [[ "$RC" -eq 0 ]]; then
  echo "SADQ_SMOKE_RUN_COMPLETE"
else
  echo "SADQ_SMOKE_RUN_FAILED rc=$RC" >&2
fi
exit "$RC"
