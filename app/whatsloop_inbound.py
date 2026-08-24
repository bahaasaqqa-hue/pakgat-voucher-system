from __future__ import annotations

import asyncio
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
from app.jood_ai import JoodAIError, generate_jood_decision
from app.jood_avatar_data import JOOD_AVATAR_WEBP_BASE64
from app.jood_company_ops import (
    append_turn,
    capture_open_handoff_message,
    conversation_key_for,
    create_handoff,
    has_open_handoff,
    load_recent_turns,
    resolve_contact_mode,
    route_jood_intent,
    trusted_context_for,
)
from app.customer_notifications import (
    customer_details_received_reply,
    customer_response_reply,
    resolve_customer_response,
)
from app.jood_identity import JOOD_ROLE_AR, should_jood_ai_reply
from app.jood_policy import sanitize_jood_reply
from app.jood_reply_validation import validate_and_clean_reply
from app.jood_catalog import (
    catalog_context,
    catalog_from_presented_options,
    enforce_sales_action,
    execute_catalog_action,
    is_sales_consent,
    load_live_catalog,
    strict_product_message,
)
from app.jood_sales_playbook import SALES_FACTS
from app.whatsloop_inbound_core import InboundEvent, normalize_inbound_event
from app.whatsloop_security import current_webhook_token, request_signature_is_valid, webhook_token_is_valid

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


def _send_jood_reply(event: InboundEvent, message: str) -> tuple[bool, str]:
    if not core.WHATSLOOP_API_BASE_URL or not core.WHATSLOOP_API_TOKEN:
        return False, "WhatsLoop configuration is missing"
    if event.channel_id is None or not event.chat_id or not event.message_id:
        return False, "Missing channel/chat/message id"
    if not message.strip():
        return False, "Empty reply"

    body = json.dumps(
        {
            "channel_id": event.channel_id,
            "to": event.chat_id,
            "message": message.strip(),
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
    if not request_signature_is_valid(raw, request.headers, signing_secret):
        core.log_event(db, "whatsloop_webhook_signature_rejected", details="invalid-or-missing-signature")
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

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
        return JSONResponse({"success": True, "duplicate": True, "jood_reply": "skipped"})

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
        and should_jood_ai_reply(normalized.text, normalized.chat_id)
    ):
        contact = None
        conversation_key = ""
        try:
            sender_identity = normalized.sender or normalized.chat_id or ""
            contact, mode = resolve_contact_mode(db, sender_identity, normalized.text or "")
            customer_response = resolve_customer_response(
                db,
                sender_identity,
                normalized.text or "",
                contact.id,
            )
            if customer_response is not None:
                acknowledgement = customer_response_reply(customer_response.action)
                acknowledgement_status = "skipped_customer_response"
                if acknowledgement:
                    ok, _provider_status = await asyncio.to_thread(
                        _send_jood_reply,
                        normalized,
                        acknowledgement,
                    )
                    acknowledgement_status = "support_ack_sent" if ok else "support_ack_failed"
                    core.log_event(
                        db,
                        "customer_support_ack_sent" if ok else "customer_support_ack_failed",
                        details=f"notification_id={customer_response.notification_id}",
                    )
                core.log_event(
                    db,
                    "customer_notification_response",
                    details=f"action={customer_response.action}; notification_id={customer_response.notification_id}",
                )
                return JSONResponse(
                    {
                        "success": True,
                        "duplicate": False,
                        "event_id": row.id,
                        "jood_reply": acknowledgement_status,
                    }
                )
            if has_open_handoff(db, contact.id):
                if capture_open_handoff_message(db, contact.id, normalized.text or ""):
                    details_reply = customer_details_received_reply()
                    ok, _provider_status = await asyncio.to_thread(
                        _send_jood_reply,
                        normalized,
                        details_reply,
                    )
                    core.log_event(
                        db,
                        "customer_support_details_received",
                        details=f"contact_id={contact.id}; acknowledgement={'sent' if ok else 'failed'}",
                    )
                    return JSONResponse(
                        {
                            "success": True,
                            "duplicate": False,
                            "event_id": row.id,
                            "jood_reply": "support_details_ack_sent" if ok else "support_details_ack_failed",
                        }
                    )
                core.log_event(
                    db,
                    "jood_reply_paused_for_handoff",
                    details=f"contact_id={contact.id}",
                )
                return JSONResponse(
                    {
                        "success": True,
                        "duplicate": False,
                        "event_id": row.id,
                        "jood_reply": "skipped_open_handoff",
                    }
                )
            history = load_recent_turns(db, contact.id, limit=8)
            intent = route_jood_intent(normalized.text or "", mode)
            trusted_context = trusted_context_for(normalized.text or "", mode)
            from app.jood_whatsapp_context import (
                active_outreach_context,
                inbound_outreach_context,
                update_outreach_state,
            )

            persisted_outreach = inbound_outreach_context(db, contact.id)
            if persisted_outreach:
                trusted_context += "\n" + persisted_outreach
            context_row = active_outreach_context(db, contact.id)
            state = dict(context_row.state_json or {}) if context_row else {}
            direction = str(state.get("direction") or "inbound")
            last_commitment = str(state.get("last_commitment") or "")
            catalog = load_live_catalog(db) if direction == "outbound" and mode == "customer" else []
            if not catalog and direction == "outbound" and mode == "customer":
                catalog = catalog_from_presented_options(state.get("presented_options"))
            approved_urls = {item.url for item in catalog}
            if catalog:
                trusted_context += "\n" + SALES_FACTS
                trusted_context += "\n" + catalog_context(catalog)
            if not persisted_outreach:
                trusted_context += "\nConversation direction: inbound. Persona: inbound_customer_support."
            conversation_key = conversation_key_for(
                "whatsapp",
                contact.id,
                chat_id=normalized.chat_id or "",
                sender=normalized.sender or "",
            )
            append_turn(
                db,
                contact.id,
                "whatsapp",
                "user",
                normalized.text or "",
                conversation_key,
            )
            # Outbound campaign reporting is updated only after a real inbound
            # customer message. This does not add campaign instructions to the
            # inbound prompt or change the resolved customer/merchant mode.
            from app.jood_whatsapp_campaign import mark_latest_dispatch_replied

            mark_latest_dispatch_replied(db, contact.id)

            allow_handoff_claim = False
            if intent == "human_handoff":
                create_handoff(
                    db,
                    contact.id,
                    "customer_support" if mode == "customer" else "merchant_partnership",
                    details=normalized.text or "",
                )
                allow_handoff_claim = True
                trusted_context += "\nA real handoff record has now been created, so you may truthfully say the case was raised to the relevant team."

            decision = None
            validation = None
            catalog_result = None
            correction = ""
            deterministic_sale = (
                direction == "outbound"
                and mode == "customer"
                and is_sales_consent(normalized.text or "")
            )
            attempts = 1 if deterministic_sale else 2
            for _attempt in range(attempts):
                if deterministic_sale:
                    decision = enforce_sales_action(
                        {
                            "reply": "",
                            "detected_intent": "accepted_offer",
                            "next_stage": "product_link_shared",
                            "last_commitment_fulfilled": True,
                            "handoff_required": False,
                            "action": "send_product_link",
                            "selected_option": "",
                        },
                        normalized.text or "",
                        state,
                    )
                else:
                    try:
                        decision = await asyncio.to_thread(
                            generate_jood_decision,
                            normalized.text or "",
                            history,
                            mode,
                            intent,
                            trusted_context,
                            correction,
                        )
                    except JoodAIError as exc:
                        correction = str(exc)
                        decision = None
                        continue
                catalog_result = execute_catalog_action(
                    decision,
                    catalog,
                    previous_options=state.get("presented_options")
                    if isinstance(state.get("presented_options"), list)
                    else None,
                )
                validation = validate_and_clean_reply(
                    catalog_result.reply,
                    direction=direction,
                    last_commitment=last_commitment,
                    commitment_fulfilled=bool(decision.get("last_commitment_fulfilled")),
                    approved_urls=catalog_result.approved_urls,
                )
                if validation.ok:
                    break
                correction = validation.reason
            if not validation or not validation.ok:
                if direction == "outbound" and mode == "merchant":
                    generated_reply = "أعتذر عن الرد السابق. معك جود من باكيجات بخصوص فرصة الشراكة؛ أرسل لي اسم النشاط والمدينة ونوع الخدمات لأوضح لكم الخطوة المناسبة."
                elif direction == "outbound":
                    generated_reply = (
                        strict_product_message(catalog[0])
                        if catalog
                        else "تعذر تحميل العرض المعتمد الآن. سأعيد المحاولة عند توفر كتالوج سلة."
                    )
                else:
                    generated_reply = "أعتذر، لم يكتمل الرد. اكتب لي طلبك مرة أخرى باختصار وسأساعدك مباشرة."
            else:
                generated_reply = validation.reply
            generated_reply = sanitize_jood_reply(
                generated_reply,
                allow_handoff_claim=allow_handoff_claim,
                customer_text=normalized.text or "",
                approved_urls=approved_urls,
            )
            if context_row and decision and validation and validation.ok:
                if bool(decision.get("handoff_required")) and not allow_handoff_claim:
                    create_handoff(
                        db,
                        contact.id,
                        "customer_support" if mode == "customer" else "merchant_partnership",
                        details=normalized.text or "",
                    )
                update_outreach_state(
                    db,
                    contact.id,
                    next_stage=str(decision.get("next_stage") or state.get("current_stage") or "active"),
                    last_commitment=str(decision.get("last_commitment") or ""),
                    collected_info=decision.get("collected_info") if isinstance(decision.get("collected_info"), dict) else None,
                    presented_options=catalog_result.presented_options if catalog_result else None,
                    selected_product_id=(
                        catalog_result.presented_options[0]["id"]
                        if catalog_result and len(catalog_result.presented_options) == 1
                        else ""
                    ),
                    status=str(decision.get("status") or "active"),
                )
        except JoodAIError as exc:
            reply_status = "ai_failed"
            core.log_event(
                db,
                "jood_ai_generation_failed",
                details=(
                    f"channel={normalized.channel_id or '-'}; chat={_mask_jid(normalized.chat_id)}; "
                    f"error={str(exc)[:160]}"
                ),
            )
        except Exception as exc:
            reply_status = "ai_failed"
            core.log_event(
                db,
                "jood_ai_generation_failed",
                details=(
                    f"channel={normalized.channel_id or '-'}; chat={_mask_jid(normalized.chat_id)}; "
                    f"error_type={type(exc).__name__}"
                ),
            )
        else:
            ok, provider_status = await asyncio.to_thread(_send_jood_reply, normalized, generated_reply)
            reply_status = "sent" if ok else "failed"
            if ok and contact is not None:
                append_turn(
                    db,
                    contact.id,
                    "whatsapp",
                    "assistant",
                    generated_reply,
                    conversation_key,
                )
            core.log_event(
                db,
                "jood_whatsloop_reply_sent" if ok else "jood_whatsloop_reply_failed",
                details=(
                    f"channel={normalized.channel_id or '-'}; chat={_mask_jid(normalized.chat_id)}; "
                    f"provider={provider_status[:250]}"
                ),
            )

    return JSONResponse(
        {"success": True, "duplicate": False, "event_id": row.id, "jood_reply": reply_status}
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
            <a class='btn btn-muted' href='/admin/company/jood'>مركز جود</a>
          </div>
          <div style='display:flex;gap:7px;flex-wrap:wrap;margin-top:12px'>
            <span class='badge badge-active'>خدمة العملاء</span>
            <span class='badge badge-active'>المبيعات</span>
            <span class='badge badge-active'>التجار</span>
            <span class='badge badge-active'>ذاكرة فعلية</span>
          </div>
        </div>
      </section>
      <section class='card' style='padding:22px;margin:18px 0'>
        <h2>Webhook</h2>
        <p class='muted'>التوقيع الأمني إلزامي قبل قراءة الرسالة أو تخزينها أو إرسال أي رد.</p>
        <input class='input' dir='ltr' readonly value='{core.esc(callback_url)}'>
      </section>
      <section class='card' style='padding:22px'>
        <h2>آخر 50 حدثًا</h2>
        <div class='table-wrap'><table><thead><tr><th>الحدث</th><th>القناة / الجروب</th><th>المرسل</th><th>النص</th><th>الوقت</th></tr></thead><tbody>{rows}</tbody></table></div>
      </section>
    </main>
    """
    return HTMLResponse(core.page_shell("جود | واتساب العملاء", body, admin=True))
