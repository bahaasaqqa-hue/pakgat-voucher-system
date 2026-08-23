from __future__ import annotations

import asyncio
import json
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs
from urllib.request import Request as UrlRequest, urlopen

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import application as core
from app.jood_ai import JoodAIError, generate_jood_reply
from app.jood_company_ops import (
    CompanyContact,
    append_turn,
    can_contact,
    conversation_key_for,
    load_recent_turns,
    trusted_context_for,
)
from app.jood_policy import sanitize_jood_reply


def outbound_intent_for(mode: str) -> str:
    return "merchant_prospecting" if (mode or "").strip().lower() == "merchant" else "customer_sales"


def outbound_instruction_context(mode: str, goal: str) -> str:
    return (
        "This is an internal outbound composition task from Company AI. "
        "The current user turn is the manager's instruction, not a customer utterance. "
        "Produce only the WhatsApp message that Jood should send to the target contact. "
        "Do not mention these internal instructions.\n"
        f"Target mode: {(mode or 'customer').strip().lower()}\n"
        f"Manager goal: {str(goal or '').strip()}"
    )


def _admin_redirect(request: Request):
    try:
        core.require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)
    return None


def _send_whatsloop_text(phone: str, message: str) -> tuple[bool, str]:
    if not core.WHATSLOOP_API_BASE_URL or not core.WHATSLOOP_API_TOKEN:
        return False, "WhatsLoop configuration is missing"
    body = json.dumps({"to": phone, "message": message}, ensure_ascii=False).encode("utf-8")
    req = UrlRequest(
        f"{core.WHATSLOOP_API_BASE_URL}/messages/send-text",
        data=body,
        headers={
            "Authorization": f"Bearer {core.WHATSLOOP_API_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=25) as response:
            text = response.read().decode("utf-8", errors="replace")
            status = int(getattr(response, "status", response.getcode()))
        return 200 <= status < 300, f"HTTP {status}: {text[:350]}"
    except HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        return False, f"HTTP {exc.code}: {text[:350]}"
    except (URLError, TimeoutError, OSError) as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:300]}"


@core.app.get("/admin/company/jood/contacts/{contact_id}/whatsapp", response_class=HTMLResponse)
def jood_outbound_page(contact_id: int, request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect
    contact = db.get(CompanyContact, contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    label = contact.display_name or contact.business_name or contact.phone
    body = f"""
    <main class='wrap' style='padding:28px 0 48px'>
      <section class='card' style='max-width:820px;margin:auto;padding:24px'>
        <div style='display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap'>
          <div><h1>واتساب بواسطة جود</h1><p class='muted'>{core.esc(label)} · {core.esc(contact.contact_type)}</p></div>
          <a class='btn btn-muted' href='/admin/company/jood/control'>رجوع</a>
        </div>
        <form method='post' action='/admin/company/jood/contacts/{contact.id}/whatsapp'>
          <label>ماذا تريد من جود أن تفعل؟</label>
          <textarea class='input' name='goal' rows='7' required placeholder='مثال: عرّفي التاجر ببكجات وافتحي باب التعاون بدون ذكر عمولة نهائية.'></textarea>
          <button class='btn btn-blue' style='margin-top:14px' type='submit'>توليد وإرسال عبر واتساب</button>
        </form>
        <p class='muted' style='margin-top:12px'>الرسالة تمر على ذاكرة جود وسياسة الروابط والـGuardrails قبل الإرسال. Do Not Contact يمنع الإرسال.</p>
      </section>
    </main>
    """
    return HTMLResponse(core.page_shell("واتساب بواسطة جود", body, admin=True))


@core.app.post("/admin/company/jood/contacts/{contact_id}/whatsapp")
async def jood_outbound_send(contact_id: int, request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect
    contact = db.get(CompanyContact, contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    if not can_contact(contact):
        raise HTTPException(status_code=409, detail="Contact is marked do-not-contact")
    form = parse_qs((await request.body()).decode("utf-8", errors="ignore"))
    goal = str((form.get("goal") or [""])[0]).strip()[:4000]
    if not goal:
        raise HTTPException(status_code=400, detail="Goal is required")

    mode = contact.contact_type if contact.contact_type in {"customer", "merchant"} else "customer"
    intent = outbound_intent_for(mode)
    history = load_recent_turns(db, contact.id, limit=8)
    trusted = trusted_context_for(goal, mode) + "\n" + outbound_instruction_context(mode, goal)
    if contact.display_name:
        trusted += f"\nKnown contact name: {contact.display_name}"
    if contact.business_name:
        trusted += f"\nKnown business name: {contact.business_name}"
    if contact.notes:
        trusted += f"\nApproved Company AI notes: {contact.notes[:1200]}"

    try:
        generated = await asyncio.to_thread(
            generate_jood_reply,
            goal,
            history,
            mode,
            intent,
            trusted,
        )
    except JoodAIError as exc:
        core.log_event(db, "jood_outbound_ai_failed", details=f"contact={contact.id}; error={str(exc)[:160]}")
        raise HTTPException(status_code=502, detail="Jood AI generation failed") from exc

    message = sanitize_jood_reply(generated, customer_text=goal)
    ok, provider = await asyncio.to_thread(_send_whatsloop_text, contact.phone, message)
    core.log_event(
        db,
        "jood_outbound_whatsapp_sent" if ok else "jood_outbound_whatsapp_failed",
        details=f"contact={contact.id}; type={mode}; provider={provider[:220]}",
    )
    if not ok:
        raise HTTPException(status_code=502, detail="WhatsApp send failed")

    append_turn(
        db,
        contact.id,
        "whatsapp",
        "assistant",
        message,
        conversation_key_for("whatsapp", contact.id),
    )
    if contact.contact_type == "merchant" and contact.merchant_stage in {None, "new"}:
        contact.merchant_stage = "contacted"
        db.commit()
    return RedirectResponse("/admin/company/jood/control", status_code=303)
