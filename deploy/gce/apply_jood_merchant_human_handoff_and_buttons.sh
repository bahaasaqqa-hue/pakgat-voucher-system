#!/usr/bin/env bash
set -Eeuo pipefail

APP=/opt/pakgat-voucher-system
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_ROOT="/opt/pakgat-repair-backups/jood-merchant-human-handoff-${STAMP}"
STAGE="$(mktemp -d /tmp/pakgat-jood-merchant-human-handoff.XXXXXX)"
CONTEXT="$APP/app/jood_whatsapp_context.py"
INBOUND="$APP/app/whatsloop_inbound.py"
BUTTONS="$APP/app/jood_whatsapp_buttons.py"
ENV_FILE=/etc/pakgat/pakgat.env
LINK_CARD="$APP/app/jood_link_card.py"
OUTBOUND="$APP/app/jood_outbound.py"
CAMPAIGN="$APP/app/jood_whatsapp_campaign.py"
APPLIED=0

cleanup() {
  rm -rf "$STAGE"
}

sha_file() {
  sha256sum "$1" | awk '{print $1}'
}

rollback() {
  local exit_code="${1:-1}"
  if [[ "$APPLIED" == 1 && -d "$BACKUP_ROOT" ]]; then
    echo "ROLLBACK=START"
    cp -f "$BACKUP_ROOT/jood_whatsapp_context.py" "$CONTEXT"
    cp -f "$BACKUP_ROOT/whatsloop_inbound.py" "$INBOUND"
    cp -f "$BACKUP_ROOT/jood_whatsapp_buttons.py" "$BUTTONS"
    chown pakgat:pakgat "$CONTEXT" "$INBOUND" "$BUTTONS"
    systemctl restart pakgat-voucher.service || true
    echo "ROLLBACK=COMPLETE"
  fi
  cleanup
  exit "$exit_code"
}

trap 'rollback $?' ERR
trap cleanup EXIT

echo "===== 0. GUARDED PREFLIGHT ====="
[[ "$(id -u)" == 0 ]]
for file in "$CONTEXT" "$INBOUND" "$BUTTONS" "$ENV_FILE" "$LINK_CARD" "$OUTBOUND" "$CAMPAIGN"; do
  [[ -f "$file" ]] || { echo "MISSING=$file" >&2; exit 1; }
done
systemctl is-active --quiet pakgat-voucher.service
curl -fsS --max-time 10 https://voucher.pakgat.com/health >/dev/null

# These are the exact production fingerprints reported by the read-only
# diagnostic on 2026-08-30. Stop instead of patching an unknown revision.
[[ "$(sha_file "$CONTEXT")" == "9f0d118084eeb0a6d3597d9252e1b5981df6900c4d9c097f9c800d8a7a8ba276" ]]
[[ "$(sha_file "$INBOUND")" == "4862929d70d1822d49008a01d68c9901c0d8d7b306af6ed5856bba9e0454d751" ]]
[[ "$(sha_file "$BUTTONS")" == "2dad729ad673df80e8fae7e76ade3f621632759b1a1cee79c36e37c313146c40" ]]

ENV_SHA="$(sha_file "$ENV_FILE")"
LINK_CARD_SHA="$(sha_file "$LINK_CARD")"
OUTBOUND_SHA="$(sha_file "$OUTBOUND")"
CAMPAIGN_SHA="$(sha_file "$CAMPAIGN")"
echo "PREFLIGHT=PASS"

echo "===== 1. ISOLATED STAGE ====="
mkdir -p "$STAGE/app"
cp -a "$CONTEXT" "$STAGE/app/jood_whatsapp_context.py"
cp -a "$INBOUND" "$STAGE/app/whatsloop_inbound.py"
cp -a "$BUTTONS" "$STAGE/app/jood_whatsapp_buttons.py"

"$APP/.venv/bin/python" - "$STAGE" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1]) / "app"
context_path = root / "jood_whatsapp_context.py"
inbound_path = root / "whatsloop_inbound.py"
buttons_path = root / "jood_whatsapp_buttons.py"

context = context_path.read_text(encoding="utf-8")
start = context.index("def merchant_campaign_choice_action(")
end = context.index("\ndef inbound_outreach_context", start)
replacement = '''def merchant_campaign_choice_action(
    message: str,
    mode: str,
    context_row: JoodWhatsAppContext | None,
) -> MerchantCampaignChoiceAction | None:
    if str(mode or "").strip().lower() != "merchant" or context_row is None:
        return None

    state = dict(context_row.state_json or {})
    if state.get("direction") != "outbound" or state.get("persona") != "outbound_merchant_acquisition":
        return None

    choice = " ".join(str(message or "").strip().split())
    sends_approved_details = choice in {
        "1",
        "١",
        "أرسلوا التفاصيل",
        "ارسلوا التفاصيل",
    }

    return MerchantCampaignChoiceAction(
        reply=MERCHANT_CAMPAIGN_CHOICE_ONE_REPLY if sends_approved_details else "",
        handoff_kind="merchant_partnership",
        handoff_details=(
            "merchant_campaign_details_shared_ready_for_partnership_manager"
            if sends_approved_details
            else "merchant_campaign_silent_human_takeover"
        ),
        next_stage="handed_off",
    )

'''
context_path.write_text(context[:start] + replacement + context[end + 1 :], encoding="utf-8")

inbound = inbound_path.read_text(encoding="utf-8")
start = inbound.index("            merchant_choice = merchant_campaign_choice_action(")
end = inbound.index("            allow_handoff_claim = False", start)
replacement = '''            merchant_choice = merchant_campaign_choice_action(
                normalized.text or "",
                mode,
                context_row,
            )
            if merchant_choice is not None:
                ok = True
                provider_status = "silent human handoff; no automatic reply"
                if merchant_choice.reply:
                    ok, provider_status = await asyncio.to_thread(
                        _send_jood_reply,
                        normalized,
                        merchant_choice.reply,
                    )
                if ok and merchant_choice.reply:
                    append_turn(
                        db,
                        contact.id,
                        "whatsapp",
                        "assistant",
                        merchant_choice.reply,
                        conversation_key,
                    )
                if ok:
                    create_handoff(
                        db,
                        contact.id,
                        merchant_choice.handoff_kind,
                        details=merchant_choice.handoff_details,
                    )
                    update_outreach_state(
                        db,
                        contact.id,
                        next_stage=merchant_choice.next_stage,
                        last_commitment="",
                        status="handed_off",
                    )
                event_name = (
                    "jood_merchant_campaign_handoff_sent"
                    if ok and merchant_choice.reply
                    else "jood_merchant_campaign_handoff_silent"
                    if ok
                    else "jood_merchant_campaign_handoff_failed"
                )
                core.log_event(
                    db,
                    event_name,
                    details=(
                        f"contact_id={contact.id}; channel={normalized.channel_id or '-'}; "
                        f"provider={provider_status[:250]}"
                    ),
                )
                reply_state = (
                    "merchant_handoff_sent"
                    if ok and merchant_choice.reply
                    else "merchant_handoff_silent"
                    if ok
                    else "merchant_handoff_failed"
                )
                return JSONResponse(
                    {
                        "success": True,
                        "duplicate": False,
                        "event_id": row.id,
                        "jood_reply": reply_state,
                    }
                )

'''
inbound_path.write_text(inbound[:start] + replacement + inbound[end:], encoding="utf-8")

buttons = buttons_path.read_text(encoding="utf-8")
replacements = (
    ("MERCHANT_TEMPLATE_BUTTONS", "MERCHANT_CHOICE_BUTTONS"),
    ('{"type": "quickReply", "text": "أرسلوا التفاصيل"}', '{"id": "1", "text": "أرسلوا التفاصيل"}'),
    ('{"type": "quickReply", "text": "لدي استفسار"}', '{"id": "2", "text": "لدي استفسار"}'),
    ('"template_buttons": [dict(button) for button in MERCHANT_CHOICE_BUTTONS]', '"buttons": [dict(button) for button in MERCHANT_CHOICE_BUTTONS]'),
    ('_post_whatsloop("/messages/send-template", payload)', '_post_whatsloop("/messages/send-buttons", payload)'),
    ('f"template HTTP {status}: {response_text}"', 'f"buttons HTTP {status}: {response_text}"'),
)
for old, new in replacements:
    count = buttons.count(old)
    if count == 0:
        raise SystemExit(f"BUTTON_PATCH_ANCHOR_MISSING:{old}")
    buttons = buttons.replace(old, new)
if "/messages/send-template" in buttons or '"template_buttons"' in buttons:
    raise SystemExit("TEMPLATE_TRANSPORT_REMAINS")
buttons_path.write_text(buttons, encoding="utf-8")
print("STAGE_PATCH=PASS")
PY

echo "===== 2. STAGE COMPILE / OFFLINE TESTS ====="
"$APP/.venv/bin/python" -m py_compile \
  "$STAGE/app/jood_whatsapp_context.py" \
  "$STAGE/app/whatsloop_inbound.py" \
  "$STAGE/app/jood_whatsapp_buttons.py"

"$APP/.venv/bin/python" - "$STAGE" <<'PY'
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import ast
import importlib.util
import sys

root = Path(sys.argv[1]) / "app"
context_path = root / "jood_whatsapp_context.py"
tree = ast.parse(context_path.read_text(encoding="utf-8"))
wanted = {
    "MERCHANT_CAMPAIGN_CHOICE_ONE_REPLY",
    "MerchantCampaignChoiceAction",
    "merchant_campaign_choice_action",
}
body = [node for node in tree.body if isinstance(node, ast.ImportFrom) and node.module == "__future__"]
for node in tree.body:
    name = getattr(node, "name", None)
    if isinstance(node, ast.Assign):
        names = {target.id for target in node.targets if isinstance(target, ast.Name)}
        if names & wanted:
            body.append(node)
    elif name in wanted:
        body.append(node)
module = ast.Module(body=body, type_ignores=[])
ast.fix_missing_locations(module)
namespace = {"dataclass": dataclass}
exec(compile(module, str(context_path), "exec"), namespace)
resolve = namespace["merchant_campaign_choice_action"]
context = SimpleNamespace(state_json={"direction": "outbound", "persona": "outbound_merchant_acquisition"})

details = resolve("أرسلوا التفاصيل", "merchant", context)
assert details is not None and "أبشروا بالسعد" in details.reply
legacy_details = resolve("1", "merchant", context)
assert legacy_details is not None and legacy_details.reply == details.reply
question = resolve("لدي استفسار", "merchant", context)
assert question is not None and question.reply == ""
legacy_question = resolve("2", "merchant", context)
assert legacy_question is not None and legacy_question.reply == ""
unexpected = resolve("ممكن توضحون أكثر؟", "merchant", context)
assert unexpected is not None and unexpected.reply == ""
assert resolve("مرحبا", "customer", context) is None

inbound = (root / "whatsloop_inbound.py").read_text(encoding="utf-8")
block = inbound[inbound.index("            merchant_choice = merchant_campaign_choice_action("):inbound.index("            allow_handoff_claim = False")]
assert "if merchant_choice.reply:" in block
assert "merchant_handoff_silent" in block
assert block.index("if merchant_choice.reply:") < block.index("_send_jood_reply")
assert "create_handoff(" in block
assert "return JSONResponse(" in block

buttons_path = root / "jood_whatsapp_buttons.py"
spec = importlib.util.spec_from_file_location("stage_buttons", buttons_path)
buttons = importlib.util.module_from_spec(spec)
spec.loader.exec_module(buttons)
message = "رسالة التاجر" + buttons.MERCHANT_CHOICE_SUFFIX
with patch.object(buttons, "resolve_channel_id", return_value=5):
    payload = buttons.build_merchant_template_payload("966500000000", message)
assert payload == {
    "channel_id": 5,
    "to": "966500000000",
    "text": "رسالة التاجر",
    "buttons": [
        {"id": "1", "text": "أرسلوا التفاصيل"},
        {"id": "2", "text": "لدي استفسار"},
    ],
}
captured = {}
def fake_post(endpoint, sent):
    captured["endpoint"] = endpoint
    captured["payload"] = sent
    return 200, b'{"success":true}'
with patch.object(buttons, "resolve_channel_id", return_value=5), patch.object(buttons, "_post_whatsloop", side_effect=fake_post):
    ok, provider = buttons.send_merchant_choice_template("966500000000", message)
assert ok and captured["endpoint"] == "/messages/send-buttons"
assert captured["payload"] == payload
assert "buttons HTTP 200" in provider
print("SILENT_HANDOFF_TESTS=PASS")
print("BUTTON_TRANSPORT_TESTS=PASS")
PY

echo "===== 3. BACKUP ====="
mkdir -p "$BACKUP_ROOT"
cp -a "$CONTEXT" "$BACKUP_ROOT/jood_whatsapp_context.py"
cp -a "$INBOUND" "$BACKUP_ROOT/whatsloop_inbound.py"
cp -a "$BUTTONS" "$BACKUP_ROOT/jood_whatsapp_buttons.py"
printf '%s\n' \
  "ENV_SHA=$ENV_SHA" \
  "LINK_CARD_SHA=$LINK_CARD_SHA" \
  "OUTBOUND_SHA=$OUTBOUND_SHA" \
  "CAMPAIGN_SHA=$CAMPAIGN_SHA" \
  > "$BACKUP_ROOT/protected_hashes.txt"
echo "BACKUP=$BACKUP_ROOT"

echo "===== 4. APPLY THREE RUNTIME FILES ====="
APPLIED=1
cp -f "$STAGE/app/jood_whatsapp_context.py" "$CONTEXT"
cp -f "$STAGE/app/whatsloop_inbound.py" "$INBOUND"
cp -f "$STAGE/app/jood_whatsapp_buttons.py" "$BUTTONS"
chown pakgat:pakgat "$CONTEXT" "$INBOUND" "$BUTTONS"

"$APP/.venv/bin/python" -m py_compile "$CONTEXT" "$INBOUND" "$BUTTONS"

# Connection, catalog card and existing send pipelines are protected byte-for-byte.
[[ "$(sha_file "$ENV_FILE")" == "$ENV_SHA" ]]
[[ "$(sha_file "$LINK_CARD")" == "$LINK_CARD_SHA" ]]
[[ "$(sha_file "$OUTBOUND")" == "$OUTBOUND_SHA" ]]
[[ "$(sha_file "$CAMPAIGN")" == "$CAMPAIGN_SHA" ]]
echo "PROTECTED_FILES_UNCHANGED=PASS"

echo "===== 5. RESTART / HEALTH ====="
systemctl restart pakgat-voucher.service
systemctl is-active --quiet pakgat-voucher.service
for attempt in $(seq 1 20); do
  if curl -fsS --max-time 5 https://voucher.pakgat.com/health >/tmp/pakgat-jood-health.json; then
    break
  fi
  sleep 1
done
grep -q '"ok":true' /tmp/pakgat-jood-health.json
grep -q '"database":"connected"' /tmp/pakgat-jood-health.json
cat /tmp/pakgat-jood-health.json
echo

echo "===== 6. FINAL CONTRACT CHECK ====="
grep -q '/messages/send-buttons' "$BUTTONS"
! grep -q '/messages/send-template' "$BUTTONS"
grep -q 'merchant_handoff_silent' "$INBOUND"
grep -q 'أرسلوا التفاصيل' "$CONTEXT"
grep -q 'merchant_campaign_silent_human_takeover' "$CONTEXT"
echo "FINAL_CONTRACT=PASS"
echo "DEPLOYMENT=PASS"
echo "ROLLBACK_BACKUP=$BACKUP_ROOT"

APPLIED=0
