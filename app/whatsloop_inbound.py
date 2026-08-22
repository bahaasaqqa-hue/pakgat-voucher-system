from __future__ import annotations

import hmac
import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import Boolean, DateTime, Integer, String, Text, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from app import application as core
from app.whatsloop_inbound_core import derive_webhook_token, normalize_inbound_event

MAX_WEBHOOK_BYTES = 1024 * 1024


class WhatsLoopInboundEvent(core.Base):
    __tablename__ = "whatsloop_inbound_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    channel_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    message_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    sender: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    chat_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    from_me: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    payload_json: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


def _expected_token() -> str:
    return derive_webhook_token(core.ADMIN_SECRET)


def _token_ok(value: str) -> bool:
    expected = _expected_token()
    return bool(value and expected and hmac.compare_digest(value, expected))


def _mask_jid(value: Optional[str]) -> str:
    if not value:
        return "—"
    base = value.split("@", 1)[0]
    if len(base) <= 6:
        return "***"
    return f"{base[:3]}***{base[-3:]}"


def _display_fields(row: WhatsLoopInboundEvent) -> tuple[Optional[int], Optional[str], Optional[str], Optional[str]]:
    channel_id = row.channel_id
    sender = row.sender
    chat_id = row.chat_id
    text = row.text
    if channel_id is not None and sender and chat_id and text:
        return channel_id, sender, chat_id, text
    try:
        raw = row.payload_json.encode("utf-8")
        payload = json.loads(row.payload_json)
        normalized = normalize_inbound_event(payload, raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return channel_id, sender, chat_id, text
    return (
        channel_id if channel_id is not None else normalized.channel_id,
        sender or normalized.sender,
        chat_id or normalized.chat_id,
        text or normalized.text,
    )


@core.app.post("/webhooks/whatsloop/{token}")
async def whatsloop_webhook(token: str, request: Request, db: Session = Depends(core.get_db)):
    if not _token_ok(token):
        raise HTTPException(status_code=404, detail="Not found")

    raw = await request.body()
    if len(raw) > MAX_WEBHOOK_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large")

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="Invalid JSON")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON object required")

    normalized = normalize_inbound_event(payload, raw)
    row = WhatsLoopInboundEvent(
        event_key=normalized.event_key,
        event_type=normalized.event_type[:100],
        channel_id=normalized.channel_id,
        message_id=(normalized.message_id or None),
        sender=(normalized.sender or None),
        chat_id=(normalized.chat_id or None),
        text=(normalized.text or None),
        from_me=normalized.from_me,
        payload_json=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    )
    db.add(row)
    try:
        db.commit()
        db.refresh(row)
        core.log_event(
            db,
            "whatsloop_webhook_received",
            details=(
                f"event={normalized.event_type[:80]}; channel={normalized.channel_id or '-'}; "
                f"sender={_mask_jid(normalized.sender)}"
            ),
        )
        return JSONResponse({"success": True, "duplicate": False, "event_id": row.id})
    except IntegrityError:
        db.rollback()
        return JSONResponse({"success": True, "duplicate": True})


@core.app.get("/admin/company/whatsloop", response_class=HTMLResponse)
def whatsloop_inbox(request: Request, db: Session = Depends(core.get_db)):
    try:
        core.require_admin(request)
    except HTTPException:
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/admin/login", status_code=303)

    callback_url = f"{core.BASE_URL}/webhooks/whatsloop/{_expected_token()}"
    events = list(
        db.scalars(
            select(WhatsLoopInboundEvent)
            .order_by(WhatsLoopInboundEvent.received_at.desc(), WhatsLoopInboundEvent.id.desc())
            .limit(50)
        ).all()
    )
    rendered_rows = []
    for row in events:
        channel_id, sender, chat_id, text = _display_fields(row)
        channel_label = str(channel_id) if channel_id is not None else "—"
        if chat_id:
            channel_label += f" · {_mask_jid(chat_id)}"
        rendered_rows.append(
            "<tr>"
            f"<td>{core.esc(row.event_type)}</td>"
            f"<td dir='ltr'>{core.esc(channel_label)}</td>"
            f"<td dir='ltr'>{core.esc(_mask_jid(sender))}</td>"
            f"<td>{core.esc((text or '—')[:240])}</td>"
            f"<td>{core.esc(core.fmt_dt(row.received_at))}</td>"
            "</tr>"
        )
    rows = "".join(rendered_rows) or "<tr><td colspan='5' class='muted'>لم تصل أحداث WhatsLoop بعد.</td></tr>"

    body = f"""
    <main class='wrap' style='padding:28px 0 48px'>
      <div style='display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap'>
        <div><h1 style='margin-bottom:4px'>Shaty · WhatsLoop Inbox</h1>
        <p class='muted'>استقبال آمن لأحداث WhatsLoop داخل Pakgat AI Company.</p></div>
        <a class='btn btn-muted' href='/admin/company'>AI Company</a>
      </div>
      <section class='card' style='padding:22px;margin:18px 0'>
        <h2>Webhook URL</h2>
        <p class='muted'>انسخ هذا الرابط إلى إعداد Webhook في WhatsLoop. يحتوي الرابط على مفتاح مشتق ولا يكشف ADMIN_SECRET.</p>
        <input class='input' dir='ltr' readonly value='{core.esc(callback_url)}'>
      </section>
      <section class='card' style='padding:22px'>
        <h2>آخر 50 حدثًا</h2>
        <div class='table-wrap'><table><thead><tr><th>الحدث</th><th>القناة / الجروب</th><th>المرسل</th><th>النص</th><th>الوقت</th></tr></thead><tbody>{rows}</tbody></table></div>
      </section>
    </main>
    """
    return HTMLResponse(core.page_shell("Shaty WhatsLoop", body, admin=True))
