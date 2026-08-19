"""Source evidence for Pakgat AI Company opportunities.

Keeps public source links separate from the core opportunity table so existing
production databases do not need an ALTER TABLE migration.  New evidence rows
are safe to create with SQLAlchemy metadata on the next app start.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Integer, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app import ai_company
from app import application as core


class OpportunityEvidence(core.Base):
    __tablename__ = "opportunity_evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    opportunity_id: Mapped[int] = mapped_column(Integer, index=True)
    source_name: Mapped[str] = mapped_column(String(180))
    source_url: Mapped[str] = mapped_column(String(1200))
    link_label: Mapped[str] = mapped_column(String(120), default="فتح المصدر")
    evidence_type: Mapped[str] = mapped_column(String(40), default="direct")
    image_url: Mapped[Optional[str]] = mapped_column(String(1200), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    is_primary: Mapped[int] = mapped_column(Integer, default=1, index=True)
    verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


KNOWN_EVIDENCE = {
    "AMC: تذكرة سينما + فشار + مشروب — عرض رائج": [
        {
            "source_name": "كوبون · AMC",
            "source_url": "https://www.cobone.com/ar/deals/riyadh/ticket-popcorn-soft-drink-amc-cinemas/219844",
            "link_label": "فتح العرض في كوبون",
            "evidence_type": "direct",
        }
    ],
    "بريرا اليرموك: عشاء مأكولات بحرية — الأفضل مبيعاً": [
        {
            "source_name": "كوبون · بريرا اليرموك",
            "source_url": "https://www.cobone.com/ar/deals/hot-now-riyadh/1-seafood-dinner-braira-alyarmouk-hotel/220127",
            "link_label": "فتح العرض في كوبون",
            "evidence_type": "direct",
        }
    ],
    "Goui باور بانك 20000mAh — #1 وخصم قوي": [
        {
            "source_name": "نون السعودية",
            "source_url": "https://www.noon.com/saudi-en/search?q=Goui%2020000mAh%20power%20bank",
            "link_label": "فتح بحث المنتج في نون",
            "evidence_type": "search",
            "note": "رابط بحث سريع لأن رابط صفحة المنتج المباشر لم يثبت في الفهرسة وقت الرصد.",
        }
    ],
    "UGREEN مشترك كهرباء 6 في 1 — Best Seller + كوبون": [
        {
            "source_name": "نون السعودية · UGREEN",
            "source_url": "https://www.noon.com/saudi-en/6-in-1-power-strip-extension-plug-multiple-3-ac-outlet-sockets-usb-c-fast-charger-3-usb-ports-triple-uk-plug-extender-extension-board-usb-charging-station-surge-protector-for-kitchen-home-office-accessories-black/N70029844V/p/",
            "link_label": "فتح المنتج في نون",
            "evidence_type": "direct",
        }
    ],
    "iPhone 17 Pro Max — Best Seller + خصم إضافي": [
        {
            "source_name": "نون السعودية · Apple",
            "source_url": "https://www.noon.com/saudi-en/apple-iphone-17-pro-max/apple/",
            "link_label": "فتح منتجات iPhone 17 Pro Max",
            "evidence_type": "category",
        }
    ],
    "UGREEN باور بانك 20000mAh — مرشح منتج مطلوب": [
        {
            "source_name": "أمازون السعودية · بحث المنتج",
            "source_url": "https://www.amazon.sa/s?k=UGREEN+20000mAh+Power+Bank+22.5W",
            "link_label": "فتح المنتج/البحث في أمازون",
            "evidence_type": "search",
            "note": "أمازون لم يوفّر لنا رابط المنتج المباشر بثبات من الفهرسة؛ هذا الرابط يصل للمطابقة بسرعة.",
        },
        {
            "source_name": "أمازون السعودية · Best Sellers",
            "source_url": "https://www.amazon.sa/-/en/gp/bestsellers/electronics",
            "link_label": "فتح قائمة Best Sellers",
            "evidence_type": "category",
            "is_primary": 0,
        },
        {
            "source_name": "نون السعودية · تحقق متقاطع",
            "source_url": "https://www.noon.com/saudi-en/~ugreen/20000-mah-20000mah-22-5w-power-bank-fast-charging-2a1c-pd-3-0-usb-c-input-output-portable-charger-with-digital-display-includes-cable-for-samsung-galaxy-s25-s24-ultra-ipad-airpods-20000mah-22-5w/N70121515V/p/",
            "link_label": "فتح المنتج المطابق في نون",
            "evidence_type": "cross_check",
            "is_primary": 0,
        },
    ],
    "رادار العودة للمدارس: استخراج Best Sellers ذات كوبونات": [
        {
            "source_name": "Amazon Seller Central السعودية",
            "source_url": "https://sellercentral.amazon.sa/",
            "link_label": "فتح Amazon Seller Central",
            "evidence_type": "campaign",
        }
    ],
}


def upsert_evidence(
    db: Session,
    opportunity_id: int,
    source_name: str,
    source_url: str,
    link_label: str = "فتح المصدر",
    evidence_type: str = "direct",
    image_url: str = "",
    note: str = "",
    is_primary: int = 1,
) -> OpportunityEvidence:
    row = db.scalar(
        select(OpportunityEvidence).where(
            OpportunityEvidence.opportunity_id == opportunity_id,
            OpportunityEvidence.source_url == source_url,
        )
    )
    now = datetime.now(timezone.utc)
    if row is None:
        row = OpportunityEvidence(
            opportunity_id=opportunity_id,
            source_name=source_name,
            source_url=source_url,
            link_label=link_label,
            evidence_type=evidence_type,
            image_url=image_url or None,
            note=note or None,
            is_primary=int(bool(is_primary)),
            verified_at=now,
        )
        db.add(row)
    else:
        row.source_name = source_name
        row.link_label = link_label
        row.evidence_type = evidence_type
        row.image_url = image_url or row.image_url
        row.note = note or row.note
        row.is_primary = int(bool(is_primary))
        row.verified_at = now
    return row


def sync_known_evidence(db: Session) -> int:
    changed = 0
    for title, entries in KNOWN_EVIDENCE.items():
        opportunity = db.scalar(
            select(ai_company.CompanyOpportunity)
            .where(ai_company.CompanyOpportunity.title == title)
            .order_by(ai_company.CompanyOpportunity.id.desc())
            .limit(1)
        )
        if not opportunity:
            continue
        for item in entries:
            existing = db.scalar(
                select(OpportunityEvidence.id).where(
                    OpportunityEvidence.opportunity_id == opportunity.id,
                    OpportunityEvidence.source_url == item["source_url"],
                )
            )
            upsert_evidence(
                db,
                opportunity.id,
                item["source_name"],
                item["source_url"],
                item.get("link_label", "فتح المصدر"),
                item.get("evidence_type", "direct"),
                item.get("image_url", ""),
                item.get("note", ""),
                item.get("is_primary", 1),
            )
            if not existing:
                changed += 1
    if changed:
        db.commit()
        core.log_event(db, "opportunity_evidence_synced", details=f"created={changed}")
    else:
        db.commit()
    return changed


def evidence_for(db: Session, opportunity_id: int) -> list[OpportunityEvidence]:
    sync_known_evidence(db)
    return list(
        db.scalars(
            select(OpportunityEvidence)
            .where(OpportunityEvidence.opportunity_id == opportunity_id)
            .order_by(OpportunityEvidence.is_primary.desc(), OpportunityEvidence.id.asc())
        ).all()
    )


def primary_evidence(db: Session, opportunity_id: int) -> Optional[OpportunityEvidence]:
    rows = evidence_for(db, opportunity_id)
    return rows[0] if rows else None
