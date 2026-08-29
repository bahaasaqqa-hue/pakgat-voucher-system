#!/usr/bin/env bash
set -Eeuo pipefail

APP="/opt/pakgat-voucher-system"
ENV_FILE="/etc/pakgat/pakgat.env"
SERVICE="pakgat-voucher.service"
CAMPAIGN_SERVICE="pakgat-jood-campaign.service"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_ROOT="/opt/pakgat-repair-backups/jood-merchant-template-quick-replies-${STAMP}"
STAGE="$(mktemp -d /tmp/pakgat-jood-merchant-template-quick-replies.XXXXXX)"
PATCHED=0
HELPER_EXISTED=0

OUTBOUND="$APP/app/jood_outbound.py"
CAMPAIGN="$APP/app/jood_whatsapp_campaign.py"
HELPER="$APP/app/jood_whatsapp_buttons.py"
INBOUND="$APP/app/whatsloop_inbound.py"
CONTEXT="$APP/app/jood_whatsapp_context.py"
MAIN="$APP/main.py"
LINK_CARD="$APP/app/jood_link_card.py"

if [[ "$EUID" -ne 0 ]]; then
  echo "ERROR: run this script with sudo/root" >&2
  exit 2
fi

for file in "$OUTBOUND" "$CAMPAIGN" "$INBOUND" "$CONTEXT" "$MAIN"; do
  [[ -f "$file" ]] || { echo "ERROR: missing required file: $file" >&2; exit 3; }
done
[[ -f "$ENV_FILE" ]] || { echo "ERROR: missing $ENV_FILE" >&2; exit 4; }

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

sha_file() {
  sha256sum "$1" | awk '{print $1}'
}

python_function_hash() {
  local file="$1" function_name="$2"
  "$APP/.venv/bin/python" - "$file" "$function_name" <<'PY'
import ast
import hashlib
import sys

path, name = sys.argv[1], sys.argv[2]
source = open(path, encoding="utf-8").read()
tree = ast.parse(source)
for node in tree.body:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
        segment = ast.get_source_segment(source, node) or ""
        print(hashlib.sha256(segment.encode("utf-8")).hexdigest())
        raise SystemExit(0)
raise SystemExit(f"function not found: {name}")
PY
}

INBOUND_BEFORE="$(sha_file "$INBOUND")"
CONTEXT_BEFORE="$(sha_file "$CONTEXT")"
MAIN_BEFORE="$(sha_file "$MAIN")"
ENV_BEFORE="$(sha_file "$ENV_FILE")"
TEXT_SENDER_BEFORE="$(python_function_hash "$OUTBOUND" _send_whatsloop_text)"
LINK_CARD_BEFORE=""
if [[ -f "$LINK_CARD" ]]; then
  LINK_CARD_BEFORE="$(sha_file "$LINK_CARD")"
fi

rollback() {
  local rc=$?
  if [[ "$rc" -eq 0 ]]; then
    rm -rf "$STAGE"
    return 0
  fi

  echo "FAILURE_DETECTED=YES" >&2
  if [[ "$PATCHED" -eq 1 && -d "$BACKUP_ROOT" ]]; then
    cp -f "$BACKUP_ROOT/jood_outbound.py" "$OUTBOUND" || true
    cp -f "$BACKUP_ROOT/jood_whatsapp_campaign.py" "$CAMPAIGN" || true
    if [[ "$HELPER_EXISTED" -eq 1 ]]; then
      cp -f "$BACKUP_ROOT/jood_whatsapp_buttons.py" "$HELPER" || true
    else
      rm -f "$HELPER" || true
    fi
    chown pakgat:pakgat "$OUTBOUND" "$CAMPAIGN" 2>/dev/null || true
    [[ ! -f "$HELPER" ]] || chown pakgat:pakgat "$HELPER" 2>/dev/null || true
    systemctl restart "$SERVICE" >/dev/null 2>&1 || true
  fi
  rm -rf "$STAGE" || true
  echo "ROLLBACK_COMPLETE=YES" >&2
  echo "BACKUP=$BACKUP_ROOT" >&2
  exit "$rc"
}
trap rollback EXIT

echo "===== 0. READ-ONLY CURRENT-STATE VERIFICATION ====="
echo "APP_SERVICE=$(systemctl is-active "$SERVICE" || true)"
echo "CAMPAIGN_WORKER=$(systemctl is-active "$CAMPAIGN_SERVICE" || true)"
echo "INBOUND_SHA=$INBOUND_BEFORE"
echo "CONTEXT_SHA=$CONTEXT_BEFORE"
echo "MAIN_SHA=$MAIN_BEFORE"
echo "TEXT_SENDER_SHA=$TEXT_SENDER_BEFORE"
[[ -z "$LINK_CARD_BEFORE" ]] || echo "LINK_CARD_SHA=$LINK_CARD_BEFORE"

BUTTON_REFS_OUTBOUND="$(grep -c 'send_merchant_choice_template' "$OUTBOUND" || true)"
BUTTON_REFS_CAMPAIGN="$(grep -c 'send_merchant_choice_template' "$CAMPAIGN" || true)"
TEXT_SEND_REFS_OUTBOUND="$(grep -c '_send_whatsloop_text, contact.phone, message' "$OUTBOUND" || true)"
TEXT_SEND_REFS_CAMPAIGN="$(grep -c '_send_whatsloop_text, contact.phone, message' "$CAMPAIGN" || true)"
echo "jood_outbound.py BUTTON_REFS=$BUTTON_REFS_OUTBOUND TEXT_SEND_REFS=$TEXT_SEND_REFS_OUTBOUND"
echo "jood_whatsapp_campaign.py BUTTON_REFS=$BUTTON_REFS_CAMPAIGN TEXT_SEND_REFS=$TEXT_SEND_REFS_CAMPAIGN"
echo "jood_whatsapp_buttons.py EXISTS=$([[ -f "$HELPER" ]] && echo True || echo False)"

if [[ "$BUTTON_REFS_OUTBOUND" != 0 || "$BUTTON_REFS_CAMPAIGN" != 0 || \
      "$TEXT_SEND_REFS_OUTBOUND" != 1 || "$TEXT_SEND_REFS_CAMPAIGN" != 2 || \
      -f "$HELPER" ]]; then
  echo "ERROR: production source is not the verified text-sender baseline; nothing changed" >&2
  exit 10
fi

CAMPAIGN_STATUSES_BEFORE="$(PYTHONPATH="$APP" "$APP/.venv/bin/python" <<'PY'
from sqlalchemy import select
from app import application as core
from app.jood_whatsapp_campaign import JoodWhatsAppCampaign

with core.SessionLocal() as db:
    rows = db.execute(
        select(JoodWhatsAppCampaign.id, JoodWhatsAppCampaign.status)
        .order_by(JoodWhatsAppCampaign.id)
    ).all()
print(",".join(f"{row.id}:{row.status}" for row in rows))
PY
)"
ACTIVE_CAMPAIGNS="$(tr ',' '\n' <<<"$CAMPAIGN_STATUSES_BEFORE" | grep -E ':(active|running)$' | paste -sd, - || true)"
echo "CAMPAIGN_STATUSES=${CAMPAIGN_STATUSES_BEFORE:-none}"
echo "ACTIVE_OR_RUNNING_CAMPAIGNS=${ACTIVE_CAMPAIGNS:-none}"
if [[ -n "$ACTIVE_CAMPAIGNS" ]]; then
  echo "ERROR: an active/running campaign exists; nothing changed" >&2
  exit 11
fi

echo "===== 1. RED TEST ====="
set +e
"$APP/.venv/bin/python" - "$OUTBOUND" "$CAMPAIGN" "$HELPER" <<'PY'
from pathlib import Path
import sys

outbound, campaign, helper = map(Path, sys.argv[1:])
assert helper.exists()
assert "send_merchant_choice_template" in outbound.read_text(encoding="utf-8")
assert "send_merchant_choice_template" in campaign.read_text(encoding="utf-8")
PY
RED_RC=$?
set -e
if [[ "$RED_RC" -eq 0 ]]; then
  echo "ERROR: RED test unexpectedly passed" >&2
  exit 12
fi
echo "RED_CONFIRMED=YES"

echo "===== 2. BUILD ISOLATED STAGE ====="
mkdir -p "$STAGE/app"
cp "$OUTBOUND" "$STAGE/app/jood_outbound.py"
cp "$CAMPAIGN" "$STAGE/app/jood_whatsapp_campaign.py"

cat > "$STAGE/app/jood_whatsapp_buttons.py" <<'PY'
from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest, urlopen


MERCHANT_CHOICE_SUFFIX = (
    "\n\n*1 — أرسلوا التفاصيل*\n"
    "*2 — لدي استفسار*"
)

MERCHANT_TEMPLATE_BUTTONS = (
    {"type": "quickReply", "text": "أرسلوا التفاصيل"},
    {"type": "quickReply", "text": "لدي استفسار"},
)


def is_merchant_choice_message(message: str) -> bool:
    return str(message or "").rstrip().endswith(MERCHANT_CHOICE_SUFFIX)


def merchant_choice_body(message: str) -> str:
    text = str(message or "").rstrip()
    if not text.endswith(MERCHANT_CHOICE_SUFFIX):
        raise ValueError("message is not the approved merchant choice message")
    return text[: -len(MERCHANT_CHOICE_SUFFIX)].rstrip()


def _core_whatsloop_config() -> tuple[str, str]:
    base = ""
    token = ""
    try:
        from app import application as core
        base = str(getattr(core, "WHATSLOOP_API_BASE_URL", "") or "").strip()
        token = str(getattr(core, "WHATSLOOP_API_TOKEN", "") or "").strip()
    except Exception:
        pass

    base = base or str(
        os.getenv("WHATSLOOP_API_BASE_URL")
        or os.getenv("WHATSLOOP_BASE_URL")
        or ""
    ).strip()
    token = token or str(
        os.getenv("WHATSLOOP_API_TOKEN")
        or os.getenv("WHATSLOOP_TOKEN")
        or ""
    ).strip()
    if not base:
        raise RuntimeError("WhatsLoop API base URL is not configured")
    if not token:
        raise RuntimeError("WhatsLoop API token is not configured")
    return base.rstrip("/"), token


def resolve_channel_id() -> int | None:
    for key in (
        "WHATSLOOP_CHANNEL_ID",
        "JOOD_WHATSLOOP_CHANNEL_ID",
        "WHATSAPP_CHANNEL_ID",
        "WHATSLOOP_SESSION_ID",
    ):
        raw = str(os.getenv(key) or "").strip()
        if raw.isdigit() and int(raw) > 0:
            return int(raw)

    try:
        from sqlalchemy import text
        from app import application as core
        with core.engine.connect() as connection:
            value = connection.execute(
                text(
                    "SELECT channel_id FROM whatsloop_inbound_events "
                    "WHERE channel_id IS NOT NULL AND channel_id > 0 "
                    "ORDER BY id DESC LIMIT 1"
                )
            ).scalar()
        if value is not None and int(value) > 0:
            return int(value)
    except Exception:
        pass
    return None


def build_merchant_template_payload(phone: str, message: str) -> dict[str, Any]:
    channel_id = resolve_channel_id()
    if channel_id is None:
        raise RuntimeError("WhatsLoop interactive channel_id is unavailable")
    clean_phone = str(phone or "").strip()
    if not clean_phone:
        raise ValueError("recipient phone is empty")
    return {
        "channel_id": channel_id,
        "to": clean_phone,
        "text": merchant_choice_body(message),
        "template_buttons": [dict(button) for button in MERCHANT_TEMPLATE_BUTTONS],
    }


def _post_whatsloop(endpoint: str, payload: dict[str, Any]) -> tuple[int, bytes]:
    base, token = _core_whatsloop_config()
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = UrlRequest(
        base + endpoint,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=35) as response:
            return int(getattr(response, "status", response.getcode())), response.read()
    except HTTPError as exc:
        return int(exc.code), exc.read()
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"WhatsLoop request failed: {type(exc).__name__}: {exc}") from exc


def send_merchant_choice_template(phone: str, message: str) -> tuple[bool, str]:
    payload = build_merchant_template_payload(phone, message)
    status, raw = _post_whatsloop("/messages/send-template", payload)
    response_text = raw.decode("utf-8", errors="replace")[:700]
    return 200 <= status < 300, f"template HTTP {status}: {response_text}"
PY

"$APP/.venv/bin/python" - "$STAGE" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
import_line = (
    "from app.jood_whatsapp_buttons import "
    "is_merchant_choice_message, send_merchant_choice_template\n"
)
anchor = "from app.jood_policy import sanitize_jood_reply\n"
send_line = "ok, provider = await asyncio.to_thread(_send_whatsloop_text, contact.phone, message)"

expected_sites = {
    root / "app/jood_outbound.py": 1,
    root / "app/jood_whatsapp_campaign.py": 2,
}

for path, expected in expected_sites.items():
    source = path.read_text(encoding="utf-8")
    if source.count(anchor) != 1:
        raise SystemExit(f"IMPORT_ANCHOR_MISMATCH:{path.name}:{source.count(anchor)}")
    source = source.replace(anchor, anchor + import_line, 1)

    lines = source.splitlines(keepends=True)
    matches = [index for index, line in enumerate(lines) if line.strip() == send_line]
    if len(matches) != expected:
        raise SystemExit(
            f"TEXT_SEND_ANCHOR_MISMATCH:{path.name}:expected={expected}:actual={len(matches)}"
        )
    for index in reversed(matches):
        newline = "\n" if lines[index].endswith("\n") else ""
        indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
        replacement = (
            f'{indent}if mode == "merchant" and is_merchant_choice_message(message):\n'
            f"{indent}    ok, provider = await asyncio.to_thread(\n"
            f"{indent}        send_merchant_choice_template,\n"
            f"{indent}        contact.phone,\n"
            f"{indent}        message,\n"
            f"{indent}    )\n"
            f"{indent}else:\n"
            f"{indent}    ok, provider = await asyncio.to_thread(\n"
            f"{indent}        _send_whatsloop_text, contact.phone, message\n"
            f"{indent}    ){newline}"
        )
        lines[index] = replacement
    path.write_text("".join(lines), encoding="utf-8")
    print(f"PATCHED_STAGE={path.name};sender_sites={len(matches)}")
PY

echo "===== 3. STAGE COMPILE AND UNIT TESTS — NO NETWORK ====="
"$APP/.venv/bin/python" -m py_compile \
  "$STAGE/app/jood_whatsapp_buttons.py" \
  "$STAGE/app/jood_outbound.py" \
  "$STAGE/app/jood_whatsapp_campaign.py"
echo "STAGE_COMPILE=PASS"

"$APP/.venv/bin/python" - "$STAGE" <<'PY'
from pathlib import Path
from unittest.mock import patch
import ast
import importlib.util
import sys

root = Path(sys.argv[1])
helper_path = root / "app/jood_whatsapp_buttons.py"
spec = importlib.util.spec_from_file_location("stage_jood_whatsapp_buttons", helper_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def load_builder(path: Path, function_name: str):
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    node = next(
        item for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == function_name
    )
    isolated = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(isolated)
    namespace = {
        "PAKGAT_OFFICIAL_WEBSITE": "https://pakgat.com",
        "PAKGAT_MERCHANT_CAMPAIGN_SITE": "https://pakgat.com",
    }
    exec(compile(isolated, str(path), "exec"), namespace)
    return namespace[function_name]


class Contact:
    display_name = "صالون اختبار"
    business_name = "نشاط اختبار"
    phone = "966500000000"


builders = (
    load_builder(root / "app/jood_outbound.py", "approved_merchant_outreach_message"),
    load_builder(root / "app/jood_whatsapp_campaign.py", "approved_merchant_campaign_message"),
)
for builder in builders:
    original = builder(Contact())
    body = module.merchant_choice_body(original)
    assert original == body + module.MERCHANT_CHOICE_SUFFIX
    assert body.endswith("إذا ناسبكم نبدأ، ردوا برقم واحد فقط:")
    assert "*1 — أرسلوا التفاصيل*" not in body
    assert "*2 — لدي استفسار*" not in body

message = builders[0](Contact())
with patch.object(module, "resolve_channel_id", return_value=5):
    payload = module.build_merchant_template_payload(Contact.phone, message)
assert payload == {
    "channel_id": 5,
    "to": Contact.phone,
    "text": module.merchant_choice_body(message),
    "template_buttons": [
        {"type": "quickReply", "text": "أرسلوا التفاصيل"},
        {"type": "quickReply", "text": "لدي استفسار"},
    ],
}

captured = {}
def fake_post(endpoint, sent_payload):
    captured["endpoint"] = endpoint
    captured["payload"] = sent_payload
    return 200, b'{"success":true}'

with patch.object(module, "resolve_channel_id", return_value=5), \
     patch.object(module, "_post_whatsloop", side_effect=fake_post):
    ok, provider = module.send_merchant_choice_template(Contact.phone, message)
assert ok
assert captured["endpoint"] == "/messages/send-template"
assert captured["payload"] == payload
assert "HTTP 200" in provider

outbound = (root / "app/jood_outbound.py").read_text(encoding="utf-8")
campaign = (root / "app/jood_whatsapp_campaign.py").read_text(encoding="utf-8")
helper = helper_path.read_text(encoding="utf-8")
for source in (outbound, campaign, helper):
    assert "/messages/send-" + "buttons" not in source
assert outbound.count("send_merchant_choice_template") == 2
assert campaign.count("send_merchant_choice_template") == 3
print("STAGE_TEMPLATE_UNIT_TESTS=PASS")
PY

[[ "$(python_function_hash "$STAGE/app/jood_outbound.py" _send_whatsloop_text)" == "$TEXT_SENDER_BEFORE" ]]
echo "STAGE_TEXT_SENDER_UNCHANGED=PASS"

echo "===== 4. BACKUP ONLY FILES THAT WILL CHANGE ====="
mkdir -p "$BACKUP_ROOT"
cp -a "$OUTBOUND" "$BACKUP_ROOT/jood_outbound.py"
cp -a "$CAMPAIGN" "$BACKUP_ROOT/jood_whatsapp_campaign.py"
if [[ -f "$HELPER" ]]; then
  HELPER_EXISTED=1
  cp -a "$HELPER" "$BACKUP_ROOT/jood_whatsapp_buttons.py"
fi
printf '%s\n' \
  "INBOUND_SHA=$INBOUND_BEFORE" \
  "CONTEXT_SHA=$CONTEXT_BEFORE" \
  "MAIN_SHA=$MAIN_BEFORE" \
  "ENV_SHA=$ENV_BEFORE" \
  "TEXT_SENDER_SHA=$TEXT_SENDER_BEFORE" \
  "LINK_CARD_SHA=$LINK_CARD_BEFORE" \
  > "$BACKUP_ROOT/protected_hashes.txt"
echo "BACKUP=$BACKUP_ROOT"

echo "===== 5. APPLY EXACT STAGED FILES ====="
PATCHED=1
cp -f "$STAGE/app/jood_outbound.py" "$OUTBOUND"
cp -f "$STAGE/app/jood_whatsapp_campaign.py" "$CAMPAIGN"
cp -f "$STAGE/app/jood_whatsapp_buttons.py" "$HELPER"
chown pakgat:pakgat "$OUTBOUND" "$CAMPAIGN" "$HELPER"

echo "===== 6. LIVE COMPILE AND UNIT TESTS — NO NETWORK ====="
PYTHONPATH="$APP" "$APP/.venv/bin/python" -m py_compile "$HELPER" "$OUTBOUND" "$CAMPAIGN"
echo "LIVE_COMPILE=PASS"

PYTHONPATH="$APP" "$APP/.venv/bin/python" -m unittest \
  tests.test_jood_outbound \
  tests.test_jood_whatsapp_campaign \
  tests.test_jood_merchant_campaign_copy \
  tests.test_jood_whatsapp_context
echo "EXISTING_JOOD_TESTS=PASS"

PYTHONPATH="$APP" "$APP/.venv/bin/python" - <<'PY'
from unittest.mock import patch
from app import jood_whatsapp_buttons as module

message = (
    "*مساكم الله بالخير ✨*\n\n"
    "*معكم جود من منصة بكجات — https://pakgat.com*\n\n"
    "أعجبنا نشاط *اختبار*، ونشوف عندكم فرصة ممتازة لـ *استقطاب عملاء جدد في الرياض* "
    "من خلال *كوبونات وعروض وبكجات مميزة*.\n\n"
    "*بكجات منصة متخصصة في مدينة الرياض*، ونعمل على ربط الأنشطة المميزة بعملاء يبحثون عن عروض وتجارب تستحق التجربة.\n\n"
    "التعاون معنا *بدون أي تكاليف مسبقة عليكم*، ونساعدكم في تجهيز العرض وإبرازه بشكل واضح وجذاب.\n\n"
    "إذا ناسبكم نبدأ، ردوا برقم واحد فقط:\n\n"
    "*1 — أرسلوا التفاصيل*\n"
    "*2 — لدي استفسار*"
)
with patch.object(module, "resolve_channel_id", return_value=5):
    payload = module.build_merchant_template_payload("966500000000", message)
assert payload["template_buttons"] == [
    {"type": "quickReply", "text": "أرسلوا التفاصيل"},
    {"type": "quickReply", "text": "لدي استفسار"},
]
assert payload["text"].endswith("إذا ناسبكم نبدأ، ردوا برقم واحد فقط:")
assert "*1 — أرسلوا التفاصيل*" not in payload["text"]
assert "*2 — لدي استفسار*" not in payload["text"]
print("LIVE_PAYLOAD_TEST=PASS")
PY

echo "===== 7. PROTECTED-SCOPE HASH CHECK ====="
[[ "$(sha_file "$INBOUND")" == "$INBOUND_BEFORE" ]]
[[ "$(sha_file "$CONTEXT")" == "$CONTEXT_BEFORE" ]]
[[ "$(sha_file "$MAIN")" == "$MAIN_BEFORE" ]]
[[ "$(sha_file "$ENV_FILE")" == "$ENV_BEFORE" ]]
[[ "$(python_function_hash "$OUTBOUND" _send_whatsloop_text)" == "$TEXT_SENDER_BEFORE" ]]
if [[ -n "$LINK_CARD_BEFORE" ]]; then
  [[ "$(sha_file "$LINK_CARD")" == "$LINK_CARD_BEFORE" ]]
fi
echo "PROTECTED_SCOPE_UNCHANGED=PASS"

echo "===== 8. RESTART APP ONLY AND HEALTH CHECK ====="
systemctl restart "$SERVICE"
for attempt in {1..20}; do
  if curl -fsS --max-time 3 http://127.0.0.1:8000/health > "$BACKUP_ROOT/health.json" 2>/dev/null; then
    echo "HEALTH=PASS"
    break
  fi
  if [[ "$attempt" -eq 20 ]]; then
    echo "ERROR: health check did not recover" >&2
    exit 20
  fi
  sleep 1
done
[[ "$(systemctl is-active "$SERVICE")" == "active" ]]

echo "===== 9. FINAL VERIFICATION ====="
[[ "$(sha_file "$INBOUND")" == "$INBOUND_BEFORE" ]]
[[ "$(sha_file "$CONTEXT")" == "$CONTEXT_BEFORE" ]]
[[ "$(sha_file "$MAIN")" == "$MAIN_BEFORE" ]]
[[ "$(sha_file "$ENV_FILE")" == "$ENV_BEFORE" ]]
[[ "$(python_function_hash "$OUTBOUND" _send_whatsloop_text)" == "$TEXT_SENDER_BEFORE" ]]
if [[ -n "$LINK_CARD_BEFORE" ]]; then
  [[ "$(sha_file "$LINK_CARD")" == "$LINK_CARD_BEFORE" ]]
fi
CAMPAIGN_STATUSES_AFTER="$(PYTHONPATH="$APP" "$APP/.venv/bin/python" <<'PY'
from sqlalchemy import select
from app import application as core
from app.jood_whatsapp_campaign import JoodWhatsAppCampaign

with core.SessionLocal() as db:
    rows = db.execute(
        select(JoodWhatsAppCampaign.id, JoodWhatsAppCampaign.status)
        .order_by(JoodWhatsAppCampaign.id)
    ).all()
print(",".join(f"{row.id}:{row.status}" for row in rows))
PY
)"
[[ "$CAMPAIGN_STATUSES_AFTER" == "$CAMPAIGN_STATUSES_BEFORE" ]]
echo "CAMPAIGN_STATUS_UNCHANGED_GATE=PASS"
echo "DEPLOY_COMPLETE=YES"
echo "NO_LIVE_WHATSAPP_SENT_DURING_DEPLOY=YES"
echo "BUTTON_ENDPOINT=/messages/send-template"
echo "BUTTON_TYPE=quickReply"
echo "CAMPAIGN_WORKER_RESTARTED=NO"
echo "BACKUP=$BACKUP_ROOT"

trap - EXIT
rm -rf "$STAGE"
