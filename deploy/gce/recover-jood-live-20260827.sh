#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="/opt/pakgat-voucher-system"
SERVICE="pakgat-voucher.service"
CAMPAIGN_SERVICE="pakgat-jood-campaign.service"
EXPECTED_LIVE_HEAD="5bad8bbb61863ee6ba5c7451251fc3b5342f28b2"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
BACKUP_DIR="/opt/pakgat-repair-backups/jood-hotfix-${STAMP}"
RESTART_ATTEMPTED=0

JOOD_FILES=(
  "app/jood_identity.py"
  "app/jood_policy.py"
  "app/jood_whatsapp_campaign.py"
  "app/jood_whatsapp_context.py"
)
FILES=("${JOOD_FILES[@]}" "main.py")

declare -A EXPECTED_HEAD_BLOBS=(
  ["app/jood_identity.py"]="1bc196f163c76ce0b3566dce223076a11729db9e"
  ["app/jood_policy.py"]="772a2e4fef39b6bf63ae2ece0918bce288363a80"
  ["app/jood_whatsapp_campaign.py"]="a69f0d6b2fcfb81b762d349cc314ae79f5750931"
  ["app/jood_whatsapp_context.py"]="78e979d79d739206efc48fad536ea66fb5982324"
)

cd "$APP_DIR"

echo "===== 0. SAFETY GATES — NO CHANGES YET ====="
CURRENT_HEAD="$(git rev-parse HEAD)"
echo "CURRENT_HEAD=$CURRENT_HEAD"
if [[ "$CURRENT_HEAD" != "$EXPECTED_LIVE_HEAD" ]]; then
  echo "ABORT: live HEAD changed since diagnosis. Nothing was modified."
  exit 20
fi
for f in "${JOOD_FILES[@]}"; do
  actual="$(git rev-parse "HEAD:$f")"
  expected="${EXPECTED_HEAD_BLOBS[$f]}"
  echo "$f HEAD_BLOB=$actual"
  if [[ "$actual" != "$expected" ]]; then
    echo "ABORT: $f HEAD blob is not the verified known-good blob. Nothing was modified."
    exit 21
  fi
done
if git show HEAD:main.py | grep -q "BEGIN PAKGAT JOOD MULTICHANNEL"; then
  echo "ABORT: live HEAD main.py unexpectedly contains multichannel bootstrap. Nothing was modified."
  exit 22
fi

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

restore_preincident_disk_state() {
  for f in "${JOOD_FILES[@]}"; do
    if [[ -f "$BACKUP_DIR/$f" ]]; then
      install -D -o pakgat -g pakgat -m 0644 "$BACKUP_DIR/$f" "$APP_DIR/$f"
    fi
  done
  git checkout HEAD -- main.py || true
  chown pakgat:pakgat main.py || true
}

rollback() {
  local rc=$?
  trap - ERR
  echo "===== FAILURE — CONTROLLED ROLLBACK ====="
  if [[ "$RESTART_ATTEMPTED" == "0" ]]; then
    for f in "${FILES[@]}"; do
      if [[ -f "$BACKUP_DIR/$f" ]]; then
        install -D -o pakgat -g pakgat -m 0644 "$BACKUP_DIR/$f" "$APP_DIR/$f"
      fi
    done
    echo "Live application process was not restarted."
  else
    restore_preincident_disk_state
    systemctl restart "$SERVICE" || true
    systemctl is-active "$SERVICE" || true
    echo "Returned to the pre-recovery runtime code shape."
  fi
  echo "Campaign 1 remains paused for safety."
  echo "Backup: $BACKUP_DIR"
  exit "$rc"
}
trap rollback ERR

echo "===== 1. SNAPSHOT CURRENT STATE ====="
git rev-parse HEAD | tee "$BACKUP_DIR/head.txt"
git status --short | tee "$BACKUP_DIR/git-status.txt"
git diff -- "${FILES[@]}" > "$BACKUP_DIR/jood-local.diff" || true
for f in "${FILES[@]}"; do
  if [[ -f "$f" ]]; then
    mkdir -p "$BACKUP_DIR/$(dirname "$f")"
    cp -a "$f" "$BACKUP_DIR/$f"
  fi
done
for f in app/jood_link_card.py app/jood_multichannel.py; do
  if [[ -f "$f" ]]; then
    mkdir -p "$BACKUP_DIR/$(dirname "$f")"
    cp -a "$f" "$BACKUP_DIR/$f"
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
backup_dir = Path(os.environ['BACKUP_DIR'])
with core.SessionLocal() as db:
    row = db.execute(text('SELECT status FROM jood_whatsapp_campaigns WHERE id = 1')).first()
    previous = row[0] if row else 'missing'
    (backup_dir / 'campaign-1-status-before.txt').write_text(str(previous), encoding='utf-8')
    if row:
        db.execute(text("UPDATE jood_whatsapp_campaigns SET status='paused' WHERE id = 1"))
        db.commit()
        print(f'CAMPAIGN_1: {previous} -> paused')
    else:
        print('CAMPAIGN_1: not found')
PY

echo "===== 3. RECORD INCIDENT SIGNATURE ====="
grep -q "send_whatsapp_link_card" app/jood_whatsapp_campaign.py && echo "BAD_LINK_CARD_PATCH=FOUND" || echo "BAD_LINK_CARD_PATCH=NOT_FOUND"
grep -q "def merchant_campaign_choice_action" app/jood_whatsapp_context.py && echo "CHOICE_RESOLVER=PRESENT" || echo "CHOICE_RESOLVER=MISSING"
grep -q "BEGIN PAKGAT JOOD MULTICHANNEL" main.py && echo "MULTICHANNEL_BOOTSTRAP=FOUND" || echo "MULTICHANNEL_BOOTSTRAP=NOT_FOUND"

echo "===== 4. RESTORE ONLY VERIFIED JOOD FILES TO CURRENT LIVE HEAD ====="
git checkout HEAD -- "${FILES[@]}"
chown pakgat:pakgat "${FILES[@]}"

echo "===== 5. VERIFY INCIDENT PATCHES ARE REMOVED ====="
! grep -q "send_whatsapp_link_card" app/jood_whatsapp_campaign.py
grep -q "def merchant_campaign_choice_action" app/jood_whatsapp_context.py
grep -q "is_probable_business_auto_reply" app/jood_identity.py
! grep -q "BEGIN PAKGAT JOOD MULTICHANNEL" main.py
for f in "${JOOD_FILES[@]}"; do
  test "$(git hash-object "$f")" = "${EXPECTED_HEAD_BLOBS[$f]}"
done

echo "===== 6. TARGETED REGRESSION TESTS ====="
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

echo "===== 7. APPROVED MERCHANT COPY CHECK — NO SEND ====="
DATABASE_URL="sqlite:///:memory:" \
ADMIN_PASSWORD="test-only-password" \
ADMIN_SECRET="test-only-admin-secret" \
PUBLIC_BASE_URL="https://example.test" \
WHATSLOOP_API_BASE_URL="https://example.test/api/v1" \
WHATSLOOP_API_TOKEN="test-only-whatsloop-token" \
.venv/bin/python - <<'PY'
from types import SimpleNamespace
from app.jood_outbound import approved_merchant_outreach_message
m = approved_merchant_outreach_message(SimpleNamespace(business_name='اختبار التاجر', display_name=''))
required = [
    'معكم جود من منصة بكجات',
    'استقطاب عملاء جدد في الرياض',
    '1 — أرسلوا التفاصيل',
    '2 — لدي استفسار',
]
missing = [x for x in required if x not in m]
if missing:
    raise SystemExit('MISSING_APPROVED_COPY=' + repr(missing))
print('APPROVED_MERCHANT_COPY=PASS')
PY

echo "===== 8. RESTART APP ====="
RESTART_ATTEMPTED=1
systemctl restart "$SERVICE"
sleep 3
systemctl is-active "$SERVICE"
curl -fsS http://127.0.0.1:8000/health | tee "$BACKUP_DIR/health-after.json"

echo "===== 9. POST-RESTART RUNTIME CHECK ====="
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
from app.jood_whatsapp_context import merchant_campaign_choice_action
from app.jood_outbound import approved_merchant_outreach_message
assert callable(merchant_campaign_choice_action)
assert '1 — أرسلوا التفاصيل' in approved_merchant_outreach_message(type('C', (), {'business_name':'اختبار','display_name':''})())
print('RUNTIME_JOOD_CHECK=PASS')
PY

echo "===== 10. FINAL SAFETY STATE ====="
echo "Campaign 1 intentionally remains PAUSED."
echo "No queued campaign contact was sent by this recovery."
echo "No site/theme, voucher, product, merchant-finance, or env file was changed."
echo "Backup: $BACKUP_DIR"
echo "RECOVERY_COMPLETE=YES"
trap - ERR
