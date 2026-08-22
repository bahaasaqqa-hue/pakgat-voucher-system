from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping

_CURRENT_CONTEXT = b"pakgat:whatsloop:webhook:v2"
_LEGACY_CONTEXT = b"pakgat:whatsloop:webhook:v1"


def _derive(admin_secret: str, context: bytes) -> str:
    return hmac.new(admin_secret.encode("utf-8"), context, hashlib.sha256).hexdigest()


def current_webhook_token(admin_secret: str) -> str:
    """Return the new callback-path token shown for WhatsLoop configuration."""
    return _derive(admin_secret, _CURRENT_CONTEXT)


def legacy_webhook_token(admin_secret: str) -> str:
    """Return the previous callback-path token during the migration window."""
    return _derive(admin_secret, _LEGACY_CONTEXT)


def webhook_token_is_valid(candidate: str, admin_secret: str) -> bool:
    """Accept v2 plus v1 temporarily so callback rotation does not drop messages."""
    if not candidate or not admin_secret:
        return False
    return hmac.compare_digest(candidate, current_webhook_token(admin_secret)) or hmac.compare_digest(
        candidate, legacy_webhook_token(admin_secret)
    )


def signature_header_metadata(headers: Mapping[str, str]) -> list[str]:
    """Return only safe metadata for likely webhook-signature headers.

    Values are never logged. We expose only the header name, value length, and a
    known non-secret scheme prefix such as ``sha256=`` when present.
    """
    rows: list[str] = []
    for raw_name, raw_value in headers.items():
        name = str(raw_name or "").strip().lower()
        if not name:
            continue
        likely_signature = (
            "signature" in name
            or "hmac" in name
            or ("whatsloop" in name and any(token in name for token in ("sign", "hook")))
        )
        if not likely_signature:
            continue
        value = str(raw_value or "")
        prefix = ""
        for known in ("sha256=", "sha1=", "v1=", "v0="):
            if value.lower().startswith(known):
                prefix = known
                break
        rows.append(f"{name}(len={len(value)},prefix={prefix})")
    return sorted(rows)


def verify_hmac_sha256_hex(raw_body: bytes, signature: str, secret: str) -> bool:
    """Verify a raw-body HMAC-SHA256 signature encoded as hexadecimal.

    WhatsLoop's observed ``x-webhook-signature`` is 64 characters, matching a
    SHA-256 hex digest. The optional ``sha256=`` prefix is accepted defensively.
    No signature or secret value is returned or logged here.
    """
    if not signature or not secret:
        return False
    candidate = str(signature).strip()
    if candidate.lower().startswith("sha256="):
        candidate = candidate[7:]
    if len(candidate) != 64:
        return False
    try:
        int(candidate, 16)
    except ValueError:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(candidate.lower(), expected)
