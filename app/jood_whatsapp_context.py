from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app import application as core


class JoodWhatsAppContext(core.Base):
    __tablename__ = "jood_whatsapp_contexts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contact_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    mode: Mapped[str] = mapped_column(String(20), index=True)
    objective: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(30), default="individual", index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


def remember_outreach_context(
    db: Session,
    contact_id: int,
    mode: str,
    objective: str,
    source: str,
) -> JoodWhatsAppContext:
    row = db.scalar(select(JoodWhatsAppContext).where(JoodWhatsAppContext.contact_id == contact_id))
    if not row:
        row = JoodWhatsAppContext(contact_id=contact_id)
        db.add(row)
    row.mode = "merchant" if str(mode).strip().lower() == "merchant" else "customer"
    row.objective = str(objective or "").strip()[:12000]
    row.source = str(source or "individual").strip()[:30]
    row.active = True
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return row


def active_outreach_context(db: Session, contact_id: int) -> JoodWhatsAppContext | None:
    return db.scalar(
        select(JoodWhatsAppContext).where(
            JoodWhatsAppContext.contact_id == contact_id,
            JoodWhatsAppContext.active.is_(True),
        )
    )


def inbound_outreach_context(db: Session, contact_id: int) -> str:
    row = active_outreach_context(db, contact_id)
    if not row or not row.objective.strip():
        return ""
    return (
        "This is an ongoing outbound conversation initiated by Pakgat, not a new inbound support request.\n"
        f"Persisted outreach mode: {row.mode}\n"
        f"Persisted outreach objective: {row.objective}\n"
        "Use the real conversation history to understand what was already offered and what the contact means now. "
        "Answer naturally to any agreement, question, objection, refusal, or topic change. Continue the objective when relevant, "
        "but do not force a scripted reply and do not restart with 'How can I help?'."
    )
