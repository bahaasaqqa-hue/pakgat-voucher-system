"""Arabic UI layer for Pakgat AI Company and the admin navigation.

The operational/data model keeps its stable English machine values internally.
This module changes only what the CEO/admin sees in HTML. It also adds a direct
Pakgat AI Company entry to the shared admin navigation.
"""

from __future__ import annotations

from fastapi import Request
from starlette.responses import Response

from app import application as core


# ---------------------------------------------------------------------------
# Shared admin navigation: keep the whole visible header Arabic and expose the
# AI Company control center directly from every admin page.
# ---------------------------------------------------------------------------

_original_page_shell = core.page_shell


def _arabic_admin_page_shell(title: str, body: str, admin: bool = False) -> str:
    html = _original_page_shell(title, body, admin=admin)

    if admin and 'href="/admin/company"' not in html:
        marker = '<a class="btn btn-muted" href="/admin">لوحة الإدارة</a>'
        ai_link = '<a class="btn btn-muted" href="/admin/company">شركة بكجات الذكية</a>'
        html = html.replace(marker, marker + ai_link, 1)

    html = html.replace("<small>Pakgat Voucher System</small>", "<small>نظام قسائم بكجات</small>")
    html = html.replace(" | Pakgat</title>", " | بكجات</title>")
    return html


core.page_shell = _arabic_admin_page_shell


# ---------------------------------------------------------------------------
# Company-area Arabic localization.
# The longer phrases are applied first, then shorter labels. Machine values in
# the DB remain unchanged, so integrations/queries are not affected.
# ---------------------------------------------------------------------------

_PHRASES = {
    "Pakgat AI Company — Control Center": "شركة بكجات الذكية — مركز التحكم",
    "Pakgat AI Company · Salla signed data · Google Data Hub": "شركة بكجات الذكية · بيانات سلة الموقعة · مركز بيانات جوجل",
    "Pakgat AI Company · Google Cloud": "شركة بكجات الذكية · سحابة جوجل",
    "Google Cloud · Data Hub · CEO Dashboard · Monitoring": "سحابة جوجل · مركز البيانات · لوحة المدير التنفيذي · المراقبة",
    "Market · Products · Pricing · SEO · Merchants · Growth": "السوق · المنتجات · التسعير · تحسين محركات البحث · التجار · النمو",
    "Salla · Sales & Orders": "سلة · المبيعات والطلبات",
    "Growth & Product Intelligence": "النمو وذكاء المنتجات",
    "Sales & Growth": "المبيعات والنمو",
    "Growth & Products": "النمو والمنتجات",
    "Product Performance — Confirmed Sales": "أداء المنتجات — المبيعات المؤكدة",
    "Blueprint KPI Coverage": "تغطية مؤشرات الأداء في المخطط المرجعي",
    "Connection Coverage": "تغطية الاتصال",
    "Top Products Seen": "أكثر المنتجات ظهورًا",
    "Latest Product Lines": "أحدث بنود المنتجات",
    "Latest Orders": "أحدث الطلبات",
    "Source Inventory": "سجل مصادر البيانات",
    "Connected · Readable · Writable · Needs Integration": "متصل · قابل للقراءة · قابل للكتابة · يحتاج ربط",
    "Data Sources": "مصادر البيانات",
    "Open Alerts": "التنبيهات المفتوحة",
    "Critical Alerts": "التنبيهات الحرجة",
    "CEO Decisions / Tasks": "قرارات ومهام المدير التنفيذي",
    "Company Health": "صحة الشركة",
    "Local Partner Products": "منتجات الشركاء المحلية",
    "Salla Webhooks": "أحداث سلة",
    "Salla OAuth": "تفويض سلة",
    "Salla OAuth / Merchant API": "تفويض سلة / واجهة التاجر",
    "Salla Products / Inventory": "منتجات ومخزون سلة",
    "Salla Abandoned Carts": "السلات المتروكة في سلة",
    "Salla Reviews": "تقييمات سلة",
    "Google Analytics": "إحصاءات جوجل",
    "Google Search Console": "أدوات مشرفي المواقع من جوجل",
    "Google Compute Engine": "محرك حوسبة جوجل",
    "Google Trends / Web": "مؤشرات جوجل / الويب",
    "Orders Captured": "الطلبات المستلمة",
    "Confirmed Sales": "المبيعات المؤكدة",
    "Captured Revenue": "الإيرادات المسجلة",
    "Products Seen": "المنتجات المرصودة",
    "Confirmed Orders": "الطلبات المؤكدة",
    "Units Sold": "الوحدات المباعة",
    "Products Sold": "المنتجات المباعة",
    "Top Product": "أفضل منتج",
    "Observed Status": "الحالة المرصودة",
    "Conversion Rate": "معدل التحويل",
    "Repeat Purchase": "تكرار الشراء",
    "Abandoned Carts": "السلات المتروكة",
    "Full Product Classification": "التصنيف الكامل للمنتجات",
    "Needs traffic/session source": "يحتاج مصدر الزيارات والجلسات",
    "Needs privacy-safe customer identity source": "يحتاج مصدر هوية عميل يحافظ على الخصوصية",
    "Needs Salla read integration": "يحتاج ربط قراءة من سلة",
    "Needs historical catalog/product observations": "يحتاج تاريخًا كافيًا لمراقبة الكتالوج والمنتجات",
    "Catalog-wide prices & stock": "أسعار ومخزون كامل الكتالوج",
    "From confirmed order snapshots": "من سجلات الطلبات المؤكدة",
    "From order items": "من بنود الطلبات",
    "Webhook Data Hub": "مركز البيانات عبر أحداث الويب",
    "Opportunity Dispatch": "إسناد الفرص",
    "Control Center": "مركز التحكم",
    "Company Agents": "مندوبي بكجات",
    "Opportunity Score": "تقييم الفرصة",
    "No sales": "لا توجد مبيعات",
    "Hot · captured": "رائج · مرصود",
    "Active · captured": "نشط · مرصود",
    "Local fallback": "بديل محلي",
    "Current mode: Local fallback": "الوضع الحالي: بديل محلي",
    "OAuth stored in Google DB": "تم حفظ التفويض في قاعدة بيانات جوجل",
    "Source control / deployment history": "إدارة المصدر وسجل النشر",
    "Production runtime": "بيئة التشغيل الإنتاجية",
    "Google VM Data Hub": "مركز البيانات على خادم جوجل",
    "Needs Integration": "يحتاج ربط",
    "Connected": "متصل",
    "Readable": "قابل للقراءة",
    "Writable": "قابل للكتابة",
    "Internal": "داخلي",
    "Commerce": "التجارة",
    "Acquisition": "الاستحواذ",
    "Technology": "التقنية",
    "Market": "السوق",
    "Products": "المنتجات",
    "Pricing": "التسعير",
    "Merchants": "التجار",
    "Growth": "النمو",
    "Revenue": "الإيرادات",
    "Orders": "الطلبات",
    "Pending": "قيد الانتظار",
    "AOV": "متوسط قيمة الطلب",
    "Units": "الوحدات",
    "Product": "المنتج",
    "SKU": "رمز المنتج",
    "Order": "الطلب",
    "Payment": "الدفع",
    "Total": "الإجمالي",
    "Items": "المنتجات",
    "Event": "الحدث",
    "Updated": "آخر تحديث",
    "Priority": "الأولوية",
    "Source": "المصدر",
    "Opportunity": "الفرصة",
    "Score": "التقييم",
    "Status": "الحالة",
    "Created": "تاريخ الإنشاء",
    "Department": "القسم",
    "Task": "المهمة",
    "Action": "الإجراء",
    "Detail": "التفاصيل",
    "Category": "الفئة",
    "ID": "الرقم",
    "Live": "مباشر",
    "Issued": "الصادرة",
    "Redeemed": "المستخدمة",
    "Expired": "المنتهية",
    "Integrations": "التكاملات",
    "Vouchers": "القسائم",
    "Voucher & CRM": "القسائم وإدارة العملاء",
    "Opportunities": "الفرص",
    "WhatsLoop": "واتس لووب",
    "Salla": "سلة",
    "Google Cloud": "سحابة جوجل",
    "Data Hub": "مركز البيانات",
    "Monitoring": "المراقبة",
    "CEO Dashboard": "لوحة المدير التنفيذي",
    "Pakgat AI Company": "شركة بكجات الذكية",
    "Pakgat": "بكجات",
}

_STATUS_TEXT = {
    "new": "جديدة",
    "review": "قيد المراجعة",
    "approved": "معتمدة",
    "active": "نشطة",
    "assigned": "مسندة",
    "contacted": "تم التواصل",
    "replied": "تم الرد",
    "negotiating": "قيد التفاوض",
    "won": "ناجحة",
    "lost": "غير ناجحة",
    "open": "مفتوحة",
    "pending": "قيد الانتظار",
    "sent": "تم الإرسال",
    "failed": "فشل",
}


def _localize_company_html(html: str) -> str:
    # Exact long phrases first so shorter tokens do not produce awkward wording.
    for source, target in sorted(_PHRASES.items(), key=lambda item: len(item[0]), reverse=True):
        html = html.replace(source, target)

    # Translate common machine status values only when rendered as table/select text;
    # this deliberately avoids touching CSS classes such as badge-active.
    for source, target in _STATUS_TEXT.items():
        html = html.replace(f">{source}<", f">{target}<")
        html = html.replace(f">{source} ·", f">{target} ·")

    html = html.replace(" received / ", " مستلم / ")
    html = html.replace(" rejected", " مرفوض")
    html = html.replace(" SAR", " ر.س")
    html = html.replace("KPIs", "مؤشرات الأداء")
    html = html.replace("SEO", "تحسين محركات البحث")
    html = html.replace("Blueprint", "المخطط المرجعي")
    html = html.replace("Webhooks", "أحداث الويب")
    html = html.replace("Webhook", "حدث الويب")
    html = html.replace("OAuth", "التفويض")
    html = html.replace("API", "واجهة برمجة التطبيقات")
    return html


# ---------------------------------------------------------------------------
# Final company HTML localization middleware.
# Other AI Company modules inject sections into /admin/company after page_shell
# returns, so middleware is intentionally last in main.py to translate the final
# assembled page, including Sales/Growth, Sources and Opportunity Dispatch.
# ---------------------------------------------------------------------------

@core.app.middleware("http")
async def arabic_company_ui(request: Request, call_next):
    response = await call_next(request)

    if not request.url.path.startswith("/admin/company"):
        return response

    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type.lower():
        return response

    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk)
    body = b"".join(chunks).decode("utf-8", errors="replace")
    body = _localize_company_html(body)

    headers = dict(response.headers)
    headers.pop("content-length", None)
    return Response(
        content=body,
        status_code=response.status_code,
        headers=headers,
        media_type="text/html",
        background=response.background,
    )
