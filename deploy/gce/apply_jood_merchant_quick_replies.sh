#!/usr/bin/env bash
set -Eeuo pipefail

APP="/opt/pakgat-voucher-system"
ENV_FILE="/etc/pakgat/pakgat.env"
SERVICE="pakgat-voucher.service"
CAMPAIGN_SERVICE="pakgat-jood-campaign.service"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_ROOT="/opt/pakgat-repair-backups/jood-merchant-quick-replies-${STAMP}"
STAGE="$(mktemp -d /tmp/pakgat-jood-merchant-quick-replies.XXXXXX)"
PATCHED=0
MODULE_EXISTED=0

OUTBOUND="$APP/app/jood_outbound.py"
CAMPAIGN="$APP/app/jood_whatsapp_campaign.py"
BUTTONS="$APP/app/jood_whatsapp_buttons.py"
INBOUND="$APP/app/whatsloop_inbound.py"
CONTEXT="$APP/app/jood_whatsapp_context.py"
MAIN="$APP/main.py"
LINK_CARD="$APP/app/jood_link_card.py"

if [[ "${EUID}" -ne 0 ]]; then
  echo "ERROR: run this script with sudo/root" >&2
  exit 2
fi

for f in "$OUTBOUND" "$CAMPAIGN" "$INBOUND" "$CONTEXT" "$MAIN"; do
  [[ -f "$f" ]] || { echo "ERROR: missing required file: $f" >&2; exit 3; }
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
  local file="$1" func="$2"
  "$APP/.venv/bin/python" - "$file" "$func" <<'PY'
import ast, hashlib, sys
path, name = sys.argv[1], sys.argv[2]
src = open(path, encoding="utf-8").read()
tree = ast.parse(src)
for node in tree.body:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
        text = ast.get_source_segment(src, node) or ""
        print(hashlib.sha256(text.encode("utf-8")).hexdigest())
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

  echo
  echo "!!! FAILURE DETECTED — ROLLING BACK ONLY THIS CHANGE !!!" >&2
  if [[ "$PATCHED" -eq 1 && -d "$BACKUP_ROOT" ]]; then
    cp -f "$BACKUP_ROOT/jood_outbound.py" "$OUTBOUND" || true
    cp -f "$BACKUP_ROOT/jood_whatsapp_campaign.py" "$CAMPAIGN" || true
    if [[ "$MODULE_EXISTED" -eq 1 ]]; then
      cp -f "$BACKUP_ROOT/jood_whatsapp_buttons.py" "$BUTTONS" || true
    else
      rm -f "$BUTTONS" || true
    fi
    chown pakgat:pakgat "$OUTBOUND" "$CAMPAIGN" 2>/dev/null || true
    [[ ! -f "$BUTTONS" ]] || chown pakgat:pakgat "$BUTTONS" 2>/dev/null || true
    systemctl restart "$SERVICE" >/dev/null 2>&1 || true
  fi
  rm -rf "$STAGE" || true
  echo "ROLLBACK_COMPLETE=YES" >&2
  echo "BACKUP=$BACKUP_ROOT" >&2
  exit "$rc"
}
trap rollback EXIT

cat <<'TXT'
============================================================
PAKGAT JOOD — MERCHANT QUICK REPLY BUTTONS
Scope: ONLY the approved merchant first-touch 1/2 choices
No live WhatsApp send is performed by this deployment.
============================================================
TXT

echo "===== 0. READ-ONLY SAFETY GATES ====="
echo "APP_SERVICE=$(systemctl is-active "$SERVICE" || true)"
echo "CAMPAIGN_WORKER=$(systemctl is-active "$CAMPAIGN_SERVICE" || true)"
echo "INBOUND_SHA=$INBOUND_BEFORE"
echo "CONTEXT_SHA=$CONTEXT_BEFORE"
echo "MAIN_SHA=$MAIN_BEFORE"
echo "TEXT_SENDER_SHA=$TEXT_SENDER_BEFORE"
[[ -z "$LINK_CARD_BEFORE" ]] || echo "LINK_CARD_SHA=$LINK_CARD_BEFORE"

CAMPAIGN_STATUS="$(PYTHONPATH="$APP" "$APP/.venv/bin/python" <<'PY'
from app import application as core
from app.jood_whatsapp_campaign import JoodWhatsAppCampaign
with core.SessionLocal() as db:
    row = db.get(JoodWhatsAppCampaign, 1)
    print((row.status if row else "missing").strip())
PY
)"
echo "CAMPAIGN_1_STATUS=$CAMPAIGN_STATUS"
if [[ "$CAMPAIGN_STATUS" != "paused" ]]; then
  echo "ERROR: Campaign 1 must remain paused while patching. Nothing changed." >&2
  exit 10
fi

if grep -q "send_merchant_choice_buttons" "$OUTBOUND" && \
   grep -q "send_merchant_choice_buttons" "$CAMPAIGN" && \
   [[ -f "$BUTTONS" ]]; then
  echo "ALREADY_INSTALLED=YES"
  exit 0
fi

echo "===== 1. RED TEST — feature must be absent before patch ====="
set +e
PYTHONPATH="$APP" "$APP/.venv/bin/python" - "$APP" <<'PY'
from pathlib import Path
import sys
root = Path(sys.argv[1])
outbound = (root / "app/jood_outbound.py").read_text(encoding="utf-8")
campaign = (root / "app/jood_whatsapp_campaign.py").read_text(encoding="utf-8")
assert "send_merchant_choice_buttons" in outbound
assert "send_merchant_choice_buttons" in campaign
assert (root / "app/jood_whatsapp_buttons.py").exists()
PY
RED_RC=$?
set -e
if [[ "$RED_RC" -eq 0 ]]; then
  echo "ERROR: red test unexpectedly passed; refusing to patch unknown state" >&2
  exit 11
fi
echo "RED_CONFIRMED=YES"

echo "===== 2. PREPARE ISOLATED STAGE ====="
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


# Exact suffix gate: only this approved merchant first-touch becomes interactive.
MERCHANT_CHOICE_SUFFIX = (
    "\n\n*1 — أرسلوا التفاصيل*\n"
    "*2 — لدي استفسار*"
)

MERCHANT_CHOICE_BUTTONS = (
    {"id": "1", "text": "أرسلوا التفاصيل"},
    {"id": "2", "text": "لدي استفسار"},
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

    # Read-only fallback to the latest channel already seen by Pakgat.
    try:
        from sqlalchemy import text
        from app import application as core
        with core.engine.connect() as conn:
            value = conn.execute(
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


def build_merchant_choice_payload(phone: str, message: str) -> dict[str, Any]:
    channel_id = resolve_channel_id()
    if channel_id is None:
        # Fail closed: never modify/fallback through the known-good text sender.
        raise RuntimeError("WhatsLoop interactive channel_id is unavailable")

    clean_phone = str(phone or "").strip()
    if not clean_phone:
        raise ValueError("recipient phone is empty")

    return {
        "channel_id": channel_id,
        "to": clean_phone,
        "text": merchant_choice_body(message),
        "buttons": [dict(button) for button in MERCHANT_CHOICE_BUTTONS],
    }


def post_whatsloop(endpoint: str, payload: dict[str, Any]) -> tuple[int, bytes]:
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


def send_merchant_choice_buttons(phone: str, message: str) -> tuple[bool, str]:
    payload = build_merchant_choice_payload(phone, message)
    status, raw = post_whatsloop("/messages/send-buttons", payload)
    response_text = raw.decode("utf-8", errors="replace")[:700]
    return 200 <= status < 300, f"buttons HTTP {status}: {response_text}"
PY

"$APP/.venv/bin/python" - "$STAGE" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
import_line = (
    "from app.jood_whatsapp_buttons import "
    "is_merchant_choice_message, send_merchant_choice_buttons\n"
)
anchor = "from app.jood_policy import sanitize_jood_reply\n"
old_send = "    ok, provider = await asyncio.to_thread(_send_whatsloop_text, contact.phone, message)"
new_send = """    if mode == \"merchant\" and is_merchant_choice_message(message):
        ok, provider = await asyncio.to_thread(
            send_merchant_choice_buttons,
            contact.phone,
            message,
        )
    else:
        ok, provider = await asyncio.to_thread(_send_whatsloop_text, contact.phone, message)"""

expectations = {
    root / "app/jood_outbound.py": 1,
    root / "app/jood_whatsapp_campaign.py": 2,
}

for path, expected_count in expectations.items():
    source = path.read_text(encoding="utf-8")
    if import_line not in source:
        if source.count(anchor) != 1:
            raise SystemExit(f"IMPORT_ANCHOR_MISMATCH:{path.name}:{source.count(anchor)}")
        source = source.replace(anchor, anchor + import_line, 1)

    count = source.count(old_send)
    if count != expected_count:
        raise SystemExit(
            f"TEXT_SEND_ANCHOR_MISMATCH:{path.name}:expected={expected_count}:actual={count}"
        )
    source = source.replace(old_send, new_send)
    path.write_text(source, encoding="utf-8")
    print(f"PATCHED_STAGE={path.name};sender_sites={count}")
PY

echo "===== 3. STAGE TESTS — NO NETWORK ====="
"$APP/.venv/bin/python" -m py_compile \
  "$STAGE/app/jood_whatsapp_buttons.py" \
  "$STAGE/app/jood_outbound.py" \
  "$STAGE/app/jood_whatsapp_campaign.py"

echo "STAGE_COMPILE=PASS"

PYTHONPATH="$STAGE:$APP" "$APP/.venv/bin/python" - "$STAGE" <<'PY'
from pathlib import Path
from unittest.mock import patch
import importlib.util
import sys

root = Path(sys.argv[1])
module_path = root / "app/jood_whatsapp_buttons.py"
spec = importlib.util.spec_from_file_location("stage_buttons", module_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

message = (
    "*مساكم الله بالخير ✨*\n\n"
    "*معكم جود من منصة بكجات — https://pakgat.com*\n\n"
    "أعجبنا نشاط *احساس*، ونشوف عندكم فرصة ممتازة لـ *استقطاب عملاء جدد في الرياض* "
    "من خلال *كوبونات وعروض وبكجات مميزة*.\n\n"
    "*بكجات منصة متخصصة في مدينة الرياض*، ونعمل على ربط الأنشطة المميزة بعملاء يبحثون عن عروض وتجارب تستحق التجربة.\n\n"
    "التعاون معنا *بدون أي تكاليف مسبقة عليكم*، ونساعدكم في تجهيز العرض وإبرازه بشكل واضح وجذاب.\n\n"
    "إذا ناسبكم نبدأ، ردوا برقم واحد فقط:\n\n"
    "*1 — أرسلوا التفاصيل*\n"
    "*2 — لدي استفسار*"
)

assert mod.is_merchant_choice_message(message)
assert not mod.is_merchant_choice_message("رسالة تاجر عادية")
body = mod.merchant_choice_body(message)
assert body.endswith("إذا ناسبكم نبدأ، ردوا برقم واحد فقط:")
assert "*1 — أرسلوا التفاصيل*" not in body
assert "*2 — لدي استفسار*" not in body

with patch.object(mod, "resolve_channel_id", return_value=5):
    payload = mod.build_merchant_choice_payload("966500000000", message)
assert payload == {
    "channel_id": 5,
    "to": "966500000000",
    "text": body,
    "buttons": [
        {"id": "1", "text": "أرسلوا التفاصيل"},
        {"id": "2", "text": "لدي استفسار"},
    ],
}

captured = {}
def fake_post(endpoint, sent_payload):
    captured["endpoint"] = endpoint
    captured["payload"] = sent_payload
    return 200, b'{"success":true}'

with patch.object(mod, "resolve_channel_id", return_value=5), \
     patch.object(mod, "post_whatsloop", side_effect=fake_post):
    ok, provider = mod.send_merchant_choice_buttons("966500000000", message)
assert ok
assert captured["endpoint"] == "/messages/send-buttons"
assert "HTTP 200" in provider

outbound = (root / "app/jood_outbound.py").read_text(encoding="utf-8")
campaign = (root / "app/jood_whatsapp_campaign.py").read_text(encoding="utf-8")
assert outbound.count("send_merchant_choice_buttons") >= 2
assert campaign.count("send_merchant_choice_buttons") >= 3
print("STAGE_QUICK_REPLY_TESTS=PASS")
PY

echo "===== 4. BACKUP LIVE FILES ====="
mkdir -p "$BACKUP_ROOT"
cp -a "$OUTBOUND" "$BACKUP_ROOT/jood_outbound.py"
cp -a "$CAMPAIGN" "$BACKUP_ROOT/jood_whatsapp_campaign.py"
if [[ -f "$BUTTONS" ]]; then
  MODULE_EXISTED=1
  cp -a "$BUTTONS" "$BACKUP_ROOT/jood_whatsapp_buttons.py"
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
cp -f "$STAGE/app/jood_outbound.py" "$OUTBOUND"
cp -f "$STAGE/app/jood_whatsapp_campaign.py" "$CAMPAIGN"
cp -f "$STAGE/app/jood_whatsapp_buttons.py" "$BUTTONS"
chown pakgat:pakgat "$OUTBOUND" "$CAMPAIGN" "$BUTTONS"
PATCHED=1

echo "===== 6. LIVE GREEN TESTS — NO NETWORK ====="
PYTHONPATH="$APP" "$APP/.venv/bin/python" -m py_compile \
  "$BUTTONS" "$OUTBOUND" "$CAMPAIGN"

echo "LIVE_COMPILE=PASS"

PYTHONPATH="$APP" "$APP/.venv/bin/python" - <<'PY'
from unittest.mock import patch
from app import jood_whatsapp_buttons as mod

message = (
    "*مساكم الله بالخير ✨*\n\n"
    "*معكم جود من منصة بكجات — https://pakgat.com*\n\n"
    "أعجبنا نشاط *احساس*، ونشوف عندكم فرصة ممتازة لـ *استقطاب عملاء جدد في الرياض* "
    "من خلال *كوبونات وعروض وبكجات مميزة*.\n\n"
    "*بكجات منصة متخصصة في مدينة الرياض*، ونعمل على ربط الأنشطة المميزة بعملاء يبحثون عن عروض وتجارب تستحق التجربة.\n\n"
    "التعاون معنا *بدون أي تكاليف مسبقة عليكم*، ونساعدكم في تجهيز العرض وإبرازه بشكل واضح وجذاب.\n\n"
    "إذا ناسبكم نبدأ، ردوا برقم واحد فقط:\n\n"
    "*1 — أرسلوا التفاصيل*\n"
    "*2 — لدي استفسار*"
)

with patch.object(mod, "resolve_channel_id", return_value=5):
    payload = mod.build_merchant_choice_payload("966500000000", message)
assert payload["buttons"] == [
    {"id": "1", "text": "أرسلوا التفاصيل"},
    {"id": "2", "text": "لدي استفسار"},
]
assert payload["text"].endswith("إذا ناسبكم نبدأ، ردوا برقم واحد فقط:")
assert "*1 — أرسلوا التفاصيل*" not in payload["text"]
assert "footer" not in payload
print("LIVE_PAYLOAD_TEST=PASS")
PY

# Existing regressions that cover merchant copy, outbound, and 1/2 handoff logic.
PYTHONPATH="$APP" "$APP/.venv/bin/python" -m unittest \
  tests.test_jood_outbound \
  tests.test_jood_merchant_campaign_copy \
  tests.test_jood_whatsapp_context

echo "EXISTING_JOOD_TESTS=PASS"

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

echo "===== 8. RESTART APP ONLY + HEALTH ====="
systemctl restart "$SERVICE"
for i in {1..20}; do
  if curl -fsS --max-time 3 http://127.0.0.1:8000/health > "$BACKUP_ROOT/health.json" 2>/dev/null; then
    echo "HEALTH=PASS"
    break
  fi
  if [[ "$i" -eq 20 ]]; then
    echo "ERROR: health check did not recover" >&2
    exit 20
  fi
  sleep 1
done
[[ "$(systemctl is-active "$SERVICE")" == "active" ]]
echo "APP_SERVICE=active"

POST_CAMPAIGN_STATUS="$(PYTHONPATH="$APP" "$APP/.venv/bin/python" <<'PY'
from app import application as core
from app.jood_whatsapp_campaign import JoodWhatsAppCampaign
with core.SessionLocal() as db:
    row = db.get(JoodWhatsAppCampaign, 1)
    print((row.status if row else "missing").strip())
PY
)"
[[ "$POST_CAMPAIGN_STATUS" == "paused" ]]
echo "CAMPAIGN_1_STILL_PAUSED=PASS"

echo "===== 9. FINAL SOURCE VERIFICATION ====="
grep -n "jood_whatsapp_buttons\|is_merchant_choice_message\|send_merchant_choice_buttons" \
  "$OUTBOUND" "$CAMPAIGN" "$BUTTONS" | head -80

echo
echo "DEPLOY_COMPLETE=YES"
echo "NO_LIVE_WHATSAPP_SENT_DURING_DEPLOY=YES"
echo "SALLA_CHANGED=NO"
echo "DATABASE_MUTATED=NO"
echo "WHATSLOOP_CONFIG_CHANGED=NO"
echo "WHATSLOOP_TEXT_SENDER_CHANGED=NO"
echo "WHATSLOOP_WEBHOOK_CHANGED=NO"
echo "BUTTON_ENDPOINT=/messages/send-buttons"
echo "BUTTON_1_ID=1"
echo "BUTTON_2_ID=2"
echo "BACKUP=$BACKUP_ROOT"

trap - EXIT
rm -rf "$STAGE"
