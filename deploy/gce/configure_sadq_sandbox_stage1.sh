#!/usr/bin/env bash
set -u

REPO=/opt/pakgat-voucher-system
SERVICE=pakgat-voucher
ENV_FILE=/etc/pakgat/pakgat.env
BRANCH=feat/sadq-dynamic-auth-webhook
CLIENT_TARGET=78aec01a59dadbddbe74507e7db5f5abfc82aeac
CLIENT_FILE=app/sadq_client.py
CLIENT_LIVE="$REPO/$CLIENT_FILE"
CALLBACK_URL=https://voucher.pakgat.com/integrations/sadq/webhook
BASE_URL=https://sandbox-api.sadq-sa.com
STAMP="$(date +%Y%m%d-%H%M%S)"
ENV_BACKUP="/tmp/pakgat-env-before-sadq-stage1-$STAMP"
CLIENT_BACKUP="/tmp/sadq-client-before-stage1-$STAMP.py"
CLIENT_EXISTED=0
EXTERNAL_PHASE=0
ROLLBACK_READY=0

PROTECTED_FILES=(
  main.py
  app/admin_theme_core.py
  app/jood_identity.py
  app/jood_outbound.py
  app/jood_policy.py
  app/jood_whatsapp_campaign.py
  app/jood_whatsapp_campaign_ui.py
  app/jood_whatsapp_context.py
  app/whatsloop_inbound.py
  app/jood_whatsapp_buttons.py
)

declare -A PROTECTED_BEFORE

hash_file() {
  local path="$1"
  if [[ -f "$path" ]]; then
    sha256sum "$path" | awk '{print $1}'
  else
    printf '%s' '__MISSING__'
  fi
}

capture_protected_hashes() {
  local rel
  for rel in "${PROTECTED_FILES[@]}"; do
    PROTECTED_BEFORE["$rel"]="$(hash_file "$REPO/$rel")"
  done
}

verify_protected_hashes() {
  local rel now
  for rel in "${PROTECTED_FILES[@]}"; do
    now="$(hash_file "$REPO/$rel")"
    if [[ "$now" != "${PROTECTED_BEFORE[$rel]}" ]]; then
      echo "PROTECTED_FILE_CHANGED=$rel" >&2
      return 1
    fi
  done
  return 0
}

rollback_local() {
  if [[ "$ROLLBACK_READY" -ne 1 ]]; then
    return 0
  fi
  echo "SADQ_STAGE1_ROLLBACK_START"
  cp -a "$ENV_BACKUP" "$ENV_FILE" 2>/dev/null || true
  if [[ "$CLIENT_EXISTED" -eq 1 ]]; then
    cp -a "$CLIENT_BACKUP" "$CLIENT_LIVE" 2>/dev/null || true
  else
    rm -f "$CLIENT_LIVE" 2>/dev/null || true
  fi
  chown pakgat:pakgat "$CLIENT_LIVE" 2>/dev/null || true
  systemctl restart "$SERVICE" >/dev/null 2>&1 || true
  echo "SADQ_STAGE1_ROLLBACK_DONE"
}

fail() {
  echo "SADQ_STAGE1_FAILED: $*" >&2
  if [[ "$EXTERNAL_PHASE" -eq 0 ]]; then
    rollback_local
  else
    echo "SADQ_STAGE1_CONFIG_PRESERVED_AFTER_EXTERNAL_PHASE=YES" >&2
  fi
  exit 1
}

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "SADQ_STAGE1_FAILED: Run as root" >&2
  exit 1
fi

[[ -d "$REPO/.git" ]] || fail "Repository not found: $REPO"
[[ -f "$ENV_FILE" ]] || fail "Environment file not found: $ENV_FILE"
[[ -x "$REPO/.venv/bin/python" ]] || fail "Production Python venv not found"
command -v openssl >/dev/null 2>&1 || fail "openssl is required"
command -v curl >/dev/null 2>&1 || fail "curl is required"
command -v sha256sum >/dev/null 2>&1 || fail "sha256sum is required"

capture_protected_hashes
cp -a "$ENV_FILE" "$ENV_BACKUP" || fail "Could not back up environment file"
if [[ -f "$CLIENT_LIVE" ]]; then
  CLIENT_EXISTED=1
  cp -a "$CLIENT_LIVE" "$CLIENT_BACKUP" || fail "Could not back up existing Sadq client"
fi
ROLLBACK_READY=1

read -r -p "Sadq Basic Client ID [Integrationclient]: " SADQ_CLIENT_ID_INPUT
SADQ_CLIENT_ID_INPUT="${SADQ_CLIENT_ID_INPUT:-Integrationclient}"
read -r -s -p "Sadq Basic Client Secret: " SADQ_CLIENT_SECRET_INPUT
echo
read -r -p "Sadq integration username: " SADQ_USERNAME_INPUT
read -r -s -p "Sadq integration password: " SADQ_PASSWORD_INPUT
echo
read -r -p "Sadq Account ID: " SADQ_ACCOUNT_ID_INPUT
read -r -s -p "Sadq Account Secret: " SADQ_ACCOUNT_SECRET_INPUT
echo

[[ -n "$SADQ_CLIENT_ID_INPUT" ]] || fail "Basic Client ID is required"
[[ -n "$SADQ_CLIENT_SECRET_INPUT" ]] || fail "Basic Client Secret is required"
[[ -n "$SADQ_USERNAME_INPUT" ]] || fail "Integration username is required"
[[ -n "$SADQ_PASSWORD_INPUT" ]] || fail "Integration password is required"
[[ -n "$SADQ_ACCOUNT_ID_INPUT" ]] || fail "Account ID is required"
[[ -n "$SADQ_ACCOUNT_SECRET_INPUT" ]] || fail "Account Secret is required"

CURRENT_WEBHOOK_TOKEN="$($REPO/.venv/bin/python - "$ENV_FILE" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
value = ""
for raw in path.read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, candidate = line.split("=", 1)
    if key.strip() != "SADQ_WEBHOOK_TOKEN":
        continue
    candidate = candidate.strip()
    if len(candidate) >= 2 and candidate[0] == candidate[-1] and candidate[0] in {"'", '"'}:
        candidate = candidate[1:-1]
    value = candidate
print(value)
PY
)" || fail "Could not inspect existing webhook token"

if [[ -n "$CURRENT_WEBHOOK_TOKEN" && "$CURRENT_WEBHOOK_TOKEN" != "NOT_SET" ]]; then
  SADQ_WEBHOOK_TOKEN_INPUT="$CURRENT_WEBHOOK_TOKEN"
  echo "SADQ_WEBHOOK_TOKEN_REUSED=YES"
else
  SADQ_WEBHOOK_TOKEN_INPUT="$(openssl rand -hex 32)" || fail "Could not generate webhook token"
  [[ ${#SADQ_WEBHOOK_TOKEN_INPUT} -ge 64 ]] || fail "Generated webhook token is too short"
  echo "SADQ_WEBHOOK_TOKEN_GENERATED=YES"
fi

sudo -u pakgat git -C "$REPO" fetch origin "$BRANCH" || fail "git fetch failed"
sudo -u pakgat git -C "$REPO" cat-file -e "$CLIENT_TARGET^{commit}" || fail "Sadq client target commit unavailable"
TMP_CLIENT="/tmp/pakgat-sadq-client-$STAMP.py"
sudo -u pakgat git -C "$REPO" show "$CLIENT_TARGET:$CLIENT_FILE" > "$TMP_CLIENT" || fail "Could not materialize Sadq client"
install -o pakgat -g pakgat -m 0644 "$TMP_CLIENT" "$CLIENT_LIVE" || fail "Could not install Sadq client"
rm -f "$TMP_CLIENT" 2>/dev/null || true

SADQ_SETUP_BASE_URL="$BASE_URL" \
SADQ_SETUP_CLIENT_ID="$SADQ_CLIENT_ID_INPUT" \
SADQ_SETUP_CLIENT_SECRET="$SADQ_CLIENT_SECRET_INPUT" \
SADQ_SETUP_USERNAME="$SADQ_USERNAME_INPUT" \
SADQ_SETUP_PASSWORD="$SADQ_PASSWORD_INPUT" \
SADQ_SETUP_ACCOUNT_ID="$SADQ_ACCOUNT_ID_INPUT" \
SADQ_SETUP_ACCOUNT_SECRET="$SADQ_ACCOUNT_SECRET_INPUT" \
SADQ_SETUP_WEBHOOK_URL="$CALLBACK_URL" \
SADQ_SETUP_WEBHOOK_TOKEN="$SADQ_WEBHOOK_TOKEN_INPUT" \
$REPO/.venv/bin/python - "$ENV_FILE" <<'PY' || fail "Could not update Sadq environment configuration"
from pathlib import Path
import os
import stat
import sys

path = Path(sys.argv[1])
st = path.stat()
keys = {
    "SADQ_API_BASE_URL": os.environ["SADQ_SETUP_BASE_URL"],
    "SADQ_CLIENT_ID": os.environ["SADQ_SETUP_CLIENT_ID"],
    "SADQ_CLIENT_SECRET": os.environ["SADQ_SETUP_CLIENT_SECRET"],
    "SADQ_USERNAME": os.environ["SADQ_SETUP_USERNAME"],
    "SADQ_PASSWORD": os.environ["SADQ_SETUP_PASSWORD"],
    "SADQ_ACCOUNT_ID": os.environ["SADQ_SETUP_ACCOUNT_ID"],
    "SADQ_ACCOUNT_SECRET": os.environ["SADQ_SETUP_ACCOUNT_SECRET"],
    "SADQ_WEBHOOK_URL": os.environ["SADQ_SETUP_WEBHOOK_URL"],
    "SADQ_WEBHOOK_TOKEN": os.environ["SADQ_SETUP_WEBHOOK_TOKEN"],
}
for key, value in keys.items():
    if "\n" in value or "\r" in value or "'" in value:
        raise SystemExit(f"Unsupported character in {key}")

original = path.read_text(encoding="utf-8").splitlines()
seen = set()
output = []
for raw in original:
    stripped = raw.strip()
    if stripped and not stripped.startswith("#") and "=" in stripped:
        key = stripped.split("=", 1)[0].strip()
        if key in keys:
            if key not in seen:
                output.append(f"{key}='{keys[key]}'")
                seen.add(key)
            continue
    output.append(raw)
for key, value in keys.items():
    if key not in seen:
        output.append(f"{key}='{value}'")

tmp = path.with_name(path.name + ".sadq-stage1.tmp")
tmp.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
os.chmod(tmp, stat.S_IMODE(st.st_mode))
os.chown(tmp, st.st_uid, st.st_gid)
os.replace(tmp, path)
PY

unset SADQ_CLIENT_SECRET_INPUT SADQ_PASSWORD_INPUT SADQ_ACCOUNT_SECRET_INPUT CURRENT_WEBHOOK_TOKEN

sudo -u pakgat "$REPO/.venv/bin/python" -m py_compile "$CLIENT_LIVE" || fail "Sadq client compile failed"

grep -q '^SADQ_CLIENT_ID=' "$ENV_FILE" || fail "SADQ_CLIENT_ID missing from environment"
grep -q '^SADQ_WEBHOOK_TOKEN=' "$ENV_FILE" || fail "SADQ_WEBHOOK_TOKEN missing from environment"
grep -q '^SADQ_WEBHOOK_URL=' "$ENV_FILE" || fail "SADQ_WEBHOOK_URL missing from environment"

echo "SADQ_STAGE1_LOCAL_CONFIG_OK"

systemctl restart "$SERVICE" || fail "Service restart failed"
READY=0
for _ in {1..20}; do
  if systemctl is-active --quiet "$SERVICE"; then
    HTTP="$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/merchant 2>/dev/null || true)"
    if [[ "$HTTP" == "200" || "$HTTP" == "303" || "$HTTP" == "307" ]]; then
      READY=1
      break
    fi
  fi
  sleep 1
done
if [[ "$READY" -ne 1 ]]; then
  systemctl status "$SERVICE" --no-pager || true
  journalctl -u "$SERVICE" -n 60 --no-pager || true
  fail "Service did not become healthy"
fi

echo "SADQ_STAGE1_SERVICE_OK"

UNAUTH_STATUS="$(curl -sS -o /dev/null -w '%{http_code}' \
  -X POST \
  -H 'Content-Type: application/json' \
  --data '{}' \
  "$CALLBACK_URL" 2>/dev/null || true)"
[[ "$UNAUTH_STATUS" == "403" ]] || fail "Unauthenticated callback probe returned HTTP $UNAUTH_STATUS instead of 403"
echo "PAKGAT_CALLBACK_UNAUTH_PROTECTED"

SADQ_VERIFY_WEBHOOK_TOKEN="$SADQ_WEBHOOK_TOKEN_INPUT" \
SADQ_VERIFY_CALLBACK_URL="$CALLBACK_URL" \
$REPO/.venv/bin/python - <<'PY' || fail "Authenticated callback verification failed"
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen

token = os.environ["SADQ_VERIFY_WEBHOOK_TOKEN"]
url = os.environ["SADQ_VERIFY_CALLBACK_URL"]
request = Request(
    url,
    data=b"{}",
    headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    },
    method="POST",
)
try:
    with urlopen(request, timeout=20) as response:
        status = int(getattr(response, "status", response.getcode()))
except HTTPError as exc:
    status = int(exc.code)
if status != 422:
    raise SystemExit(f"Authenticated callback returned HTTP {status}, expected 422")
PY

echo "PAKGAT_CALLBACK_AUTH_VALIDATED"

verify_protected_hashes || fail "Protected Jood/WhatsLoop/main files changed before external registration"
echo "PROTECTED_SETTINGS_AND_ROUTING_UNCHANGED"

EXTERNAL_PHASE=1

SADQ_STAGE1_ENV_FILE="$ENV_FILE" \
SADQ_STAGE1_REPO="$REPO" \
$REPO/.venv/bin/python - <<'PY' || fail "Sadq dynamic authentication or webhook registration failed"
from pathlib import Path
import os
import sys


def load_environment(path: Path) -> None:
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


repo = Path(os.environ["SADQ_STAGE1_REPO"])
load_environment(Path(os.environ["SADQ_STAGE1_ENV_FILE"]))
os.chdir(repo)
sys.path.insert(0, str(repo))

from app import sadq_client

client = sadq_client.SadqClient(sadq_client.SadqConfig.from_env())
client.get_access_token()
print("SADQ_DYNAMIC_AUTH_OK", flush=True)

expected = sadq_client._normalized_url(client.config.webhook_url)
before = client.list_webhooks()
was_present = any(
    sadq_client._normalized_url(item.get("webhookUrl", "")) == expected
    for item in before
    if item.get("webhookUrl")
)
client.ensure_webhook()
after = client.list_webhooks()
matching = [
    item
    for item in after
    if item.get("webhookUrl")
    and sadq_client._normalized_url(item.get("webhookUrl", "")) == expected
]
if not matching:
    raise SystemExit("Sadq webhook was not present after ensure_webhook")
print("SADQ_WEBHOOK_ALREADY_PRESENT=YES" if was_present else "SADQ_WEBHOOK_CREATED=YES", flush=True)
print(f"SADQ_WEBHOOK_LIST_OK count={len(after)}", flush=True)
print("SADQ_WEBHOOK_REGISTERED_OK", flush=True)
PY

unset SADQ_WEBHOOK_TOKEN_INPUT SADQ_CLIENT_ID_INPUT SADQ_USERNAME_INPUT SADQ_ACCOUNT_ID_INPUT

verify_protected_hashes || fail "Protected Jood/WhatsLoop/main files changed"

echo "SADQ_STAGE1_READY_FOR_E2E"
echo "SADQ_STAGE1_DEPLOY_OK"
echo "ENV_BACKUP=$ENV_BACKUP"
if [[ "$CLIENT_EXISTED" -eq 1 ]]; then
  echo "CLIENT_BACKUP=$CLIENT_BACKUP"
fi
echo "CHANGED_ONLY=/etc/pakgat/pakgat.env,$CLIENT_FILE"
echo "CALLBACK=$CALLBACK_URL"
