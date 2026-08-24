from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Callable
import json
from urllib.request import Request as UrlRequest, urlopen

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import application as core


@dataclass(frozen=True)
class DispatchResult:
    sent: int = 0
    failed: int = 0


@dataclass(frozen=True)
class CustomerResponseResult:
    action: str
    value: str
    notification_id: int


def send_whatsloop_text(phone: str, message_body: str) -> None:
    if not core.WHATSLOOP_API_BASE_URL or not core.WHATSLOOP_API_TOKEN:
        raise RuntimeError("WhatsLoopConfigurationError")
    request = UrlRequest(
        f"{core.WHATSLOOP_API_BASE_URL}/messages/send-text",
        data=json.dumps({"to": phone, "message": message_body}, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {core.WHATSLOOP_API_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=25) as response:
        status_code = getattr(response, "status", response.getcode())
        response.read()
    if not 200 <= status_code < 300:
        raise RuntimeError("WhatsLoopHTTPError")


def resolve_customer_response(
    db: Session,
    sender_phone: str,
    text: str,
    contact_id: int,
) -> CustomerResponseResult | None:
    value = str(text or "").strip()
    if value not in {"1", "2", "3", "4", "5"}:
        return None
    phone = core.normalize_saudi_phone(sender_phone)
    if not phone:
        return None
    prompt = db.scalar(
        select(core.CustomerNotification)
        .where(
            core.CustomerNotification.customer_phone == phone,
            core.CustomerNotification.status == "sent",
            core.CustomerNotification.response_value.is_(None),
        )
        .order_by(
            core.CustomerNotification.sent_at.desc(),
            core.CustomerNotification.id.desc(),
        )
        .limit(1)
    )
    if not prompt:
        return None
    if prompt.notification_type == "voucher_redeemed":
        action = "rating_recorded"
    elif prompt.notification_type == "voucher_issued" and value in {"1", "2"}:
        action = "receipt_confirmed" if value == "1" else "human_handoff"
    else:
        return None
    prompt.response_value = value
    prompt.responded_at = core.now_utc()
    prompt.updated_at = prompt.responded_at
    db.commit()
    if action == "human_handoff":
        from app.jood_company_ops import JoodHandoff, create_handoff

        open_row = db.scalar(
            select(JoodHandoff).where(
                JoodHandoff.contact_id == contact_id,
                JoodHandoff.status == "open",
            )
        )
        if not open_row:
            create_handoff(db, contact_id, "customer_support", "Voucher customer requested support")
    return CustomerResponseResult(action=action, value=value, notification_id=prompt.id)


def dispatch_due_customer_notifications(
    db: Session,
    send: Callable[[str, str], None],
    *,
    limit: int = 50,
) -> DispatchResult:
    now = core.now_utc()
    rows = list(
        db.scalars(
            select(core.CustomerNotification)
            .where(
                core.CustomerNotification.status.in_(("queued", "failed")),
                or_(
                    core.CustomerNotification.next_attempt_at.is_(None),
                    core.CustomerNotification.next_attempt_at <= now,
                ),
            )
            .order_by(core.CustomerNotification.created_at, core.CustomerNotification.id)
            .limit(limit)
        ).all()
    )
    sent = failed = 0
    for row in rows:
        row.status = "sending"
        row.attempt_count += 1
        row.updated_at = now
        db.commit()
        try:
            send(row.customer_phone, row.message_body)
        except Exception as exc:  # provider failures stay retryable
            row.status = "failed"
            row.last_error = type(exc).__name__[:200]
            row.next_attempt_at = core.now_utc() + timedelta(minutes=min(60, 2 ** row.attempt_count))
            row.updated_at = core.now_utc()
            db.commit()
            failed += 1
        else:
            row.status = "sent"
            row.sent_at = core.now_utc()
            row.updated_at = row.sent_at
            row.next_attempt_at = None
            row.last_error = None
            db.commit()
            sent += 1
    return DispatchResult(sent=sent, failed=failed)
