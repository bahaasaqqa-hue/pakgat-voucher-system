#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="/opt/pakgat-voucher-system"
SERVICE="pakgat-voucher.service"
CAMPAIGN_SERVICE="pakgat-jood-campaign.service"
GOOD_COMMIT="91e0870293267b5bcfdddc5d025b2109856ac63a"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
BACKUP_DIR="/opt/pakgat-repair-backups/jood-hotfix-${STAMP}"
STAGE_DIR="/tmp/pakgat-jood-good-${STAMP}"
RESTART_ATTEMPTED=0

JOOD_FILES=(
  "app/jood_identity.py"
  "app/jood_policy.py"
  "app/jood_whatsapp_campaign.py"
  "app/jood_whatsapp_context.py"
  "app/jood_outbound.py"
)

declare -A GOOD_BLOBS=(
  ["app/jood_identity.py"]="1bc196f163c76ce0b3566dce223076a11729db9e"
  ["app/jood_policy.py"]="772a2e4fef39b6bf63ae2ece0918bce288363a80"
  ["app/jood_whatsapp_campaign.py"]="a69f0d6b2fcfb81b762d349cc314ae79f5750931"
  ["app/jood_whatsapp_context.py"]="78e979d79d739206efc48fad536ea66fb5982324"
  ["app/jood_outbound.py"]="f9670b92d3bfadf9997d6cda9ff4fcfe522cdb26"
)

cd "$APP_DIR"

echo "===== 0. READ-ONLY SAFETY + STAGE KNOWN-GOOD FILES ====="
CURRENT_HEAD="$(git rev-parse HEAD)"
echo "CURRENT_HEAD=$CURRENT_HEAD"

git fetch origin gce-migration >/dev/null 2>&1
if ! git cat-file -e "${GOOD_COMMIT}^{commit}" 2>/dev/null; then
  echo "ABORT: pinned known-good commit is unavailable. Nothing was modified."
  exit 20
fi

mkdir -p "$STAGE_DIR"
chmod 700 "$STAGE_DIR"
for f in "${JOOD_FILES[@]}"; do
  mkdir -p "$STAGE_DIR/$(dirname "$f")"
  git show "${GOOD_COMMIT}:${f}" > "$STAGE_DIR/$f"
  staged_hash="$(git hash-object "$STAGE_DIR/$f")"
  current_hash="$(git hash-object "$f")"
  echo "$f CURRENT=$current_hash GOOD=$staged_hash"
  if [[ "$staged_hash" != "${GOOD_BLOBS[$f]}" ]]; then
    echo "ABORT: pinned good file $f does not match verified blob. Nothing was modified."
    rm -rf "$STAGE_DIR"
    exit 21
  fi
done

INCIDENT_SCORE=0
grep -q "send_whatsapp_link_card" app/jood_whatsapp_campaign.py && { echo "SIGNATURE: bad link-card campaign patch present"; INCIDENT_SCORE=$((INCIDENT_SCORE+1)); } || true
grep -q "def merchant_campaign_choice_action" app/jood_whatsapp_context.py || { echo "SIGNATURE: merchant choice resolver missing"; INCIDENT_SCORE=$((INCIDENT_SCORE+1)); }
grep -q "is_probable_business_auto_reply" app/jood_identity.py || { echo "SIGNATURE: business auto-reply filter missing"; INCIDENT_SCORE=$((INCIDENT_SCORE+1)); }
if [[ "$INCIDENT_SCORE" -lt 2 ]]; then
  echo "ABORT: current Jood state no longer matches the diagnosed incident strongly enough. Nothing was modified."
  rm -rf "$STAGE_DIR"
  exit 22
fi

grep -q '/admin/company/jood/whatsapp/send-now' app/jood_outbound.py || {
  echo "ABORT: individual send-now route is missing from current app. Nothing was modified."
  rm -rf "$STAGE_DIR"
  exit 23
}

echo "SAFETY_GATES=PASS"

mkdir -p "$BACKUP_DIR/files"
chmod 700 "$BACKUP_DIR"

rollback() {
  local rc=$?
  trap - ERR
  echo "===== FAILURE — CONTROLLED ROLLBACK ====="
  if [[ -d "$BACKUP_DIR/files" ]]; then
    for f in "${JOOD_FILES[@]}" main.py; do
      if [[ -f "$BACKUP_DIR/files/$f" ]]; then
        install -D -o pakgat -g pakgat -m 0644 "$BACKUP_DIR/files/$f" "$APP_DIR/$f"
      fi
    done
  fi
  if [[ "$RESTART_ATTEMPTED" == "1" ]]; then
    systemctl restart "$SERVICE" || true
    systemctl is-active "$SERVICE" || true
  fi
  rm -rf "$STAGE_DIR" || true
  echo "Campaign 1 remains paused for safety."
  echo "Backup: $BACKUP_DIR"
  exit "$rc"
}
trap rollback ERR

echo "===== 1. BACKUP CURRENT PRODUCTION FILES ====="
printf '%s\n' "$CURRENT_HEAD" > "$BACKUP_DIR/head.txt"
git status --short | tee "$BACKUP_DIR/git-status.txt"
git diff > "$BACKUP_DIR/working-tree.diff" || true
for f in "${JOOD_FILES[@]}" main.py; do
  if [[ -f "$f" ]]; then
    mkdir -p "$BACKUP_DIR/files/$(dirname "$f")"
    cp -a "$f" "$BACKUP_DIR/files/$f"
  fi
done
for f in app/jood_link_card.py app/jood_multichannel.py; do
  if [[ -f "$f" ]]; then
    mkdir -p "$BACKUP_DIR/files/$(dirname "$f")"
    cp -a "$f" "$BACKUP_DIR/files/$f"
  fi
done
echo "BACKUP_DIR=$BACKUP_DIR"

echo "===== 2. FREEZE MERCHANT CAMPAIGN ====="
systemctl stop "$CAMPAIGN_SERVICE" 2>/dev/null || true
BACKUP_DIR="$BACKUP_DIR" .venv/bin/python - <<'PY'
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
backup = Path(os.environ['BACKUP_DIR'])
with core.SessionLocal() as db:
    row = db.execute(text('SELECT status FROM jood_whatsapp_campaigns WHERE id=1')).first()
    previous = row[0] if row else 'missing'
    (backup / 'campaign-1-status-before.txt').write_text(str(previous), encoding='utf-8')
    if row:
        db.execute(text("UPDATE jood_whatsapp_campaigns SET status='paused' WHERE id=1"))
        db.commit()
        print(f'CAMPAIGN_1: {previous} -> paused')
    else:
        print('CAMPAIGN_1: not found')
PY

echo "===== 3. INSTALL ONLY PINNED KNOWN-GOOD JOOD FILES ====="
for f in "${JOOD_FILES[@]}"; do
  install -D -o pakgat -g pakgat -m 0644 "$STAGE_DIR/$f" "$APP_DIR/$f"
done

python3 - <<'PY'
from pathlib import Path
p = Path('main.py')
s = p.read_text(encoding='utf-8')
start = '# BEGIN PAKGAT JOOD MULTICHANNEL'
end = '# END PAKGAT JOOD MULTICHANNEL'
if start in s:
    if end not in s:
        raise SystemExit('multichannel start marker exists without end marker')
    before, rest = s.split(start, 1)
    _block, after = rest.split(end, 1)
    p.write_text((before.rstrip() + '\n\n' + after.lstrip('\n')), encoding='utf-8')
    print('MAIN_MULTICHANNEL_BLOCK=REMOVED')
else:
    print('MAIN_MULTICHANNEL_BLOCK=NOT_PRESENT')
PY
chown pakgat:pakgat main.py

echo "===== 4. STATIC VERIFICATION ====="
for f in "${JOOD_FILES[@]}"; do
  actual="$(git hash-object "$f")"
  echo "$f RESTORED=$actual"
  test "$actual" = "${GOOD_BLOBS[$f]}"
done
! grep -q "send_whatsapp_link_card" app/jood_whatsapp_campaign.py
grep -q "def merchant_campaign_choice_action" app/jood_whatsapp_context.py
grep -q "is_probable_business_auto_reply" app/jood_identity.py
grep -q '/admin/company/jood/whatsapp/send-now' app/jood_outbound.py
! grep -q '^# BEGIN PAKGAT JOOD MULTICHANNEL$' main.py

echo "===== 5. TARGETED REGRESSION TESTS — NO WHATSAPP SEND ====="
DATABASE_URL="sqlite:///:memory:" \
ADMIN_PASSWORD="test-only-password" \
ADMIN_SECRET="test-only-admin-secret" \
PUBLIC_BASE_URL="https://example.test" \
WHATSLOOP_API_BASE_URL="https://example.test/api/v1" \
WHATSLOOP_API_TOKEN="test-only-whatsloop-token" \
.venv/bin/python -m unittest \
  tests.test_jood_whatsapp_context \
  tests.test_jood_merchant_inbound_safety \
  tests.test_jood_whatsapp_campaign

.venv/bin/python -m py_compile \
  app/jood_identity.py \
  app/jood_policy.py \
  app/jood_whatsapp_campaign.py \
  app/jood_whatsapp_context.py \
  app/jood_outbound.py \
  main.py

echo "===== 6. BEHAVIOR CHECKS — NO NETWORK SEND ====="
DATABASE_URL="sqlite:///:memory:" \
ADMIN_PASSWORD="test-only-password" \
ADMIN_SECRET="test-only-admin-secret" \
PUBLIC_BASE_URL="https://example.test" \
WHATSLOOP_API_BASE_URL="https://example.test/api/v1" \
WHATSLOOP_API_TOKEN="test-only-whatsloop-token" \
.venv/bin/python - <<'PY'
from types import SimpleNamespace
from app.jood_outbound import approved_merchant_outreach_message
from app.jood_whatsapp_context import merchant_campaign_choice_action
m = approved_merchant_outreach_message(SimpleNamespace(business_name='اختبار التاجر', display_name=''))
for required in ('معكم جود من منصة بكجات', 'استقطاب عملاء جدد في الرياض', '1 — أرسلوا التفاصيل', '2 — لدي استفسار'):
    assert required in m, required
ctx = SimpleNamespace(state_json={'direction':'outbound','persona':'outbound_merchant_acquisition'})
a = merchant_campaign_choice_action('1', 'merchant', ctx)
assert a is not None
assert 'أبشروا بالسعد' in a.reply
print('APPROVED_MERCHANT_OPENING=PASS')
print('MERCHANT_CHOICE_1_FLOW=PASS')
PY

echo "===== 7. RESTART APP + POLL HEALTH ====="
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
if [[ "$HEALTH_OK" != "1" ]]; then
  echo "ERROR: health endpoint did not become ready within 30 seconds"
  systemctl status "$SERVICE" --no-pager -l || true
  journalctl -u "$SERVICE" --since '2 minutes ago' --no-pager -n 120 || true
  false
fi
systemctl is-active "$SERVICE"
echo "HEALTH_AFTER_RESTART=PASS"

echo "===== 8. POST-RESTART RUNTIME + LOG CHECK ====="
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
from app.jood_whatsapp_context import merchant_campaign_choice_action
from app.jood_outbound import approved_merchant_outreach_message
assert callable(merchant_campaign_choice_action)
assert '1 — أرسلوا التفاصيل' in approved_merchant_outreach_message(type('C', (), {'business_name':'اختبار','display_name':''})())
print('RUNTIME_JOOD_IMPORTS=PASS')
PY
journalctl -u "$SERVICE" --since '2 minutes ago' --no-pager -n 80 | tee "$BACKUP_DIR/restart-log.txt"
if grep -Eiq 'Traceback|ImportError|ModuleNotFoundError|Application startup failed' "$BACKUP_DIR/restart-log.txt"; then
  echo "ERROR: restart log contains a fatal application signal"
  false
fi

echo "===== 9. FINAL SAFETY STATE ====="
rm -rf "$STAGE_DIR"
echo "Campaign 1 intentionally remains PAUSED."
echo "No WhatsApp message was sent by this recovery script."
echo "Only five Jood Python files were restored from pinned commit $GOOD_COMMIT."
echo "main.py was preserved except for removal of the exact Jood multichannel marker block if present."
echo "No theme/site content, voucher, product, merchant-finance, env, or customer/order data was modified."
echo "Backup: $BACKUP_DIR"
echo "RECOVERY_COMPLETE=YES"
trap - ERR
