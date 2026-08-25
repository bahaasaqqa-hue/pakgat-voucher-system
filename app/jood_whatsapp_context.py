from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, inspect, select, text
from sqlalchemy.orm import Mapped, Session, mapped_column

from app import application as core


MERCHANT_CAMPAIGN_CHOICE_ONE_REPLY = """أبشروا بالسعد 🙌

خلّونا نوضح لكم فكرة «بكجات» على السريع:

إحنا ما نكتفي بنشر كوبون عادي. نشتغل على عرضكم كحملة تسويق ومبيعات متكاملة:

✅ نجهز الفكرة والتصميم والمحتوى ونبرزها في منصتنا.
✅ نسوّق للعرض عبر السوشال ميديا وقنواتنا لاستقطاب عملاء جدد في الرياض.
✅ بدون أي رسوم أو تكاليف مسبقة عليكم. نسبتنا فقط من المبيعات الفعلية اللي تجيكم عن طريقنا.
✅ طريقة الاستبدال سهلة وآمنة. العميل يستلم قسيمة رقمية، وأنتم تمسحونها بالجوال خلال ثوانٍ وتنتهي العملية بسهولة.

يعني من الآخر: أنتم تقدمون الخدمة، وإحنا نجهز العرض ونسوّق له وندير القسيمة.

والتعاون طبعًا بعقد رسمي وموثق يحفظ حقوق الجميع 🤝

والخطوة الجاية بسيطة 👌
راح يتواصل معكم مسؤول الشراكات في بكجات مباشرة، ويكمل معكم تفاصيل العرض وآلية التعاون والعقد، ونرتب الإطلاق سوا.

تشرفنا فيكم، وبإذن الله تكون بداية تعاون جميل ومثمر 🚀"""


@dataclass(frozen=True)
class MerchantCampaignChoiceAction:
    reply: str
    handoff_kind: str
    handoff_details: str
    next_stage: str


def infer_last_commitment(message: str) -> str:
    clean = " ".join(str(message or "").strip().split())
    commitment_markers = ("أرسل لك", "ارسل لك", "أرسل لكم", "سأرسل", "راح أرسل", "أشاركك", "أعطيك")
    return clean[:1000] if any(marker in clean for marker in commitment_markers) else ""


class JoodWhatsAppContext(core.Base):
    __tablename__ = "jood_whatsapp_contexts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contact_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    mode: Mapped[str] = mapped_column(String(20), index=True)
    objective: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(30), default="individual", index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    state_json: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


def ensure_jood_whatsapp_context_schema() -> None:
    inspector = inspect(core.engine)
    if "jood_whatsapp_contexts" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("jood_whatsapp_contexts")}
    if "state_json" not in columns:
        with core.engine.begin() as connection:
            connection.execute(text("ALTER TABLE jood_whatsapp_contexts ADD COLUMN state_json JSON"))


def remember_outreach_context(
    db: Session,
    contact_id: int,
    mode: str,
    objective: str,
    source: str,
    last_commitment: str = "",
    presented_options: list[dict[str, str]] | None = None,
) -> JoodWhatsAppContext:
    row = db.scalar(select(JoodWhatsAppContext).where(JoodWhatsAppContext.contact_id == contact_id))
    if not row:
        row = JoodWhatsAppContext(contact_id=contact_id)
        db.add(row)
    row.mode = "merchant" if str(mode).strip().lower() == "merchant" else "customer"
    row.objective = str(objective or "").strip()[:12000]
    row.source = str(source or "individual").strip()[:30]
    row.active = True
    persona = "outbound_merchant_acquisition" if row.mode == "merchant" else "outbound_customer_sales"
    row.state_json = {
        "direction": "outbound",
        "persona": persona,
        "objective": row.objective,
        "current_stage": "opening_sent",
        "last_commitment": infer_last_commitment(last_commitment),
        "collected_info": {},
        "presented_options": list(presented_options or []),
        "selected_product_id": (
            str(presented_options[0].get("id") or "")[:100]
            if presented_options and isinstance(presented_options[0], dict)
            else ""
        ),
        "status": "active",
    }
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return row


def update_outreach_state(
    db: Session,
    contact_id: int,
    *,
    next_stage: str,
    last_commitment: str,
    collected_info: dict | None = None,
    presented_options: list[dict[str, str]] | None = None,
    selected_product_id: str = "",
    status: str = "active",
) -> JoodWhatsAppContext | None:
    row = active_outreach_context(db, contact_id)
    if not row:
        return None
    state = dict(row.state_json or {})
    state["current_stage"] = str(next_stage or state.get("current_stage") or "active")[:80]
    state["last_commitment"] = str(last_commitment or "")[:1000]
    merged_info = dict(state.get("collected_info") or {})
    merged_info.update(dict(collected_info or {}))
    state["collected_info"] = merged_info
    if presented_options is not None:
        state["presented_options"] = list(presented_options)
    if selected_product_id:
        state["selected_product_id"] = str(selected_product_id)[:100]
    state["status"] = str(status or "active")[:40]
    row.state_json = state
    row.active = state["status"] == "active"
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


def merchant_campaign_choice_action(
    message: str,
    mode: str,
    context_row: JoodWhatsAppContext | None,
) -> MerchantCampaignChoiceAction | None:
    if str(mode or "").strip().lower() != "merchant" or context_row is None:
        return None

    state = dict(context_row.state_json or {})
    if state.get("direction") != "outbound" or state.get("persona") != "outbound_merchant_acquisition":
        return None

    choice = " ".join(str(message or "").strip().split())
    if choice not in {"1", "١"}:
        return None

    return MerchantCampaignChoiceAction(
        reply=MERCHANT_CAMPAIGN_CHOICE_ONE_REPLY,
        handoff_kind="merchant_partnership",
        handoff_details="merchant_campaign_choice_1_ready_for_partnership_manager",
        next_stage="handed_off",
    )


def inbound_outreach_context(db: Session, contact_id: int) -> str:
    row = active_outreach_context(db, contact_id)
    if not row or not row.objective.strip():
        return ""
    return (
        "This is an ongoing outbound conversation initiated by Pakgat, not a new inbound support request.\n"
        f"Persisted conversation state JSON: {json.dumps(row.state_json or {}, ensure_ascii=False)}\n"
        "Use the real conversation history to understand what was already offered and what the contact means now. "
        "Answer naturally to any agreement, question, objection, refusal, or topic change. Continue the objective when relevant, "
        "but do not force a scripted reply and do not restart with 'How can I help?'."
    )
