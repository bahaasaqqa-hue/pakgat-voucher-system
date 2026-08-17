"""Non-blocking bridge from Pakgat Voucher System audit events to Pakgat AI Data Hub.

The integration is deliberately fail-open: voucher issuance/redemption and WhatsLoop
operations must continue even when the AI Data Hub is unavailable.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest, urlopen


DATA_HUB_URL = os.getenv("PAKGAT_AI_DATA_HUB_URL", "").rstrip("/")
INGEST_TOKEN = os.getenv("PAKGAT_AI_INGEST_TOKEN", "")
DATA_HUB_TIMEOUT_SECONDS = float(os.getenv("PAKGAT_AI_DATA_HUB_TIMEOUT", "3"))


def _utc_iso(value: Optional[datetime] = None) -> str:
    dt = value or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _severity(action: str) -> str:
    value = (action or "").lower()
    if any(word in value for word in ("failed", "error")):
        return "warning"
    if any(word in value for word in ("conflict", "invalid", "security")):
        return "warning"
    return "info"


def _safe_details(details: Optional[str]) -> Optional[str]:
    """Keep operational context while stripping message-provider response bodies and phones."""
    if not details:
        return None
    text = str(details)
    text = re.sub(r"response=.*$", "response=[redacted]", text, flags=re.IGNORECASE)
    text = re.sub(r"(?<!\d)(?:\+?966|00966|0)?5\d{8}(?!\d)", "[phone-redacted]", text)
    return text[:350]


def _order_from_details(details: Optional[str]) -> Optional[str]:
    if not details:
        return None
    match = re.search(r"(?:^|;)\s*order=([^;]+)", str(details), flags=re.IGNORECASE)
    return match.group(1).strip() if match else None


def _external_id(action: str, voucher_id: Optional[int], order_id: Optional[str], details: Optional[str]) -> str:
    if voucher_id is not None:
        return f"voucher:{voucher_id}:{action}"
    if order_id:
        return f"order:{order_id}:{action}"
    digest = hashlib.sha256(f"{action}|{details or ''}".encode("utf-8")).hexdigest()[:20]
    return f"audit:{digest}"


def _post_json(path: str, payload: dict[str, Any]) -> None:
    if not DATA_HUB_URL or not INGEST_TOKEN:
        return
    body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    request = UrlRequest(
        f"{DATA_HUB_URL}{path}",
        data=body,
        headers={
            "Authorization": f"Bearer {INGEST_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=DATA_HUB_TIMEOUT_SECONDS) as response:
            response.read(256)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        # Fail open by design. The voucher system remains the source of truth.
        return


def _send_async(path: str, payload: dict[str, Any]) -> None:
    if not DATA_HUB_URL or not INGEST_TOKEN:
        return
    threading.Thread(target=_post_json, args=(path, payload), daemon=True).start()


def emit_health(status: str = "ok", details: Optional[dict[str, Any]] = None) -> None:
    _send_async(
        "/v1/health",
        {
            "service": "pakgat-voucher-system",
            "status": status,
            "details": details or {},
        },
    )


def install_datahub_hooks(application_module: Any) -> None:
    """Wrap the existing audit logger so every important lifecycle event reaches the Data Hub."""
    if getattr(application_module, "_pakgat_ai_datahub_installed", False):
        return

    original_log_event = application_module.log_event

    def wrapped_log_event(
        db: Any,
        action: str,
        voucher_id: Optional[int] = None,
        details: Optional[str] = None,
        created_at: Optional[datetime] = None,
    ) -> None:
        # Preserve the current production behavior first.
        original_log_event(db, action, voucher_id, details, created_at)

        order_id = _order_from_details(details)
        product_id: Optional[str] = None
        merchant: Optional[str] = None
        voucher_status: Optional[str] = None

        if voucher_id is not None:
            try:
                voucher = db.get(application_module.Voucher, voucher_id)
                if voucher:
                    order_id = str(voucher.order_id or order_id or "") or None
                    product_id = str(voucher.product_id or "") or None
                    merchant = str(voucher.merchant_name or "") or None
                    voucher_status = str(voucher.status or "") or None
            except Exception:
                # Enrichment is optional; never affect the transaction path.
                pass

        safe_details = _safe_details(details)
        payload = {
            "event_type": str(action),
            "source": "voucher-system",
            "occurred_at": _utc_iso(created_at),
            "external_id": _external_id(str(action), voucher_id, order_id, safe_details),
            "order_id": order_id,
            "product_id": product_id,
            "merchant": merchant,
            "severity": _severity(str(action)),
            "payload": {
                "voucher_id": voucher_id,
                "voucher_status": voucher_status,
                "details": safe_details,
            },
        }
        _send_async("/v1/events", payload)

        if action in {"voucher_created", "voucher_redeemed", "whatsapp_sent", "redemption_whatsapp_sent", "merchant_whatsapp_sent", "merchant_redemption_whatsapp_sent"}:
            emit_health("ok", {"last_event": action, "occurred_at": payload["occurred_at"]})
        elif any(word in str(action).lower() for word in ("failed", "error")):
            emit_health("degraded", {"last_event": action, "occurred_at": payload["occurred_at"]})

    application_module.log_event = wrapped_log_event
    application_module._pakgat_ai_datahub_installed = True

    # Emit a boot signal without making application startup depend on the Data Hub.
    emit_health("ok", {"bridge": "installed"})
