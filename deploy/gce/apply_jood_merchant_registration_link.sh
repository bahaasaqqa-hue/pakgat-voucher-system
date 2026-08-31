#!/usr/bin/env bash
set -u

REPO=/opt/pakgat-voucher-system
SERVICE=pakgat-voucher
TARGET=de9f9e6e2d1b46a3a309821e23901dd4247d5da0
LIVE="$REPO/app/jood_whatsapp_context.py"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="/tmp/jood-whatsapp-context-before-registration-link-$STAMP.py"
TARGET_COPY="/tmp/jood-whatsapp-context-target-$STAMP.py"
BEFORE_HASHES="/tmp/jood-registration-link-protected-before-$STAMP.sha256"
AFTER_HASHES="/tmp/jood-registration-link-protected-after-$STAMP.sha256"

fail() {
  echo "DEPLOY_FAILED: $*" >&2
  exit 1
}

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  fail "Run as root"
fi

[[ -d "$REPO/.git" ]] || fail "Repository not found: $REPO"
[[ -f "$LIVE" ]] || fail "Live Jood context file not found: $LIVE"
command -v sha256sum >/dev/null 2>&1 || fail "sha256sum is required"
command -v curl >/dev/null 2>&1 || fail "curl is required"

PROTECTED=(
  "$REPO/main.py"
  "$REPO/app/admin_theme_core.py"
  "$REPO/app/jood_identity.py"
  "$REPO/app/jood_outbound.py"
  "$REPO/app/jood_policy.py"
  "$REPO/app/jood_whatsapp_settings.py"
  "$REPO/app/jood_whatsapp_campaign.py"
  "$REPO/app/jood_whatsapp_campaign_ui.py"
  "$REPO/app/whatsloop_inbound.py"
  "$REPO/app/jood_whatsapp_buttons.py"
  "/etc/pakgat/pakgat.env"
)

capture_hashes() {
  local out="$1"
  : > "$out"
  local f
  for f in "${PROTECTED[@]}"; do
    if [[ -f "$f" ]]; then
      sha256sum "$f" >> "$out"
    else
      printf 'MISSING  %s\n' "$f" >> "$out"
    fi
  done
}

cp -a "$LIVE" "$BACKUP" || fail "Could not create Jood context backup"
capture_hashes "$BEFORE_HASHES"

rollback() {
  echo "ROLLBACK_START"
  cp -a "$BACKUP" "$LIVE" 2>/dev/null || true
  systemctl restart "$SERVICE" >/dev/null 2>&1 || true
  echo "ROLLBACK_DONE"
}

sudo -u pakgat git -C "$REPO" fetch origin gce-migration || {
  rollback
  fail "git fetch failed"
}

sudo -u pakgat git -C "$REPO" cat-file -e "$TARGET^{commit}" || {
  rollback
  fail "target commit is unavailable"
}

sudo -u pakgat git -C "$REPO" show "$TARGET:app/jood_whatsapp_context.py" > "$TARGET_COPY" || {
  rollback
  fail "could not read approved target text"
}

python3 - "$LIVE" "$TARGET_COPY" <<'PY' || {
import hashlib
import re
import sys
from pathlib import Path

live_path = Path(sys.argv[1])
target_path = Path(sys.argv[2])
live = live_path.read_text(encoding="utf-8")
target = target_path.read_text(encoding="utf-8")
pattern = re.compile(r'(?ms)^MERCHANT_CAMPAIGN_CHOICE_ONE_REPLY = """.*?"""')

live_matches = list(pattern.finditer(live))
target_matches = list(pattern.finditer(target))
if len(live_matches) != 1:
    raise SystemExit(f"expected exactly one live choice-one reply constant, found {len(live_matches)}")
if len(target_matches) != 1:
    raise SystemExit(f"expected exactly one target choice-one reply constant, found {len(target_matches)}")

lm = live_matches[0]
tm = target_matches[0]
new_block = tm.group(0)
if "https://merchant.pakgat.com/merchant/register" not in new_block:
    raise SystemExit("approved target reply is missing merchant registration URL")
if "التحقق عبر نفاذ" not in new_block:
    raise SystemExit("approved target reply is missing Nafath wording")
if "أبشروا بالسعد 🙌" not in lm.group(0):
    raise SystemExit("live approved details reply does not match expected campaign copy")

prefix = live[:lm.start()]
suffix = live[lm.end():]
new_text = prefix + new_block + suffix

# Idempotent when already applied.
if new_text != live:
    live_path.write_text(new_text, encoding="utf-8")

after = live_path.read_text(encoding="utf-8")
after_matches = list(pattern.finditer(after))
if len(after_matches) != 1:
    raise SystemExit("choice-one reply constant count changed unexpectedly")
am = after_matches[0]
if after[:am.start()] != prefix or after[am.end():] != suffix:
    raise SystemExit("bytes outside the approved reply constant changed")
if am.group(0) != new_block:
    raise SystemExit("approved reply constant was not installed exactly")

print("JOOD_REPLY_PATCH_SCOPE_OK")
print("PREFIX_SHA256=" + hashlib.sha256(prefix.encode("utf-8")).hexdigest())
print("SUFFIX_SHA256=" + hashlib.sha256(suffix.encode("utf-8")).hexdigest())
PY
  rollback
  fail "bounded Jood reply patch failed"
}

sudo -u pakgat "$REPO/.venv/bin/python" -m py_compile "$LIVE" || {
  rollback
  fail "Jood context compile failed"
}

# Runtime behavior check without writing settings, campaign rows, or database state.
(
  set -a
  source /etc/pakgat/pakgat.env 2>/dev/null || true
  set +a
  cd "$REPO" || exit 1
  "$REPO/.venv/bin/python" - <<'PY'
from app.jood_whatsapp_context import JoodWhatsAppContext, merchant_campaign_choice_action

ctx = JoodWhatsAppContext(
    contact_id=0,
    mode="merchant",
    objective="merchant partnership",
    source="campaign",
    active=True,
    state_json={
        "direction": "outbound",
        "persona": "outbound_merchant_acquisition",
        "status": "active",
    },
)
details = merchant_campaign_choice_action("أرسلوا التفاصيل", "merchant", ctx)
question = merchant_campaign_choice_action("لدي استفسار", "merchant", ctx)
assert details is not None
assert "https://merchant.pakgat.com/merchant/register" in details.reply
assert "التحقق عبر نفاذ" in details.reply
assert question is not None
assert question.reply == ""
assert question.handoff_details == "merchant_campaign_silent_human_takeover"
print("JOOD_CHOICE_BEHAVIOR_OK")
PY
) || {
  rollback
  fail "Jood choice behavior verification failed"
}

capture_hashes "$AFTER_HASHES"
if ! cmp -s "$BEFORE_HASHES" "$AFTER_HASHES"; then
  echo "PROTECTED_FILE_CHANGE_DETECTED" >&2
  diff -u "$BEFORE_HASHES" "$AFTER_HASHES" || true
  rollback
  fail "a protected settings/routing file changed"
fi

echo "PROTECTED_SETTINGS_AND_ROUTING_UNCHANGED"

systemctl restart "$SERVICE" || {
  rollback
  fail "service restart failed"
}

READY=0
for _ in {1..20}; do
  if systemctl is-active --quiet "$SERVICE"; then
    if curl -fsS http://127.0.0.1:8000/merchant >/dev/null 2>&1; then
      READY=1
      break
    fi
  fi
  sleep 1
done

if [[ "$READY" -ne 1 ]]; then
  systemctl status "$SERVICE" --no-pager || true
  journalctl -u "$SERVICE" -n 60 --no-pager || true
  rollback
  fail "service health check failed"
fi

# Recheck protected files after restart as well.
capture_hashes "$AFTER_HASHES"
if ! cmp -s "$BEFORE_HASHES" "$AFTER_HASHES"; then
  diff -u "$BEFORE_HASHES" "$AFTER_HASHES" || true
  rollback
  fail "protected settings/routing file changed after restart"
fi

echo "JOOD_MERCHANT_REGISTRATION_LINK_DEPLOY_OK"
echo "BACKUP=$BACKUP"
echo "CHANGED_ONLY=app/jood_whatsapp_context.py::MERCHANT_CAMPAIGN_CHOICE_ONE_REPLY"
