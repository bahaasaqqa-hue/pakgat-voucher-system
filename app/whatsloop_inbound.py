from __future__ import annotations

from base64 import b64decode
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest, urlopen

from fastapi import Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import Boolean, DateTime, Integer, String, Text, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from app import application as core
from app.jood_avatar_data import JOOD_AVATAR_WEBP_BASE64
from app.jood_identity import JOOD_ROLE_AR, JOOD_TEST_REPLY, should_jood_test_reply
from app.whatsloop_inbound_core import InboundEvent, normalize_inbound_event
from app.whatsloop_security import current_webhook_token, verify_hmac_sha256_hex, webhook_token_is_valid

MAX_WEBHOOK_BYTES = 1024 * 1024
_JOOD_AVATAR_BYTES = b64decode(JOOD_AVATAR_WEBP_BASE64)
WHATSLOOP_WEBHOOK_SECRET_FILE = "/etc/pakgat/whatsloop_webhook_secret"


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
    return current_webhook_token(core.ADMIN_SECRET)


def _token_ok(value: str) -> bool:
    return webhook_token_is_valid(value, core.ADMIN_SECRET)


def _load_whatsloop_webhook_secret() -> str:
    """Load the signing secret without logging it or placing it in source code."""
    value = os.getenv("WHATSLOOP_WEBHOOK_SECRET", "").strip()
    if value:
        return value
    try:
        return Path(WHATSLOOP_WEBHOOK_SECRET_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


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


def _send_jood_test_reply(event: InboundEvent) -> tuple[bool, str]:
    if not core.WHATSLOOP_API_BASE_URL or not core.WHATSLOOP_API_TOKEN:
        return False, "WhatsLoop configuration is missing"
    if event.channel_id is None or not event.chat_id or not event.message_id:
        return False, "Missing channel/chat/message id"

    body = json.dumps(
        {
            "channel_id": event.channel_id,
            "to": event.chat_id,
            "message": JOOD_TEST_REPLY,
            "quoted_message_id": event.message_id,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = UrlRequest(
        f"{core.WHATSLOOP_API_BASE_URL}/messages/send-reply",
        data=body,
        headers={
            "Authorization": f"Bearer {core.WHATSLOOP_API_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=20) as response:
            text = response.read().decode("utf-8", errors="replace")
            status_code = int(getattr(response, "status", response.getcode()))
        return 200 <= status_code < 300, f"HTTP {status_code}: {text[:300]}"
    except HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        return False, f"HTTP {exc.code}: {text[:300]}"
    except (URLError, TimeoutError, OSError) as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:300]}"


@core.app.get("/admin/company/jood/avatar", include_in_schema=False)
def jood_avatar():
    return Response(
        content=_JOOD_AVATAR_BYTES,
        media_type="image/webp",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@core.app.post("/webhooks/whatsloop/{token}")
async def whatsloop_webhook(token: str, request: Request, db: Session = Depends(core.get_db)):
    if not _token_ok(token):
        raise HTTPException(status_code=404, detail="Not found")

    raw = await request.body()
    if len(raw) > MAX_WEBHOOK_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large")

    signing_secret = _load_whatsloop_webhook_secret()
    signature = request.headers.get("x-webhook-signature", "")
    if not signature:
        hmac_probe = "signature-missing"
    elif not signing_secret:
        hmac_probe = "secret-missing"
    else:
        hmac_probe = "match" if verify_hmac_sha256_hex(raw, signature, signing_secret) else "mismatch"
    core.log_event(db, "whatsloop_hmac_probe", details=f"x-webhook-signature={hmac_probe}")

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
    except IntegrityError:
        db.rollback()
        return JSONResponse({"success": True, "duplicate": True, "test_reply": "skipped"})

    core.log_event(
        db,
        "whatsloop_webhook_received",
        details=(
            f"event={normalized.event_type[:80]}; channel={normalized.channel_id or '-'}; "
            f"sender={_mask_jid(normalized.sender)}"
        ),
    )

    reply_status = "skipped"
    if (
        normalized.event_type == "message.received"
        and normalized.from_me is not True
        and should_jood_test_reply(normalized.text, normalized.chat_id)
    ):
        ok, provider_status = _send_jood_test_reply(normalized)
        reply_status = "sent" if ok else "failed"
        core.log_event(
            db,
            "jood_whatsloop_reply_sent" if ok else "jood_whatsloop_reply_failed",
            details=(
                f"channel={normalized.channel_id or '-'}; group={_mask_jid(normalized.chat_id)}; "
                f"provider={provider_status[:250]}"
            ),
        )

    return JSONResponse(
        {"success": True, "duplicate": False, "event_id": row.id, "test_reply": reply_status}
    )


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
      <section class='card' style='padding:18px 22px;margin-bottom:18px;display:grid;grid-template-columns:120px minmax(0,1fr);gap:20px;align-items:center'>
        <img src='/admin/company/jood/avatar' alt='جود من بكجات' style='display:block;width:112px;height:150px;object-fit:cover;object-position:50% 12%;border-radius:18px;background:#eff6ff;border:1px solid #dbeafe'>
        <div>
          <div style='display:flex;justify-content:space-between;gap:10px;align-items:flex-start;flex-wrap:wrap'>
            <div><h1 style='margin:0 0 5px'>جود · واتساب العملاء</h1>
            <p class='muted' style='margin:0'>{core.esc(JOOD_ROLE_AR)} عبر WhatsLoop.</p></div>
            <a class='btn btn-muted' href='/admin/company'>مركز التحكم</a>
          </div>
          <div style='display:flex;gap:7px;flex-wrap:wrap;margin-top:12px'>
            <span class='badge badge-active'>خدمة العملاء</span>
            <span class='badge badge-active'>المبيعات</span>
            <span class='badge badge-active'>التجار</span>
          </div>
          <p class='muted' style='margin:12px 0 0'>شاتي يبقى المساعد التنفيذي الداخلي لبهاء؛ جود هي الواجهة الخارجية لبكجات.</p>
        </div>
      </section>
      <section class='card' style='padding:22px;margin:18px 0'>
        <h2>رابط Webhook الجديد</h2>
        <p class='muted'>هذا رابط مُدوّر جديد. الرابط السابق سيبقى مقبولًا مؤقتًا حتى يتم تحديث WhatsLoop، لذلك لن تنقطع الرسائل أثناء الانتقال.</p>
        <input class='input' dir='ltr' readonly value='{core.esc(callback_url)}'>
      </section>
      <section class='card' style='padding:22px'>
        <h2>آخر 50 حدثًا</h2>
        <div class='table-wrap'><table><thead><tr><th>الحدث</th><th>القناة / الجروب</th><th>المرسل</th><th>النص</th><th>الوقت</th></tr></thead><tbody>{rows}</tbody></table></div>
      </section>
    </main>
    """
    return HTMLResponse(core.page_shell("جود | واتساب العملاء", body, admin=True))
