from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Iterable
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

from fastapi import BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app import application as core
from app.jood_ai import JoodAIError, generate_jood_reply
from app.jood_company_ops import (
    CONTACT_TYPES,
    CompanyContact,
    append_turn,
    can_contact,
    conversation_key_for,
    load_recent_turns,
    trusted_context_for,
)
from app.jood_outbound import (
    _send_whatsloop_text,
    ensure_outbound_opening,
    outbound_instruction_context,
    outbound_intent_for,
)
from app.jood_policy import sanitize_jood_reply
from app.jood_whatsapp_import import ImportedContact, parse_contact_upload
from app.jood_whatsapp_settings import resolved_outreach_instruction
from app.jood_whatsapp_context import remember_outreach_context
from app.jood_catalog import (
    catalog_context,
    choose_featured_product,
    load_live_catalog,
    strict_product_message,
)
from app.jood_sales_playbook import featured_product_context


RIYADH_TIMEZONE = ZoneInfo("Asia/Riyadh")
CAMPAIGN_SEND_START_HOUR = 9
CAMPAIGN_SEND_END_HOUR = 22
CAMPAIGN_SEND_INTERVAL_SECONDS = 10 * 60
PAKGAT_MERCHANT_CAMPAIGN_SITE = "https://pakgat.com"
_ACTIVE_CAMPAIGN_RUNNERS: set[int] = set()


def approved_merchant_campaign_message(contact) -> str:
    activity_name = str(
        getattr(contact, "display_name", "")
        or getattr(contact, "business_name", "")
        or "نشاطكم"
    ).strip()
    return (
        "*مساكم الله بالخير ✨*\n\n"
        f"*معكم جود من منصة بكجات — {PAKGAT_MERCHANT_CAMPAIGN_SITE}*\n\n"
        f"أعجبنا نشاط *{activity_name}*، ونشوف عندكم فرصة ممتازة لـ *استقطاب عملاء جدد في الرياض* "
        "من خلال *كوبونات وعروض وبكجات مميزة*.\n\n"
        "*بكجات منصة متخصصة في مدينة الرياض*، ونعمل على ربط الأنشطة المميزة بعملاء يبحثون عن عروض وتجارب تستحق التجربة.\n\n"
        "التعاون معنا *بدون أي تكاليف مسبقة عليكم*، ونساعدكم في تجهيز العرض وإبرازه بشكل واضح وجذاب.\n\n"
        "إذا ناسبكم نبدأ، ردوا برقم واحد فقط:\n\n"
        "*1 — أرسلوا التفاصيل*\n"
        "*2 — لدي استفسار*"
    )


class JoodWhatsAppCampaign(core.Base):
    __tablename__ = "jood_whatsapp_campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255))
    contact_type: Mapped[str] = mapped_column(String(20), index=True)
    goal: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


class JoodWhatsAppDispatch(core.Base):
    __tablename__ = "jood_whatsapp_dispatches"
    __table_args__ = (
        UniqueConstraint("campaign_id", "contact_id", name="uq_jood_whatsapp_campaign_contact"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(Integer, index=True)
    contact_id: Mapped[int] = mapped_column(Integer, index=True)
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    provider_status: Mapped[str] = mapped_column(String(500), default="")
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


def _as_riyadh_time(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(RIYADH_TIMEZONE)


def campaign_send_window_open(value: datetime | None = None) -> bool:
    local = _as_riyadh_time(value)
    return CAMPAIGN_SEND_START_HOUR <= local.hour < CAMPAIGN_SEND_END_HOUR


def campaign_seconds_until_send_window(value: datetime | None = None) -> int:
    local = _as_riyadh_time(value)
    if campaign_send_window_open(local):
        return 0
    if local.hour < CAMPAIGN_SEND_START_HOUR:
        target = local.replace(
            hour=CAMPAIGN_SEND_START_HOUR,
            minute=0,
            second=0,
            microsecond=0,
        )
    else:
        target = (local + timedelta(days=1)).replace(
            hour=CAMPAIGN_SEND_START_HOUR,
            minute=0,
            second=0,
            microsecond=0,
        )
    return max(0, int((target - local).total_seconds()))


def campaign_contact_allowed(contact, contact_type: str) -> bool:
    return (
        str(getattr(contact, "contact_type", "") or "").strip().lower()
        == str(contact_type or "").strip().lower()
        and can_contact(contact)
    )


def next_whatsapp_campaign_contact(db: Session, campaign: JoodWhatsAppCampaign) -> CompanyContact | None:
    if campaign.status != "active":
        return None
    sent_ids = select(JoodWhatsAppDispatch.contact_id).where(
        JoodWhatsAppDispatch.campaign_id == campaign.id
    )
    return db.scalar(
        select(CompanyContact)
        .where(
            CompanyContact.contact_type == campaign.contact_type,
            CompanyContact.status == "active",
            ~CompanyContact.id.in_(sent_ids),
        )
        .order_by(CompanyContact.last_contact_at.asc().nullsfirst(), CompanyContact.id.asc())
        .limit(1)
    )


def queue_campaign_contacts(
    db: Session,
    campaign: JoodWhatsAppCampaign,
    contact_ids: Iterable[int] | None = None,
) -> int:
    existing_ids = set(
        db.scalars(
            select(JoodWhatsAppDispatch.contact_id).where(
                JoodWhatsAppDispatch.campaign_id == campaign.id
            )
        ).all()
    )
    conditions = [
        CompanyContact.contact_type == campaign.contact_type,
        CompanyContact.status == "active",
    ]
    selected_ids = {int(value) for value in contact_ids or []}
    if selected_ids:
        conditions.append(CompanyContact.id.in_(selected_ids))
    contacts = list(
        db.scalars(
            select(CompanyContact)
            .where(*conditions)
            .order_by(CompanyContact.id.asc())
        ).all()
    )
    queued = 0
    for contact in contacts:
        if contact.id in existing_ids or not campaign_contact_allowed(contact, campaign.contact_type):
            continue
        db.add(
            JoodWhatsAppDispatch(
                campaign_id=campaign.id,
                contact_id=contact.id,
                message="",
                status="queued",
                provider_status="",
            )
        )
        existing_ids.add(contact.id)
        queued += 1
    db.commit()
    return queued


def mark_latest_dispatch_replied(db: Session, contact_id: int) -> bool:
    dispatch = db.scalar(
        select(JoodWhatsAppDispatch)
        .where(
            JoodWhatsAppDispatch.contact_id == contact_id,
            JoodWhatsAppDispatch.status == "sent",
        )
        .order_by(JoodWhatsAppDispatch.sent_at.desc(), JoodWhatsAppDispatch.id.desc())
        .limit(1)
    )
    if not dispatch:
        return False
    dispatch.status = "replied"
    db.commit()
    return True


def requeue_failed_dispatches(db: Session, campaign: JoodWhatsAppCampaign) -> int:
    rows = list(
        db.scalars(
            select(JoodWhatsAppDispatch).where(
                JoodWhatsAppDispatch.campaign_id == campaign.id,
                JoodWhatsAppDispatch.status == "failed",
            )
        ).all()
    )
    for dispatch in rows:
        dispatch.status = "queued"
        dispatch.provider_status = ""
    if rows:
        campaign.status = "active"
        campaign.updated_at = datetime.now(timezone.utc)
    db.commit()
    return len(rows)


def _upsert_uploaded_contact(db: Session, item: ImportedContact) -> CompanyContact:
    contact = db.scalar(select(CompanyContact).where(CompanyContact.phone == item.phone))
    if not contact:
        contact = CompanyContact(phone=item.phone, contact_type=item.contact_type, status="active")
        db.add(contact)
    contact.contact_type = item.contact_type
    contact.display_name = item.display_name or contact.display_name
    contact.business_name = item.business_name or contact.business_name
    contact.city = item.city or contact.city
    contact.notes = item.notes or contact.notes
    if item.contact_type == "merchant" and not contact.merchant_stage:
        contact.merchant_stage = "new"
    if item.contact_type == "customer":
        contact.merchant_stage = None
    contact.updated_at = datetime.now(timezone.utc)
    db.flush()
    return contact


async def _deliver_campaign_dispatch(
    db: Session,
    campaign: JoodWhatsAppCampaign,
    dispatch: JoodWhatsAppDispatch,
) -> None:
    contact = db.get(CompanyContact, dispatch.contact_id)
    if not contact or not campaign_contact_allowed(contact, campaign.contact_type):
        dispatch.status = "skipped"
        dispatch.provider_status = "Contact unavailable or do-not-contact"
        db.commit()
        return

    dispatch.status = "generating"
    db.commit()
    mode = contact.contact_type if contact.contact_type in CONTACT_TYPES else "customer"
    instruction = resolved_outreach_instruction(db, mode, campaign.goal)
    history = load_recent_turns(db, contact.id, limit=8)
    trusted = trusted_context_for(instruction, mode)
    trusted += "\n" + outbound_instruction_context(mode, instruction)
    trusted += "\nThis is an approved automatic WhatsApp campaign. Write one concise personalized message and do not mention automation."
    if contact.display_name:
        trusted += f"\nKnown contact name: {contact.display_name}"
    if contact.business_name:
        trusted += f"\nKnown business name: {contact.business_name}"
    if contact.city:
        trusted += f"\nKnown city: {contact.city}"
    if contact.notes:
        trusted += f"\nApproved Company AI notes: {contact.notes[:1200]}"
    catalog = load_live_catalog(db) if mode == "customer" else []
    featured = choose_featured_product(catalog, instruction)
    if mode == "customer":
        trusted += "\n" + featured_product_context(featured)
        trusted += "\n" + catalog_context(catalog)
    try:
        if mode == "customer":
            if featured is None:
                raise RuntimeError("No approved Salla product is currently available")
            generated = strict_product_message(featured)
        elif mode == "merchant":
            generated = approved_merchant_campaign_message(contact)
        else:
            generated = await asyncio.to_thread(
                generate_jood_reply,
                instruction,
                history,
                mode,
                outbound_intent_for(mode),
                trusted,
            )
        approved_urls = {item.url for item in catalog}
        if mode == "merchant":
            approved_urls.add(PAKGAT_MERCHANT_CAMPAIGN_SITE)
            message = sanitize_jood_reply(generated, approved_urls=approved_urls)
        else:
            message = ensure_outbound_opening(
                sanitize_jood_reply(generated, approved_urls=approved_urls), mode, contact, featured
            )
        ok, provider = await asyncio.to_thread(_send_whatsloop_text, contact.phone, message)
        if not ok:
            raise RuntimeError(provider)
    except Exception as exc:
        dispatch.status = "failed"
        dispatch.provider_status = str(exc)[:500]
        db.commit()
        core.log_event(
            db,
            "jood_whatsapp_campaign_dispatch_failed",
            details=f"campaign={campaign.id}; contact={contact.id}; error={str(exc)[:180]}",
        )
        return

    dispatch.message = message
    dispatch.status = "sent"
    dispatch.provider_status = provider[:500]
    dispatch.sent_at = datetime.now(timezone.utc)
    append_turn(
        db,
        contact.id,
        "whatsapp",
        "assistant",
        message,
        conversation_key_for("whatsapp", contact.id),
    )
    presented = (
        [{"id": featured.id, "name": featured.name, "url": featured.url, "price": str(featured.price)}]
        if featured
        else []
    )
    remember_outreach_context(
        db, contact.id, mode, instruction, "campaign", message, presented_options=presented
    )
    if contact.contact_type == "merchant" and contact.merchant_stage in {None, "new"}:
        contact.merchant_stage = "contacted"
    db.commit()


def _next_queued_dispatch(db: Session, campaign_id: int) -> JoodWhatsAppDispatch | None:
    return db.scalar(
        select(JoodWhatsAppDispatch)
        .where(
            JoodWhatsAppDispatch.campaign_id == campaign_id,
            JoodWhatsAppDispatch.status == "queued",
        )
        .order_by(JoodWhatsAppDispatch.id.asc())
        .limit(1)
    )


async def process_campaign_queue(campaign_id: int) -> None:
    campaign_id = int(campaign_id)
    if campaign_id in _ACTIVE_CAMPAIGN_RUNNERS:
        return
    _ACTIVE_CAMPAIGN_RUNNERS.add(campaign_id)
    try:
        while True:
            delay = 0
            now = datetime.now(timezone.utc)
            with core.SessionLocal() as db:
                campaign = db.get(JoodWhatsAppCampaign, campaign_id)
                if not campaign or campaign.status not in {"active", "running", "scheduled"}:
                    return

                dispatch = _next_queued_dispatch(db, campaign.id)
                if not dispatch:
                    campaign.status = "completed"
                    campaign.updated_at = now
                    db.commit()
                    return

                if not campaign_send_window_open(now):
                    campaign.status = "scheduled"
                    campaign.updated_at = now
                    db.commit()
                    delay = campaign_seconds_until_send_window(now)
                else:
                    campaign.status = "running"
                    campaign.updated_at = now
                    db.commit()
                    await _deliver_campaign_dispatch(db, campaign, dispatch)

                    remaining = _next_queued_dispatch(db, campaign.id)
                    campaign.updated_at = datetime.now(timezone.utc)
                    if not remaining:
                        campaign.status = "completed"
                        db.commit()
                        return
                    campaign.status = "active"
                    db.commit()
                    delay = CAMPAIGN_SEND_INTERVAL_SECONDS

            await asyncio.sleep(max(1, delay))
    finally:
        _ACTIVE_CAMPAIGN_RUNNERS.discard(campaign_id)


@core.app.on_event("startup")
async def resume_queued_whatsapp_campaigns() -> None:
    with core.SessionLocal() as db:
        campaign_ids = list(
            db.scalars(
                select(JoodWhatsAppCampaign.id)
                .join(
                    JoodWhatsAppDispatch,
                    JoodWhatsAppDispatch.campaign_id == JoodWhatsAppCampaign.id,
                )
                .where(
                    JoodWhatsAppCampaign.status.in_(("active", "running", "scheduled")),
                    JoodWhatsAppDispatch.status == "queued",
                )
                .distinct()
                .order_by(JoodWhatsAppCampaign.id.asc())
            ).all()
        )
    for campaign_id in campaign_ids:
        asyncio.create_task(process_campaign_queue(int(campaign_id)))


@core.app.post("/admin/company/jood/whatsapp-campaigns/upload")
async def upload_and_start_whatsapp_campaign(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    name: str = Form(""),
    contact_type: str = Form("merchant"),
    instruction: str = Form(""),
    db: Session = Depends(core.get_db),
):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect
    clean_type = contact_type.strip().lower()
    if clean_type not in CONTACT_TYPES:
        raise HTTPException(status_code=400, detail="Invalid contact type")
    body = await file.read(2_000_001)
    if len(body) > 2_000_000:
        raise HTTPException(status_code=413, detail="File is too large")
    try:
        imported = parse_contact_upload(file.filename or "", body, clean_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    contact_ids: list[int] = []
    for item in imported:
        if item.contact_type != clean_type:
            item = ImportedContact(
                phone=item.phone,
                contact_type=clean_type,
                display_name=item.display_name,
                business_name=item.business_name,
                city=item.city,
                notes=item.notes,
            )
        contact = _upsert_uploaded_contact(db, item)
        if can_contact(contact):
            contact_ids.append(contact.id)
    campaign = JoodWhatsAppCampaign(
        name=(name.strip() or f"Jood {clean_type.title()} WhatsApp")[:255],
        contact_type=clean_type,
        goal=instruction.strip()[:5000],
        status="active",
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    queued = queue_campaign_contacts(db, campaign, contact_ids)
    if queued:
        background_tasks.add_task(process_campaign_queue, campaign.id)
    else:
        campaign.status = "completed"
        db.commit()
    core.log_event(db, "jood_whatsapp_campaign_uploaded", details=f"campaign={campaign.id}; queued={queued}")
    return RedirectResponse(
        f"/admin/company/jood/whatsapp-campaigns?started={campaign.id}&queued={queued}",
        status_code=303,
    )


@core.app.post("/admin/company/jood/whatsapp-campaigns/{campaign_id}/retry")
async def retry_whatsapp_campaign(
    campaign_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(core.get_db),
):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect
    campaign = db.get(JoodWhatsAppCampaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="WhatsApp campaign not found")
    queued = requeue_failed_dispatches(db, campaign)
    if queued:
        background_tasks.add_task(process_campaign_queue, campaign.id)
    return RedirectResponse(
        f"/admin/company/jood/whatsapp-campaigns?started={campaign.id}&queued={queued}",
        status_code=303,
    )


def _admin_redirect(request: Request):
    try:
        core.require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)
    return None


@core.app.post("/admin/company/jood/control/whatsapp-campaigns")
async def create_whatsapp_campaign(request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect
    form = parse_qs((await request.body()).decode("utf-8", errors="ignore"))
    value = lambda name, default="": str((form.get(name) or [default])[0]).strip()
    contact_type = value("contact_type", "customer").lower()
    goal = value("goal")
    if contact_type not in CONTACT_TYPES:
        raise HTTPException(status_code=400, detail="Valid contact type is required")
    row = JoodWhatsAppCampaign(
        name=(value("name") or f"Jood {contact_type.title()} WhatsApp")[:255],
        contact_type=contact_type,
        goal=goal[:5000],
        status="active",
    )
    db.add(row)
    db.commit()
    return RedirectResponse("/admin/company/jood/control", status_code=303)


@core.app.post("/admin/company/jood/whatsapp-campaigns/{campaign_id}/next")
async def send_next_whatsapp_campaign_contact(
    campaign_id: int,
    request: Request,
    db: Session = Depends(core.get_db),
):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect
    campaign = db.get(JoodWhatsAppCampaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="WhatsApp campaign not found")
    contact = next_whatsapp_campaign_contact(db, campaign)
    if not contact:
        campaign.status = "completed"
        campaign.updated_at = datetime.now(timezone.utc)
        db.commit()
        return RedirectResponse("/admin/company/jood/control", status_code=303)

    mode = contact.contact_type if contact.contact_type in CONTACT_TYPES else "customer"
    intent = outbound_intent_for(mode)
    history = load_recent_turns(db, contact.id, limit=8)
    trusted = trusted_context_for(campaign.goal, mode)
    trusted += "\n" + outbound_instruction_context(mode, campaign.goal)
    trusted += "\nThis message belongs to an approved Company AI WhatsApp campaign. Send one concise, non-spammy first-touch or follow-up message appropriate to the available history."
    if contact.display_name:
        trusted += f"\nKnown contact name: {contact.display_name}"
    if contact.business_name:
        trusted += f"\nKnown business name: {contact.business_name}"
    if contact.city:
        trusted += f"\nKnown city: {contact.city}"
    if contact.notes:
        trusted += f"\nApproved Company AI notes: {contact.notes[:1200]}"
    catalog = load_live_catalog(db) if mode == "customer" else []
    featured = choose_featured_product(catalog, campaign.goal)
    if mode == "customer":
        trusted += "\n" + featured_product_context(featured)
        trusted += "\n" + catalog_context(catalog)

    try:
        if mode == "customer":
            if featured is None:
                raise JoodAIError("No approved Salla product is currently available")
            generated = strict_product_message(featured)
        elif mode == "merchant":
            generated = approved_merchant_campaign_message(contact)
        else:
            generated = await asyncio.to_thread(
                generate_jood_reply,
                campaign.goal,
                history,
                mode,
                intent,
                trusted,
            )
    except JoodAIError as exc:
        core.log_event(
            db,
            "jood_whatsapp_campaign_ai_failed",
            details=f"campaign={campaign.id}; contact={contact.id}; error={str(exc)[:150]}",
        )
        raise HTTPException(status_code=502, detail="Jood AI generation failed") from exc

    approved_urls = {item.url for item in catalog}
    if mode == "merchant":
        approved_urls.add(PAKGAT_MERCHANT_CAMPAIGN_SITE)
        message = sanitize_jood_reply(generated, approved_urls=approved_urls)
    else:
        message = ensure_outbound_opening(
            sanitize_jood_reply(generated, approved_urls=approved_urls), mode, contact, featured
        )
    ok, provider = await asyncio.to_thread(_send_whatsloop_text, contact.phone, message)
    if not ok:
        core.log_event(
            db,
            "jood_whatsapp_campaign_send_failed",
            details=f"campaign={campaign.id}; contact={contact.id}; provider={provider[:220]}",
        )
        raise HTTPException(status_code=502, detail="WhatsApp send failed")

    dispatch = JoodWhatsAppDispatch(
        campaign_id=campaign.id,
        contact_id=contact.id,
        message=message,
        status="sent",
        provider_status=provider[:500],
    )
    db.add(dispatch)
    append_turn(
        db,
        contact.id,
        "whatsapp",
        "assistant",
        message,
        conversation_key_for("whatsapp", contact.id),
    )
    presented = (
        [{"id": featured.id, "name": featured.name, "url": featured.url, "price": str(featured.price)}]
        if featured
        else []
    )
    remember_outreach_context(
        db, contact.id, mode, campaign.goal, "campaign", message, presented_options=presented
    )
    if contact.contact_type == "merchant" and contact.merchant_stage in {None, "new"}:
        contact.merchant_stage = "contacted"
    campaign.updated_at = datetime.now(timezone.utc)
    db.commit()
    core.log_event(
        db,
        "jood_whatsapp_campaign_sent",
        details=f"campaign={campaign.id}; contact={contact.id}; type={contact.contact_type}",
    )
    return RedirectResponse("/admin/company/jood/control", status_code=303)