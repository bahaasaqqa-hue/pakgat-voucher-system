#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="/opt/pakgat-voucher-system"
SERVICE="pakgat-voucher.service"
EXPECTED_LIVE_INBOUND_HASH="343d97072e06d34c02158a8a14ca66e7bc27e942"
EXPECTED_CONTEXT_HASH="78e979d79d739206efc48fad536ea66fb5982324"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
BACKUP_DIR="/opt/pakgat-repair-backups/jood-merchant-followup-${STAMP}"
WORKTREE="/tmp/pakgat-jood-merchant-followup-${STAMP}"
LIVE_PATCHED=0
RESTART_ATTEMPTED=0

load_test_env() {
  export DATABASE_URL="sqlite:///:memory:"
  export ADMIN_PASSWORD="test-only-password"
  export ADMIN_SECRET="test-only-admin-secret"
  export PUBLIC_BASE_URL="https://example.test"
  export WHATSLOOP_API_BASE_URL="https://example.test/api/v1"
  export WHATSLOOP_API_TOKEN="test-only-whatsloop-token"
}

load_prod_env() {
  set -a
  # shellcheck disable=SC1091
  source /etc/pakgat/pakgat.env
  set +a
}

cleanup_worktree() {
  git -C "$APP_DIR" worktree remove --force "$WORKTREE" >/dev/null 2>&1 || true
  rm -rf "$WORKTREE" >/dev/null 2>&1 || true
}

rollback() {
  local rc=$?
  trap - ERR
  echo "===== FAILURE — CONTROLLED ROLLBACK ====="
  if [[ "$LIVE_PATCHED" == "1" && -f "$BACKUP_DIR/whatsloop_inbound.py" ]]; then
    install -o pakgat -g pakgat -m 0644 "$BACKUP_DIR/whatsloop_inbound.py" "$APP_DIR/app/whatsloop_inbound.py"
  fi
  if [[ "$RESTART_ATTEMPTED" == "1" ]]; then
    systemctl restart "$SERVICE" || true
    for _ in $(seq 1 30); do
      if curl -fsS --max-time 2 http://127.0.0.1:8000/health >/dev/null 2>&1; then
        break
      fi
      sleep 1
    done
    systemctl is-active "$SERVICE" || true
  fi
  cleanup_worktree
  echo "Campaign 1 remains PAUSED."
  echo "Backup: $BACKUP_DIR"
  exit "$rc"
}
trap rollback ERR

cd "$APP_DIR"

echo "===== 0. READ-ONLY SAFETY GATES ====="
echo "HEAD=$(git rev-parse HEAD)"
LIVE_HASH="$(git hash-object app/whatsloop_inbound.py)"
CONTEXT_HASH="$(git hash-object app/jood_whatsapp_context.py)"
echo "INBOUND_HASH=$LIVE_HASH"
echo "CONTEXT_HASH=$CONTEXT_HASH"
test "$LIVE_HASH" = "$EXPECTED_LIVE_INBOUND_HASH"
test "$CONTEXT_HASH" = "$EXPECTED_CONTEXT_HASH"
grep -q 'def open_handoff_blocks_current_outreach' app/whatsloop_inbound.py
grep -q 'أرسل لي اسم النشاط والمدينة ونوع الخدمات' app/whatsloop_inbound.py
! grep -q 'إذا تقصد كيف تتم آلية التعاون مع بكجات' app/whatsloop_inbound.py
systemctl is-active "$SERVICE"

echo "===== 1. VERIFY CAMPAIGN IS PAUSED — READ ONLY ====="
load_prod_env
.venv/bin/python - <<'PY'
from sqlalchemy import text
from app import application as core
with core.SessionLocal() as db:
    row = db.execute(text('SELECT status FROM jood_whatsapp_campaigns WHERE id=1')).first()
    status = row[0] if row else 'missing'
    print('CAMPAIGN_1_STATUS=' + str(status))
    if status != 'paused':
        raise SystemExit('ABORT: campaign 1 is not paused')
PY

echo "===== 2. PRE-FLIGHT ON EXACT LIVE INBOUND COPY ====="
cleanup_worktree
git worktree add --detach "$WORKTREE" FETCH_HEAD >/dev/null
cp -a "$APP_DIR/app/whatsloop_inbound.py" "$WORKTREE/app/whatsloop_inbound.py"
cd "$WORKTREE"
python3 deploy/gce/jood_merchant_followup_patch.py app/whatsloop_inbound.py
load_test_env
"$APP_DIR/.venv/bin/python" -m py_compile app/whatsloop_inbound.py deploy/gce/jood_merchant_followup_patch.py
"$APP_DIR/.venv/bin/python" -m unittest tests.test_jood_merchant_followup_fallback -v
"$APP_DIR/.venv/bin/python" -m unittest discover -s tests -p 'test_*.py' -v
PREVIEW_HASH="$(git hash-object app/whatsloop_inbound.py)"
echo "PREVIEW_PATCHED_HASH=$PREVIEW_HASH"
grep -q 'إذا تقصد كيف تتم آلية التعاون مع بكجات' app/whatsloop_inbound.py
! grep -q 'أرسل لي اسم النشاط والمدينة ونوع الخدمات' app/whatsloop_inbound.py

echo "===== 3. BACKUP LIVE INBOUND ====="
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
cp -a "$APP_DIR/app/whatsloop_inbound.py" "$BACKUP_DIR/whatsloop_inbound.py"
git -C "$APP_DIR" status --short > "$BACKUP_DIR/git-status-before.txt"
echo "BACKUP_DIR=$BACKUP_DIR"

echo "===== 4. APPLY ONLY MERCHANT FALLBACK CHANGE ====="
python3 "$WORKTREE/deploy/gce/jood_merchant_followup_patch.py" "$APP_DIR/app/whatsloop_inbound.py"
chown pakgat:pakgat "$APP_DIR/app/whatsloop_inbound.py"
LIVE_PATCHED=1
NEW_LIVE_HASH="$(git -C "$APP_DIR" hash-object app/whatsloop_inbound.py)"
echo "LIVE_PATCHED_HASH=$NEW_LIVE_HASH"
test "$NEW_LIVE_HASH" = "$PREVIEW_HASH"
"$APP_DIR/.venv/bin/python" -m py_compile "$APP_DIR/app/whatsloop_inbound.py"

echo "===== 5. RESTART + HEALTH POLL ====="
RESTART_ATTEMPTED=1
systemctl restart "$SERVICE"
HEALTH_OK=0
for i in $(seq 1 30); do
  if body="$(curl -fsS --max-time 2 http://127.0.0.1:8000/health 2>/dev/null)"; then
    echo "HEALTH_TRY=$i $body"
    HEALTH_OK=1
    break
  fi
  echo "HEALTH_TRY=$i waiting"
  sleep 1
done
test "$HEALTH_OK" = "1"
systemctl is-active "$SERVICE"

echo "===== 6. POST-RESTART RUNTIME CHECK ====="
load_prod_env
.venv/bin/python - <<'PY'
from pathlib import Path
from app.whatsloop_inbound import open_handoff_blocks_current_outreach
source = Path('/opt/pakgat-voucher-system/app/whatsloop_inbound.py').read_text(encoding='utf-8')
assert callable(open_handoff_blocks_current_outreach)
assert 'إذا تقصد كيف تتم آلية التعاون مع بكجات' in source
assert 'أرسل لي اسم النشاط والمدينة ونوع الخدمات' not in source
print('RUNTIME_STALE_HANDOFF_GATE=PASS')
print('RUNTIME_MERCHANT_FOLLOWUP_FALLBACK=PASS')
PY
journalctl -u "$SERVICE" --since '2 minutes ago' --no-pager -n 100 | tee "$BACKUP_DIR/restart-log.txt"
if grep -Eiq 'Traceback|ImportError|ModuleNotFoundError|Application startup failed' "$BACKUP_DIR/restart-log.txt"; then
  echo "ERROR: fatal startup signal found"
  false
fi

echo "===== 7. FINAL SAFETY STATE ====="
load_prod_env
.venv/bin/python - <<'PY'
from sqlalchemy import text
from app import application as core
with core.SessionLocal() as db:
    row = db.execute(text('SELECT status FROM jood_whatsapp_campaigns WHERE id=1')).first()
    status = row[0] if row else 'missing'
    print('CAMPAIGN_1_FINAL_STATUS=' + str(status))
    if status != 'paused':
        raise SystemExit('ERROR: campaign 1 changed status unexpectedly')
PY
cleanup_worktree
echo "Campaign 1 remains PAUSED."
echo "No WhatsApp message was sent by this hotfix script."
echo "Only app/whatsloop_inbound.py was changed in the live application."
echo "The existing stale-handoff fix was preserved."
echo "No handoff row was deleted or closed."
echo "No theme, voucher, product, finance, env, customer, or order data was modified."
echo "Backup: $BACKUP_DIR"
echo "MERCHANT_FOLLOWUP_HOTFIX_COMPLETE=YES"
trap - ERR
