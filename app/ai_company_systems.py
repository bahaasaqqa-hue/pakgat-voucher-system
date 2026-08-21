"""Single systems hub for the 12 Pakgat AI Company departments.

Keeps the CEO dashboard compact: one small entry opens the full systems map.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.routing import APIRoute
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import application as core
from app import ai_company
from app.ai_company_governance import CompanyApproval
from app.ai_company_hunter import CompanyLead
from app.ai_company_store_ops import StoreOpsIssue


SYSTEMS = [
    ("01", "مركز القيادة والذكاء", "تشغيل", "/admin/company/brief", "لوحة القيادة + ملخص المدير التنفيذي + القرارات والموافقات."),
    ("02", "مركز البيانات وذكاء الأعمال", "تشغيل جزئي", "/admin/company/sources", "PostgreSQL + Data Hub + مصادر وحالة الربط؛ ما زالت بعض المصادر الخارجية غير مربوطة."),
    ("03", "ذكاء السوق والمنافسين", "تشغيل جزئي", "/admin/company/competitors", "رادار المنافسين والمصادر المعتمدة؛ الإدخال الآلي الكامل للويب إلى Data Hub ما زال قيد الربط."),
    ("04", "ذكاء المنتجات والتسعير", "تشغيل جزئي", "/admin/company/growth", "أداء المنتجات من المبيعات الملتقطة؛ تصنيف السوق والهامش الكامل يحتاج مصادر أسعار أوسع."),
    ("05", "باحث التجار والموردين", "تشغيل", "/admin/company/hunter", "Merchant Hunter + Supplier Hunter + Pipeline + موافقة قبل التواصل."),
    ("06", "النمو والتجاري", "تشغيل جزئي", "/admin/company/growth", "Revenue / Orders / AOV متاحة؛ Conversion/Retention/Cart Recovery تنتظر مصادرها."),
    ("07", "تشغيل المتجر وجودة العرض", "تشغيل جزئي", "/admin/company/store-ops", "يفحص البيانات المتصلة؛ فحص الكتالوج الكامل ينتظر قراءة سلة."),
    ("08", "SEO / Google / GEO", "بانتظار الربط", "/admin/company/sources", "Search Console وAnalytics غير مربوطين بعد."),
    ("09", "الهوية والاستوديو الإبداعي", "بانتظار التنفيذ", "#", "نظام توليد ومراجعة الصور والبنرات والهوية لم يُربط داخل AI Company بعد."),
    ("10", "السوشيال وتوليد الطلب", "بانتظار التنفيذ", "#", "اختيار العروض وصناعة المحتوى وربط الأداء بالمبيعات لم يُبنَ بعد."),
    ("11", "CRM والقسائم ودورة العميل", "تشغيل جزئي", "/admin/company/salla", "Voucher/QR/WhatsApp موجود؛ Retention وRepeat Customer ما زالا ناقصين."),
    ("12", "التقنية والموثوقية والأمان", "تشغيل جزئي", "/admin/company", "Google VM + Health Monitoring موجودان؛ النسخ الاحتياطي والأمان المتقدم يجري استكمالهما."),
]


def _admin_redirect(request: Request):
    try:
        core.require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)
    return None


def _find_company_route():
    for route in core.app.routes:
        if isinstance(route, APIRoute) and route.path == "/admin/company" and "GET" in route.methods:
            return route
    return None


@core.app.get("/admin/company/systems", response_class=HTMLResponse)
def systems_page(request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect
    pending_approvals = int(db.scalar(select(func.count(CompanyApproval.id)).where(CompanyApproval.status == "pending")) or 0)
    open_leads = int(db.scalar(select(func.count(CompanyLead.id)).where(CompanyLead.status.notin_(["live", "rejected"]))) or 0)
    store_issues = int(db.scalar(select(func.count(StoreOpsIssue.id)).where(StoreOpsIssue.status == "open")) or 0)
    new_opportunities = int(db.scalar(select(func.count(ai_company.CompanyOpportunity.id)).where(ai_company.CompanyOpportunity.status == "new")) or 0)
    cards = "".join(
        f"""
        <article class='card' style='padding:20px'>
          <div style='display:flex;justify-content:space-between;gap:8px'><span class='badge badge-active'>{core.esc(num)}</span><strong>{core.esc(status)}</strong></div>
          <h2 style='font-size:20px;margin:12px 0 7px'>{core.esc(name)}</h2>
          <p class='muted' style='line-height:1.7;min-height:58px'>{core.esc(detail)}</p>
          {f"<a class='btn btn-blue' href='{url}'>فتح النظام</a>" if url != '#' else "<span class='badge badge-expired'>غير مفعّل بعد</span>"}
        </article>"""
        for num, name, status, url, detail in SYSTEMS
    )
    body = f"""
    <main class='wrap' style='padding:28px 0 48px'>
      <div style='display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap'><div><h1 style='margin-bottom:4px'>أنظمة شركة بكجات الذكية</h1><p class='muted'>الخريطة التشغيلية للـ12 قسمًا — صفحة واحدة بدل تكديس الـDashboard.</p></div><a class='btn btn-muted' href='/admin/company'>مركز التحكم</a></div>
      <div class='grid grid-mobile-1' style='grid-template-columns:repeat(4,1fr);margin:18px 0'>
        <section class='card' style='padding:16px'><div class='muted'>فرص جديدة</div><strong style='font-size:28px'>{new_opportunities}</strong></section>
        <section class='card' style='padding:16px'><div class='muted'>موافقات</div><strong style='font-size:28px'>{pending_approvals}</strong></section>
        <section class='card' style='padding:16px'><div class='muted'>Leads مفتوحة</div><strong style='font-size:28px'>{open_leads}</strong></section>
        <section class='card' style='padding:16px'><div class='muted'>مشاكل المتجر</div><strong style='font-size:28px'>{store_issues}</strong></section>
      </div>
      <div class='grid grid-mobile-1' style='grid-template-columns:repeat(3,1fr)'>{cards}</div>
    </main>"""
    return HTMLResponse(core.page_shell("أنظمة شركة بكجات الذكية", body, admin=True))


_company_route = _find_company_route()
if _company_route is not None:
    _original_dashboard = _company_route.dependant.call

    def _dashboard_with_systems(request: Request, db: Session = Depends(core.get_db)):
        response = _original_dashboard(request, db)
        if not isinstance(response, HTMLResponse):
            return response
        pending = int(db.scalar(select(func.count(CompanyApproval.id)).where(CompanyApproval.status == "pending")) or 0)
        section = f"""
        <section class='card' style='padding:18px;margin-bottom:18px'>
          <div style='display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap'>
            <div><strong style='font-size:20px'>أنظمة شركة بكجات الذكية</strong><div class='muted'>12 قسمًا · مركز واحد للتشغيل</div></div>
            <div style='display:flex;gap:8px;align-items:center'><span class='badge badge-active'>{pending} موافقات</span><a class='btn btn-blue' href='/admin/company/systems'>فتح الأنظمة</a></div>
          </div>
        </section>"""
        html = response.body.decode("utf-8", errors="replace")
        html = html.replace("</main>", section + "</main>", 1)
        response.body = html.encode("utf-8")
        response.headers["content-length"] = str(len(response.body))
        return response

    _company_route.endpoint = _dashboard_with_systems
    _company_route.dependant.call = _dashboard_with_systems
