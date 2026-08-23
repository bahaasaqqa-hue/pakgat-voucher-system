from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import parse_qs

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import Boolean, DateTime, Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app import application as core
from app.jood_policy import CAR_CARE_URL, PAKGAT_HOME_URL

CONTACT_TYPES = {"customer", "merchant"}
CONTACT_STATUSES = {"active", "do_not_contact"}
CALL_COOLDOWN_SECONDS = 30
CALL_OUTCOMES = {
    "interested",
    "follow_up",
    "not_interested",
    "no_answer",
    "busy",
    "human_handoff",
    "do_not_contact",
    "failed",
}
MERCHANT_STAGES = {
    "new",
    "contacted",
    "replied",
    "qualified",
    "agreement_requested",
    "agreement_shared",
    "handoff_ready",
    "handed_off",
    "not_interested",
    "do_not_contact",
}


class CompanyContact(core.Base):
    __tablename__ = "company_contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    phone: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    contact_type: Mapped[str] = mapped_column(String(20), default="customer", index=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    business_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    merchant_stage: Mapped[Optional[str]] = mapped_column(String(40), nullable=True, index=True)
    last_contact_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


class JoodConversationTurn(core.Base):
    __tablename__ = "jood_conversation_turns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contact_id: Mapped[int] = mapped_column(Integer, index=True)
    channel: Mapped[str] = mapped_column(String(30), index=True)
    conversation_key: Mapped[str] = mapped_column(String(300), index=True)
    role: Mapped[str] = mapped_column(String(20), index=True)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


class JoodHandoff(core.Base):
    __tablename__ = "jood_handoffs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contact_id: Mapped[int] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String(60), default="human_handoff", index=True)
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


class JoodCallCampaign(core.Base):
    __tablename__ = "jood_call_campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255))
    contact_type: Mapped[str] = mapped_column(String(20), index=True)
    goal: Mapped[str] = mapped_column(Text)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    transcript_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


class JoodCallSession(core.Base):
    __tablename__ = "jood_call_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contact_id: Mapped[int] = mapped_column(Integer, index=True)
    campaign_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    transcript: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


class JoodCallLog(core.Base):
    __tablename__ = "jood_call_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    contact_id: Mapped[int] = mapped_column(Integer, index=True)
    campaign_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    contact_type: Mapped[str] = mapped_column(String(20), index=True)
    contact_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[str] = mapped_column(String(40))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    outcome: Mapped[str] = mapped_column(String(40), index=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    transcript: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    human_follow_up: Mapped[bool] = mapped_column(Boolean, default=False)
    do_not_contact: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


def _digits(value: str) -> str:
    return re.sub(r"\D", "", str(value or ""))


def normalize_contact_phone(value: str) -> str:
    normalized = core.normalize_saudi_phone(str(value or "").split("@", 1)[0])
    if normalized:
        return normalized
    digits = _digits(str(value or "").split("@", 1)[0])
    if digits.startswith("966") and len(digits) == 12:
        return digits
    return ""


def infer_contact_type(text: str) -> str:
    value = " ".join(str(text or "").strip().lower().split())
    merchant_markers = (
        "أنا تاجر",
        "انا تاجر",
        "صاحب مطعم",
        "عندي مطعم",
        "عندنا مطعم",
        "صاحب نشاط",
        "عندي نشاط",
        "نحن مركز",
        "لدينا مركز",
        "نتعاون معكم",
        "نتعاون معاكم",
        "شراكة",
        "merchant",
        "business owner",
    )
    return "merchant" if any(marker.lower() in value for marker in merchant_markers) else "customer"


def can_contact(contact) -> bool:
    return str(getattr(contact, "status", "") or "").strip().lower() != "do_not_contact"


def conversation_key_for(
    channel: str,
    contact_id: int,
    *,
    chat_id: str = "",
    sender: str = "",
) -> str:
    clean_channel = (channel or "unknown").strip().lower()
    if clean_channel == "whatsapp" and str(chat_id or "").endswith("@g.us"):
        return f"whatsapp:{chat_id}:{sender or contact_id}"
    if clean_channel == "whatsapp":
        return f"whatsapp:{contact_id}"
    return f"{clean_channel}:{contact_id}"


def _is_voucher_request(value: str) -> bool:
    return any(
        word in value
        for word in ("قسيم", "قسائ", "كوبون", "voucher", "qr", "رقم الطلب", "طلب")
    )


def route_jood_intent(text: str, mode: str) -> str:
    value = " ".join(str(text or "").strip().lower().split())
    mode = (mode or "customer").strip().lower()

    human_words = ("أكلم موظف", "اكلم موظف", "شخص حقيقي", "مسؤول", "human", "agent")
    if any(word in value for word in human_words):
        return "human_handoff"

    if mode == "merchant":
        agreement_words = ("عقد", "اتفاقية", "الاتفاقية", "contract", "agreement")
        if any(word in value for word in agreement_words):
            return "merchant_agreement"
        qualification_words = (
            "اسم مطعمي",
            "اسم النشاط",
            "اسم المنشأة",
            "الفرع",
            "فرعنا",
            "المسؤول",
            "رقم التواصل",
            "مطعمنا",
            "مركزنا",
        )
        if any(word in value for word in qualification_words):
            return "merchant_qualification"
        return "merchant_prospecting"

    payment_words = ("دفع", "استرجاع", "استرداد", "refund", "payment", "خصم المبلغ")
    if any(word in value for word in payment_words):
        return "refund_or_payment"
    if _is_voucher_request(value):
        return "order_or_voucher"
    complaint_words = ("شكوى", "مشكلة", "ما يفتح", "مايفتح", "خربان", "complaint")
    if any(word in value for word in complaint_words):
        return "complaint"
    category_words = (
        "عروض",
        "العناية بالسيارات",
        "عناية بالسيارات",
        "مطعم",
        "مطاعم",
        "سبا",
        "ترفيه",
        "سيارات",
        "قسم",
        "تصنيف",
    )
    if any(word in value for word in category_words):
        return "product_or_category"
    sales_words = ("أبغى", "ابغى", "أريد", "اريد", "اشتري", "شراء", "recommend", "buy")
    if any(word in value for word in sales_words):
        return "customer_sales"
    return "general"


def trusted_context_for(text: str, mode: str) -> str:
    value = " ".join(str(text or "").strip().lower().split())
    facts: list[str] = [
        f"Pakgat official home URL: {PAKGAT_HOME_URL}",
        "Pakgat currently focuses operationally on Riyadh.",
    ]
    if "سيار" in value or "car care" in value:
        facts.append(f"Approved car-care category URL: {CAR_CARE_URL}")
        facts.append("Use that exact approved URL for car-care; do not construct another category URL.")
    if _is_voucher_request(value):
        facts.append(
            "آلية القسيمة الموثقة: يشتري العميل القسيمة رقميًا، ثم تصدر القسيمة/الرابط ورمز QR للعميل، "
            "ويعرضها على التاجر الذي يتحقق منها ويؤكد الاستخدام. لا تذكري وسيلة إرسال غير موثقة."
        )
    if (mode or "").strip().lower() == "merchant":
        facts.append(
            "Merchant value proposition: Pakgat helps restaurants and service businesses attract Riyadh customers "
            "through prepaid digital packages and experiences without upfront marketing cost."
        )
        facts.append(
            "Do not commit final commission, binding terms or guaranteed sales. Agreement/partner links may be shared only if whitelisted."
        )
    return "\n".join(facts)


def resolve_contact_mode(db: Session, phone: str, text: str = "") -> tuple[CompanyContact, str]:
    normalized = normalize_contact_phone(phone)
    if not normalized:
        raise ValueError("Invalid Saudi phone")
    contact = db.scalar(select(CompanyContact).where(CompanyContact.phone == normalized))
    if contact:
        mode = contact.contact_type if contact.contact_type in CONTACT_TYPES else "customer"
        return contact, mode

    mode = infer_contact_type(text)
    contact = CompanyContact(
        phone=normalized,
        contact_type=mode,
        status="active",
        merchant_stage="new" if mode == "merchant" else None,
    )
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact, mode


def load_recent_turns(db: Session, contact_id: int, limit: int = 8) -> list[dict[str, str]]:
    safe_limit = max(1, min(int(limit or 8), 8))
    rows = list(
        db.scalars(
            select(JoodConversationTurn)
            .where(JoodConversationTurn.contact_id == contact_id)
            .order_by(JoodConversationTurn.created_at.desc(), JoodConversationTurn.id.desc())
            .limit(safe_limit)
        ).all()
    )
    rows.reverse()
    return [
        {"role": "model" if row.role in {"assistant", "model"} else "user", "text": row.text}
        for row in rows
        if row.role in {"user", "assistant", "model"} and row.text
    ]


def append_turn(
    db: Session,
    contact_id: int,
    channel: str,
    role: str,
    text: str,
    conversation_key: str,
) -> JoodConversationTurn:
    row = JoodConversationTurn(
        contact_id=contact_id,
        channel=(channel or "unknown")[:30],
        conversation_key=(conversation_key or f"contact:{contact_id}")[:300],
        role=(role or "user")[:20],
        text=str(text or "")[:12000],
    )
    db.add(row)
    contact = db.get(CompanyContact, contact_id)
    if contact:
        contact.last_contact_at = datetime.now(timezone.utc)
        contact.updated_at = datetime.now(timezone.utc)
        if contact.contact_type == "merchant" and role == "user" and contact.merchant_stage in {None, "new", "contacted"}:
            contact.merchant_stage = "replied"
    db.commit()
    db.refresh(row)
    return row


def create_handoff(db: Session, contact_id: int, kind: str, details: str = "") -> JoodHandoff:
    row = JoodHandoff(
        contact_id=contact_id,
        kind=(kind or "human_handoff")[:60],
        status="open",
        details=(details or "")[:6000] or None,
    )
    db.add(row)
    contact = db.get(CompanyContact, contact_id)
    if contact and contact.contact_type == "merchant":
        contact.merchant_stage = "handed_off"
    db.commit()
    db.refresh(row)
    return row


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def call_window_is_open(campaign, now: Optional[datetime] = None) -> bool:
    if str(getattr(campaign, "status", "") or "").lower() != "active":
        return False
    current = _aware_utc(now or datetime.now(timezone.utc))
    start = _aware_utc(getattr(campaign, "start_at"))
    end = _aware_utc(getattr(campaign, "end_at"))
    return start <= current <= end


def cooldown_is_satisfied(last_finished_at: Optional[datetime], now: Optional[datetime] = None) -> bool:
    if last_finished_at is None:
        return True
    current = _aware_utc(now or datetime.now(timezone.utc))
    finished = _aware_utc(last_finished_at)
    return (current - finished).total_seconds() >= CALL_COOLDOWN_SECONDS


def next_callable_contact(db: Session, campaign: JoodCallCampaign, now: Optional[datetime] = None) -> Optional[CompanyContact]:
    if not call_window_is_open(campaign, now):
        return None
    if not cooldown_is_satisfied(campaign.last_finished_at, now):
        return None
    contacted_ids = select(JoodCallLog.contact_id).where(JoodCallLog.campaign_id == campaign.id)
    return db.scalar(
        select(CompanyContact)
        .where(
            CompanyContact.contact_type == campaign.contact_type,
            CompanyContact.status == "active",
            ~CompanyContact.id.in_(contacted_ids),
        )
        .order_by(CompanyContact.last_contact_at.asc().nullsfirst(), CompanyContact.id.asc())
        .limit(1)
    )


def _admin_redirect(request: Request):
    try:
        core.require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)
    return None


def _form_value(form: dict, key: str, default: str = "") -> str:
    return str((form.get(key) or [default])[0]).strip()


@core.app.post("/admin/company/jood/contacts")
async def jood_contact_save(request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect
    form = parse_qs((await request.body()).decode("utf-8", errors="ignore"))
    phone = normalize_contact_phone(_form_value(form, "phone"))
    contact_type = _form_value(form, "contact_type", "customer").lower()
    if not phone or contact_type not in CONTACT_TYPES:
        raise HTTPException(status_code=400, detail="Valid Saudi phone and contact type are required")

    row = db.scalar(select(CompanyContact).where(CompanyContact.phone == phone))
    if not row:
        row = CompanyContact(phone=phone, contact_type=contact_type)
        db.add(row)
    row.contact_type = contact_type
    row.display_name = _form_value(form, "display_name") or row.display_name
    row.business_name = _form_value(form, "business_name") or row.business_name
    row.city = _form_value(form, "city") or row.city
    row.notes = _form_value(form, "notes") or row.notes
    row.status = "active"
    if contact_type == "merchant" and not row.merchant_stage:
        row.merchant_stage = "new"
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    return RedirectResponse("/admin/company/jood", status_code=303)


@core.app.post("/admin/company/jood/contacts/{contact_id}/do-not-contact")
def jood_contact_block(contact_id: int, request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect
    row = db.get(CompanyContact, contact_id)
    if not row:
        raise HTTPException(status_code=404, detail="Contact not found")
    row.status = "do_not_contact"
    if row.contact_type == "merchant":
        row.merchant_stage = "do_not_contact"
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    return RedirectResponse("/admin/company/jood", status_code=303)


@core.app.get("/admin/company/jood", response_class=HTMLResponse)
def jood_operations_page(request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect
    contacts = list(
        db.scalars(
            select(CompanyContact)
            .order_by(CompanyContact.updated_at.desc(), CompanyContact.id.desc())
            .limit(100)
        ).all()
    )
    campaigns = list(
        db.scalars(
            select(JoodCallCampaign)
            .order_by(JoodCallCampaign.created_at.desc(), JoodCallCampaign.id.desc())
            .limit(20)
        ).all()
    )
    call_logs = list(
        db.scalars(
            select(JoodCallLog)
            .order_by(JoodCallLog.ended_at.desc(), JoodCallLog.id.desc())
            .limit(30)
        ).all()
    )

    contact_rows = "".join(
        "<tr>"
        f"<td>{core.esc(c.display_name or c.business_name or '—')}</td>"
        f"<td>{core.esc(c.contact_type)}</td>"
        f"<td dir='ltr'>{core.esc(core.masked_phone(c.phone))}</td>"
        f"<td>{core.esc(c.city or '—')}</td>"
        f"<td>{core.esc(c.merchant_stage or '—')}</td>"
        f"<td>{core.esc(c.status)}</td>"
        f"<td><a class='btn btn-blue' href='/admin/company/jood/contacts/{c.id}/call'>اتصال بواسطة جود</a></td>"
        "</tr>"
        for c in contacts
    ) or "<tr><td colspan='7' class='muted'>لا توجد جهات اتصال بعد.</td></tr>"

    campaign_rows = "".join(
        "<tr>"
        f"<td>{core.esc(c.name)}</td><td>{core.esc(c.contact_type)}</td>"
        f"<td>{core.esc(core.fmt_dt(c.start_at))}</td><td>{core.esc(core.fmt_dt(c.end_at))}</td>"
        f"<td>{core.esc(c.status)}</td><td>30 ثانية</td>"
        "</tr>"
        for c in campaigns
    ) or "<tr><td colspan='6' class='muted'>لا توجد حملات اتصال بعد.</td></tr>"

    log_rows = "".join(
        "<tr>"
        f"<td>{core.esc(log.contact_name or '—')}</td><td>{core.esc(log.contact_type)}</td>"
        f"<td>{core.esc(log.outcome)}</td><td>{log.duration_seconds} ث</td>"
        f"<td>{core.esc((log.summary or '—')[:280])}</td><td>{core.esc(core.fmt_dt(log.ended_at))}</td>"
        "</tr>"
        for log in call_logs
    ) or "<tr><td colspan='6' class='muted'>لا توجد مكالمات مسجلة بعد.</td></tr>"

    body = f"""
    <main class='wrap' style='padding:28px 0 48px'>
      <div style='display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap'>
        <div><h1 style='margin-bottom:4px'>جود · العمليات والعملاء والتجار</h1>
        <p class='muted'>Company AI يحدد Customer أو Merchant. جود تستخدم نفس العقل والذاكرة في واتساب والمكالمات.</p></div>
        <a class='btn btn-muted' href='/admin/company'>Control Center</a>
      </div>

      <section class='card' style='padding:22px;margin-top:18px'>
        <h2>إضافة Customer / Merchant</h2>
        <form method='post' action='/admin/company/jood/contacts'>
          <div class='grid grid-mobile-1' style='grid-template-columns:repeat(3,1fr)'>
            <div><label>رقم الجوال</label><input class='input' name='phone' dir='ltr' required placeholder='05xxxxxxxx'></div>
            <div><label>النوع</label><select class='select' name='contact_type'><option value='customer'>Customer</option><option value='merchant'>Merchant</option></select></div>
            <div><label>الاسم</label><input class='input' name='display_name'></div>
            <div><label>اسم النشاط</label><input class='input' name='business_name'></div>
            <div><label>المدينة</label><input class='input' name='city' placeholder='الرياض'></div>
            <div><label>ملاحظات / سياق</label><input class='input' name='notes'></div>
          </div>
          <button class='btn btn-blue' style='margin-top:14px' type='submit'>حفظ</button>
        </form>
      </section>

      <section class='card' style='padding:22px;margin-top:18px'>
        <h2>جهات الاتصال</h2>
        <div class='table-wrap'><table><thead><tr><th>الاسم / النشاط</th><th>النوع</th><th>الهاتف</th><th>المدينة</th><th>مرحلة التاجر</th><th>الحالة</th><th>إجراء</th></tr></thead>
        <tbody>{contact_rows}</tbody></table></div>
      </section>

      <section class='card' style='padding:22px;margin-top:18px'>
        <h2>حملات الاتصال</h2>
        <p class='muted'>نافذة الاتصال من وقت إلى وقت، ومهلة ثابتة 30 ثانية بين المحاولات. الاتصال التلقائي مؤجل؛ v1 يبدأ يدويًا من Phone Link.</p>
        <div class='table-wrap'><table><thead><tr><th>الحملة</th><th>النوع</th><th>من</th><th>إلى</th><th>الحالة</th><th>Cooldown</th></tr></thead><tbody>{campaign_rows}</tbody></table></div>
      </section>

      <section class='card' style='padding:22px;margin-top:18px'>
        <h2>Call Log</h2>
        <div class='table-wrap'><table><thead><tr><th>الجهة</th><th>النوع</th><th>النتيجة</th><th>المدة</th><th>الملخص</th><th>الوقت</th></tr></thead><tbody>{log_rows}</tbody></table></div>
      </section>
    </main>
    """
    return HTMLResponse(core.page_shell("جود · Company AI", body, admin=True))
