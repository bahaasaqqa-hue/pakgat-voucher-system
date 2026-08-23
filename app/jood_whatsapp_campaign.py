from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from urllib.parse import parse_qs

from fastapi import Depends, HTTPException, Request
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
from app.jood_outbound import _send_whatsloop_text, outbound_instruction_context, outbound_intent_for
from app.jood_policy import sanitize_jood_reply


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
    status: Mapped[str] = mapped_column(String(30), default="sent", index=True)
    provider_status: Mapped[str] = mapped_column(String(500), default="")
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


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
    if contact_type not in CONTACT_TYPES or not goal:
        raise HTTPException(status_code=400, detail="Contact type and campaign goal are required")
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

    try:
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

    message = sanitize_jood_reply(generated)
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
