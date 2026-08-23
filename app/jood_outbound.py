from __future__ import annotations

import asyncio
import json
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs
from urllib.request import Request as UrlRequest, urlopen

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import application as core
from app.jood_ai import JoodAIError, generate_jood_reply
from app.jood_company_ops import (
    CompanyContact,
    append_turn,
    can_contact,
    conversation_key_for,
    load_recent_turns,
    normalize_contact_phone,
    trusted_context_for,
)
from app.jood_policy import sanitize_jood_reply
from app.jood_catalog import catalog_context, choose_featured_product, load_live_catalog
from app.jood_sales_playbook import featured_product_context, sales_opening_fallback
from app.jood_whatsapp_settings import resolved_outreach_instruction
from app.jood_whatsapp_context import remember_outreach_context


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


def build_contact_outreach_context(contact, instruction: str) -> str:
    lines = [str(instruction or "").strip()]
    fields = (
        ("Known contact name", getattr(contact, "display_name", None)),
        ("Known business name", getattr(contact, "business_name", None)),
        ("Known city", getattr(contact, "city", None)),
        ("Approved Company AI notes", getattr(contact, "notes", None)),
    )
    for label, value in fields:
        clean = str(value or "").strip()
        if clean:
            lines.append(f"{label}: {clean[:1200]}")
    return "\n".join(line for line in lines if line)


def ensure_outbound_opening(message: str, mode: str, contact, featured_product=None) -> str:
    """Prevent a first-touch outreach from degrading into an inbound help greeting."""
    clean = " ".join(str(message or "").strip().split())
    lowered = clean.lower()
    outbound_markers = ("أتواصل مع", "نتواصل مع", "تواصلنا مع", "فرصة تعاون", "عرض خاص")
    inbound_markers = ("كيف أساعدك", "كيف اقدر اساعدك", "كيف أقدر أساعدك", "وش أقدر أخدمك")
    if (
        len(clean) >= 60
        and any(marker in clean for marker in outbound_markers)
        and not any(marker in lowered for marker in inbound_markers)
        and (
            str(mode or "").strip().lower() == "merchant"
            or featured_product is None
            or featured_product.name in clean
        )
    ):
        return clean

    name = str(getattr(contact, "display_name", "") or "").strip()
    business = str(getattr(contact, "business_name", "") or "").strip()
    greeting = f"أهلًا {name}، " if name else "أهلًا، "
    if str(mode or "").strip().lower() == "merchant":
        target = f" لنشاط {business}" if business else ""
        return (
            f"{greeting}معك جود من منصة باكيجات. أتواصل معك لعرض فرصة تعاون{target} "
            "تساعدكم في الوصول لعملاء جدد عبر عروض وبكجات مميزة. هل يناسبك أرسل لك التفاصيل؟"
        )
    return sales_opening_fallback(contact, featured_product)


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
          <label>تعليمات خاصة <span class='muted'>(اختياري)</span></label>
          <textarea class='input' name='goal' rows='5' placeholder='اتركها فارغة لاستخدام توجيه جود العام المعتمد تلقائيًا.'></textarea>
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
    override = str((form.get("goal") or [""])[0]).strip()[:4000]
    await send_outreach_to_contact(db, contact, override)
    return RedirectResponse("/admin/company/jood/control", status_code=303)


async def send_outreach_to_contact(db: Session, contact: CompanyContact, override: str = "") -> str:
    if not can_contact(contact):
        raise HTTPException(status_code=409, detail="Contact is marked do-not-contact")

    mode = contact.contact_type if contact.contact_type in {"customer", "merchant"} else "customer"
    goal = resolved_outreach_instruction(db, mode, override)
    intent = outbound_intent_for(mode)
    history = load_recent_turns(db, contact.id, limit=8)
    trusted = trusted_context_for(goal, mode) + "\n" + outbound_instruction_context(mode, goal)
    trusted += "\n" + build_contact_outreach_context(contact, goal)
    catalog = load_live_catalog(db) if mode == "customer" else []
    featured = choose_featured_product(catalog, override or goal)
    if mode == "customer":
        trusted += "\n" + featured_product_context(featured)
        trusted += "\n" + catalog_context(catalog)

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

    approved_urls = {item.url for item in catalog}
    message = sanitize_jood_reply(generated, customer_text=goal, approved_urls=approved_urls)
    message = ensure_outbound_opening(message, mode, contact, featured)
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
    presented = ([{"id": featured.id, "name": featured.name, "url": featured.url}] if featured else [])
    remember_outreach_context(
        db, contact.id, mode, goal, "individual", message, presented_options=presented
    )
    if contact.contact_type == "merchant" and contact.merchant_stage in {None, "new"}:
        contact.merchant_stage = "contacted"
        db.commit()
    return message


@core.app.post("/admin/company/jood/whatsapp/send-now")
async def jood_outbound_send_now(request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect
    form = parse_qs((await request.body()).decode("utf-8", errors="ignore"))
    value = lambda name, default="": str((form.get(name) or [default])[0]).strip()
    phone = normalize_contact_phone(value("phone"))
    contact_type = value("contact_type", "customer").lower()
    if not phone or contact_type not in {"customer", "merchant"}:
        raise HTTPException(status_code=400, detail="Valid Saudi phone and contact type are required")
    contact = db.scalar(select(CompanyContact).where(CompanyContact.phone == phone))
    if not contact:
        contact = CompanyContact(phone=phone, contact_type=contact_type, status="active")
        db.add(contact)
    contact.contact_type = contact_type
    contact.display_name = value("display_name") or contact.display_name
    contact.business_name = value("business_name") or contact.business_name
    contact.city = value("city") or contact.city
    contact.notes = value("notes") or contact.notes
    if contact_type == "merchant" and not contact.merchant_stage:
        contact.merchant_stage = "new"
    db.commit()
    db.refresh(contact)
    await send_outreach_to_contact(db, contact, value("instruction")[:4000])
    return RedirectResponse("/admin/company/jood/whatsapp-campaigns?individual_sent=1", status_code=303)
