"""Focused opportunity feed for the Pakgat AI Company pilot.

The CEO asked the pilot to match the intended production radar: focus first on
Cobone, Noon Saudi and Amazon Saudi, prioritising coupon/discount opportunities
and best-selling products.  This module does not pretend to be the final live
scraper.  It stores a small, evidence-based pilot feed from the latest public
scan and archives the older unrelated pilot examples so the UI/workflow can be
tested against the right kinds of opportunities.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ai_company
from app import application as core


SCAN_DATE = "19-08-2026"

LEGACY_PILOT_SOURCES = {
    "وزارة التجارة · موسم تخفيضات 2026",
    "American Express Saudi · Auto Chapeau",
    "Riyad Bank · Drs Lounge Clinics",
    "Riyad Bank · Arriyadh Roaster",
    "Four Seasons Riyadh",
    "Platinumlist Riyadh · BattleKart",
    "Platinumlist Riyadh · Fontana Circus",
}

FOCUSED_OPPORTUNITIES = [
    {
        "priority": "P1",
        "source": "كوبون · الرياض",
        "title": "AMC: تذكرة سينما + فشار + مشروب — عرض رائج",
        "score": 97.0,
        "details": (
            "كوبون يعرض تذكرة AMC مع فشار ومشروب بسعر 60 ر.س بدل 120 ر.س (توفير 50%)، "
            "وموسومة كالأفضل مبيعاً مع 904 قسائم مباعة وقت الفحص. "
            "فرصة بكجات: البحث عن عرض ترفيهي مماثل أو أفضل مع شريك سينما/ترفيه في الرياض، "
            "أو التفاوض على قيمة إضافية حصرية. "
            f"تاريخ الفحص العام: {SCAN_DATE}. يجب التحقق من استمرار العرض قبل التواصل."
        ),
    },
    {
        "priority": "P1",
        "source": "كوبون · الرياض",
        "title": "بريرا اليرموك: عشاء مأكولات بحرية — الأفضل مبيعاً",
        "score": 94.0,
        "details": (
            "كوبون يعرض عشاء مأكولات بحرية في فندق بريرا اليرموك بسعر 89 ر.س بدل 149 ر.س "
            "(توفير 40%) وموسوم كالأفضل مبيعاً وقت الفحص. "
            "فرصة بكجات: استهداف الفندق أو بديل منافس بعرض عشاء/بوفيه حصري للرياض. "
            f"تاريخ الفحص العام: {SCAN_DATE}. تحقق من الشروط والتوفر قبل التواصل."
        ),
    },
    {
        "priority": "P1",
        "source": "نون · الأفضل مبيعاً + كوبون",
        "title": "Goui باور بانك 20000mAh — #1 وخصم قوي",
        "score": 98.0,
        "details": (
            "صفحة أفضل العروض مبيعاً في نون أظهرت Goui 20000mAh بسعر 59 ر.س بدل 199 ر.س "
            "(خصم 70%)، #1 في الباور بانك، و+7000 مبيعة مؤخراً، مع خصم إضافي ظاهر وقت الفحص. "
            "فرصة بكجات: المنتج مرشح قوي لفئة الأجهزة/الهدايا؛ ابحث عن مورد محلي أو شريك يقدم سعراً يسمح ببكج منافس. "
            f"تاريخ الفحص العام: {SCAN_DATE}. تحقق من السعر والكوبون لحظة التنفيذ."
        ),
    },
    {
        "priority": "P1",
        "source": "نون · منطقة الكوبونات",
        "title": "UGREEN مشترك كهرباء 6 في 1 — Best Seller + كوبون",
        "score": 95.0,
        "details": (
            "منطقة كوبونات نون أظهرت UGREEN 6-in-1 Power Strip كمنتج Best Seller، #2 في فئته، "
            "+1400 مبيعة مؤخراً، مع خصم/كوبون إضافي ظاهر وقت الفحص. "
            "فرصة بكجات: منتج عملي مناسب لبكجات التقنية/المكتب ويمكن البحث عن مورد سعودي بسعر جملة. "
            f"تاريخ الفحص العام: {SCAN_DATE}. تحقق من الكوبون والسعر الحالي قبل الشراء أو التفاوض."
        ),
    },
    {
        "priority": "P1",
        "source": "نون · منطقة الكوبونات",
        "title": "iPhone 17 Pro Max — Best Seller + خصم إضافي",
        "score": 88.0,
        "details": (
            "نون أظهر iPhone 17 Pro Max 256GB ضمن منتجات الكوبون/الأفضل مبيعاً، بترتيب مرتفع في الهواتف "
            "وخصم إضافي ظاهر وقت الفحص. القيمة ليست في منافسة نون مباشرة بالسعر فقط؛ بل في رصد الطلب "
            "واستخدامه كإشارة لفئات ملحقات الهاتف والهدايا التقنية ذات الهامش الأعلى. "
            f"تاريخ الفحص العام: {SCAN_DATE}. تحقق من السعر والكوبون قبل أي قرار."
        ),
    },
    {
        "priority": "P2",
        "source": "أمازون السعودية · Best Seller",
        "title": "UGREEN باور بانك 20000mAh — مرشح منتج مطلوب",
        "score": 86.0,
        "details": (
            "نتائج Amazon.sa المفهرسة أظهرت UGREEN 20000mAh كـ Best Seller في فئة الباور بانك، "
            "مع Limited Time Deal و+500 مشتري في شهر ضمن النتيجة المفهرسة. "
            "فرصة بكجات: تقاطع الطلب مع نون يجعل فئة الباور بانك مرشحاً واضحاً للبحث عن مورد/سعر جملة. "
            "تنبيه: فهرسة أمازون العامة قد تتأخر؛ يجب التحقق المباشر من صفحة أمازون قبل اعتبار السعر أو الترتيب حالياً."
        ),
    },
    {
        "priority": "P2",
        "source": "أمازون السعودية · موسم العودة للمدارس",
        "title": "رادار العودة للمدارس: استخراج Best Sellers ذات كوبونات",
        "score": 84.0,
        "details": (
            "Amazon Seller Central السعودية يعلن حملة العودة للمدارس من 20 إلى 31 أغسطس 2026 مع Deals/Coupons. "
            "فرصة بكجات: خلال الحملة نراقب المنتجات التي تجمع بين Best Seller + Deal/Coupon ونحوّلها مباشرة "
            "إلى فرص توريد أو بكجات تقنية/دراسية. هذا Trigger للرادار وليس منتجاً نهائياً بحد ذاته."
        ),
    },
]


def sync_focused_feed(db: Session) -> tuple[int, int]:
    """Archive legacy pilot examples and ensure the focused pilot feed exists."""
    now = datetime.now(timezone.utc)
    archived = 0
    created = 0

    legacy_rows = list(
        db.scalars(
            select(ai_company.CompanyOpportunity).where(
                ai_company.CompanyOpportunity.source.in_(LEGACY_PILOT_SOURCES),
                ai_company.CompanyOpportunity.status.notin_(["won", "lost", "archived"]),
            )
        ).all()
    )
    for row in legacy_rows:
        row.status = "archived"
        row.updated_at = now
        archived += 1

    for item in FOCUSED_OPPORTUNITIES:
        existing = db.scalar(
            select(ai_company.CompanyOpportunity).where(
                ai_company.CompanyOpportunity.source == item["source"],
                ai_company.CompanyOpportunity.title == item["title"],
            )
        )
        if existing:
            continue
        db.add(
            ai_company.CompanyOpportunity(
                priority=item["priority"],
                source=item["source"],
                title=item["title"],
                details=item["details"][:1500],
                score=float(item["score"]),
                status="new",
                created_at=now,
                updated_at=now,
            )
        )
        created += 1

    if archived or created:
        db.commit()
        core.log_event(
            db,
            "focused_opportunity_feed_sync",
            details=f"date={SCAN_DATE}; created={created}; archived_legacy={archived}",
        )
    return created, archived
