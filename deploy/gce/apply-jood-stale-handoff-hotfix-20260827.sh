#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="/opt/pakgat-voucher-system"
SERVICE="pakgat-voucher.service"
CAMPAIGN_SERVICE="pakgat-jood-campaign.service"
EXPECTED_INBOUND_HASH="736e7733e4a17d732189c45464061ffbfb0a2352"
EXPECTED_CONTEXT_HASH="78e979d79d739206efc48fad536ea66fb5982324"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
BACKUP_DIR="/opt/pakgat-repair-backups/jood-stale-handoff-${STAMP}"
WORKTREE="/tmp/pakgat-jood-stale-handoff-${STAMP}"
LIVE_PATCHED=0
RESTART_ATTEMPTED=0

patch_inbound() {
  local target="$1"
  TARGET_FILE="$target" python3 - <<'PY'
import os
from pathlib import Path

p = Path(os.environ["TARGET_FILE"])
s = p.read_text(encoding="utf-8")

if "def open_handoff_blocks_current_outreach(" in s:
    raise SystemExit("ABORT: stale-handoff helper already exists; refusing to patch twice")

old_import = """    create_handoff,\n    has_open_handoff,\n    load_recent_turns,\n"""
new_import = """    create_handoff,\n    JoodHandoff,\n    load_recent_turns,\n"""
if s.count(old_import) != 1:
    raise SystemExit("ABORT: expected jood_company_ops import shape not found exactly once")
s = s.replace(old_import, new_import, 1)

marker = "\ndef _send_jood_reply(event: InboundEvent, message: str) -> tuple[bool, str]:\n"
helper = r'''

def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def open_handoff_blocks_current_outreach(db: Session, contact_id: int, context_row) -> bool:
    """Only a handoff from the current/newer conversation may pause Jood."""
    handoff = db.scalar(
        select(JoodHandoff)
        .where(
            JoodHandoff.contact_id == contact_id,
            JoodHandoff.status == "open",
        )
        .order_by(JoodHandoff.created_at.desc(), JoodHandoff.id.desc())
        .limit(1)
    )
    if handoff is None:
        return False

    context_updated_at = getattr(context_row, "updated_at", None)
    if context_updated_at is None:
        return True

    return _aware_utc(handoff.created_at) >= _aware_utc(context_updated_at)
'''
if s.count(marker) != 1:
    raise SystemExit("ABORT: send-reply marker not found exactly once")
s = s.replace(marker, helper + marker, 1)

old_gate = """            if has_open_handoff(db, contact.id):\n"""
new_gate = """            from app.jood_whatsapp_context import active_outreach_context\n\n            context_row = active_outreach_context(db, contact.id)\n            if open_handoff_blocks_current_outreach(db, contact.id, context_row):\n"""
if s.count(old_gate) != 1:
    raise SystemExit("ABORT: old unconditional handoff gate not found exactly once")
s = s.replace(old_gate, new_gate, 1)

old_context_import = """            from app.jood_whatsapp_context import (\n                active_outreach_context,\n                inbound_outreach_context,\n"""
new_context_import = """            from app.jood_whatsapp_context import (\n                inbound_outreach_context,\n"""
if s.count(old_context_import) != 1:
    raise SystemExit("ABORT: later outreach import shape not found exactly once")
s = s.replace(old_context_import, new_context_import, 1)

old_context_lookup = """            context_row = active_outreach_context(db, contact.id)\n            state = dict(context_row.state_json or {}) if context_row else {}\n"""
new_context_lookup = """            state = dict(context_row.state_json or {}) if context_row else {}\n"""
if s.count(old_context_lookup) != 1:
    raise SystemExit("ABORT: duplicate context lookup shape not found exactly once")
s = s.replace(old_context_lookup, new_context_lookup, 1)

p.write_text(s, encoding="utf-8")
print(f"PATCHED={p}")
PY
}

load_test_env() {
  export DATABASE_URL="sqlite:///:memory:"
  export ADMIN_PASSWORD="test-only-password"
  export ADMIN_SECRET="test-only-admin-secret"
  export PUBLIC_BASE_URL="https://example.test"
  export WHATSLOOP_API_BASE_URL="https://example.test/api/v1"
  export WHATSLOOP_API_TOKEN="test-only-whatsloop-token"
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
  echo "Campaign remains PAUSED."
  echo "Backup: $BACKUP_DIR"
  exit "$rc"
}
trap rollback ERR

cd "$APP_DIR"

echo "===== 0. READ-ONLY SAFETY GATES ====="
echo "HEAD=$(git rev-parse HEAD)"
CURRENT_INBOUND_HASH="$(git hash-object app/whatsloop_inbound.py)"
CURRENT_CONTEXT_HASH="$(git hash-object app/jood_whatsapp_context.py)"
echo "INBOUND_HASH=$CURRENT_INBOUND_HASH"
echo "CONTEXT_HASH=$CURRENT_CONTEXT_HASH"
test "$CURRENT_INBOUND_HASH" = "$EXPECTED_INBOUND_HASH"
test "$CURRENT_CONTEXT_HASH" = "$EXPECTED_CONTEXT_HASH"
grep -q 'if has_open_handoff(db, contact.id):' app/whatsloop_inbound.py
! grep -q 'def open_handoff_blocks_current_outreach' app/whatsloop_inbound.py
systemctl is-active "$SERVICE"

echo "===== 1. VERIFY CAMPAIGN IS PAUSED — READ ONLY ====="
.venv/bin/python - <<'PY'
import os
from pathlib import Path
for raw in Path('/etc/pakgat/pakgat.env').read_text(encoding='utf-8').splitlines():
    line = raw.strip()
    if not line or line.startswith('#') or '=' not in line:
        continue
    key, value = line.split('=', 1)
    key, value = key.strip(), value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    os.environ[key] = value
from sqlalchemy import text
from app import application as core
with core.SessionLocal() as db:
    row = db.execute(text('SELECT status FROM jood_whatsapp_campaigns WHERE id=1')).first()
    status = row[0] if row else 'missing'
    print('CAMPAIGN_1_STATUS=' + str(status))
    if status != 'paused':
        raise SystemExit('ABORT: campaign 1 is not paused')
PY
systemctl stop "$CAMPAIGN_SERVICE" 2>/dev/null || true

echo "===== 2. PRE-FLIGHT IN ISOLATED WORKTREE ====="
cleanup_worktree
git worktree add --detach "$WORKTREE" FETCH_HEAD >/dev/null
patch_inbound "$WORKTREE/app/whatsloop_inbound.py"
cd "$WORKTREE"
load_test_env
"$APP_DIR/.venv/bin/python" -m py_compile app/whatsloop_inbound.py
"$APP_DIR/.venv/bin/python" -m unittest tests.test_jood_stale_handoff -v
"$APP_DIR/.venv/bin/python" -m unittest discover -s tests -p 'test_*.py' -v
PREVIEW_HASH="$(git hash-object app/whatsloop_inbound.py)"
echo "PREVIEW_PATCHED_HASH=$PREVIEW_HASH"

echo "===== 3. BACKUP LIVE FILE ====="
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
cp -a "$APP_DIR/app/whatsloop_inbound.py" "$BACKUP_DIR/whatsloop_inbound.py"
git -C "$APP_DIR" status --short > "$BACKUP_DIR/git-status-before.txt"
echo "BACKUP_DIR=$BACKUP_DIR"

echo "===== 4. APPLY EXACT SAME PATCH TO LIVE INBOUND ONLY ====="
patch_inbound "$APP_DIR/app/whatsloop_inbound.py"
chown pakgat:pakgat "$APP_DIR/app/whatsloop_inbound.py"
LIVE_PATCHED=1
LIVE_HASH="$(git -C "$APP_DIR" hash-object app/whatsloop_inbound.py)"
echo "LIVE_PATCHED_HASH=$LIVE_HASH"
test "$LIVE_HASH" = "$PREVIEW_HASH"

echo "===== 5. LIVE SOURCE REGRESSION — NO NETWORK SEND ====="
cd "$APP_DIR"
load_test_env
PYTHONPATH="$APP_DIR" "$APP_DIR/.venv/bin/python" "$WORKTREE/tests/test_jood_stale_handoff.py"
"$APP_DIR/.venv/bin/python" -m unittest \
  tests.test_jood_whatsapp_context \
  tests.test_jood_merchant_inbound_safety \
  tests.test_customer_notification_responses \
  tests.test_jood_whatsapp_campaign
"$APP_DIR/.venv/bin/python" -m py_compile app/whatsloop_inbound.py

echo "===== 6. RESTART + HEALTH POLL ====="
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

echo "===== 7. POST-RESTART RUNTIME CHECK ====="
.venv/bin/python - <<'PY'
import os
from pathlib import Path
for raw in Path('/etc/pakgat/pakgat.env').read_text(encoding='utf-8').splitlines():
    line = raw.strip()
    if not line or line.startswith('#') or '=' not in line:
        continue
    key, value = line.split('=', 1)
    key, value = key.strip(), value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    os.environ[key] = value
from app.whatsloop_inbound import open_handoff_blocks_current_outreach
assert callable(open_handoff_blocks_current_outreach)
print('RUNTIME_STALE_HANDOFF_GATE=PASS')
PY
journalctl -u "$SERVICE" --since '2 minutes ago' --no-pager -n 100 | tee "$BACKUP_DIR/restart-log.txt"
if grep -Eiq 'Traceback|ImportError|ModuleNotFoundError|Application startup failed' "$BACKUP_DIR/restart-log.txt"; then
  echo "ERROR: fatal startup signal found"
  false
fi

echo "===== 8. FINAL SAFETY STATE ====="
cleanup_worktree
echo "Campaign 1 remains PAUSED."
echo "No WhatsApp message was sent by this hotfix script."
echo "Only app/whatsloop_inbound.py was changed in the live application."
echo "No handoff row was deleted or closed."
echo "No theme, voucher, product, finance, env, customer, or order data was modified."
echo "Backup: $BACKUP_DIR"
echo "STALE_HANDOFF_HOTFIX_COMPLETE=YES"
trap - ERR
