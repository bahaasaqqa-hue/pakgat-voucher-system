"""Competitor/source watchlist for Pakgat AI Company.

The watchlist separates direct coupon/deal competitors from product-demand
signals such as Noon and Amazon.  It does not claim server-side scraping is live;
the Google Data Hub integration remains a later step.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from app import application as core
from app import ai_company_sources


WATCHLIST = [
    {
        "name": "كوبون (Cobone)",
        "url": "https://www.cobone.com/ar/deals/riyadh",
        "type": "منافس مباشر",
        "focus": "أي عرض أو كوبون جديد، التاجر، السعر قبل/بعد، نسبة الخصم، المبيعات ووسم الأفضل مبيعًا إن ظهر.",
    },
    {
        "name": "وفرها — السعودية",
        "url": "https://waffarha.com/ar?country=ksa",
        "type": "منافس مباشر",
        "focus": "أي كوبون أو عرض أو تاجر جديد في السعودية وتغيّر الأسعار أو مدة الصلاحية.",
    },
    {
        "name": "فوز FOZ",
        "url": "https://foz.sa/",
        "type": "منافس مباشر",
        "focus": "عروض وكوبونات ومزادات وعلامات تجارية أو شركاء جدد، مع متابعة ما يعلنونه للشركات.",
    },
    {
        "name": "CashUp",
        "url": "https://cashup.io/",
        "type": "منافس مباشر",
        "focus": "متاجر شريكة وقسائم ومزايا جديدة وتغيّر نسبة القيمة الإضافية أو شبكة الاستخدام.",
    },
    {
        "name": "سيفور Cefour",
        "url": "https://play.google.com/store/apps/details?id=com.cefour.cefour&hl=ar",
        "type": "منافس مباشر",
        "focus": "عروض وكوبونات ومتاجر أو مزايا جديدة تظهر في الويب/فهرسة التطبيق والمصادر العامة.",
    },
    {
        "name": "SDC App السعودية",
        "url": "https://sdcappsa.com/ar",
        "type": "منافس مباشر / شركات",
        "focus": "علامات تجارية وعروض وشركاء جدد وبرامج الشركات والمزايا التي تدخل الشبكة.",
    },
    {
        "name": "نون السعودية",
        "url": "https://www.noon.com/saudi-ar/",
        "type": "إشارة طلب ومنتجات",
        "focus": "Best Seller، ترتيب الفئة، المبيعات الحديثة، كوبون/Deal/خصم، مع رابط المنتج المباشر.",
    },
    {
        "name": "أمازون السعودية",
        "url": "https://www.amazon.sa/",
        "type": "إشارة طلب ومنتجات",
        "focus": "Best Seller، عدد المشترين، Limited Time Deal/Coupon، مع رابط المنتج أو رابط بحث واضح عند تعذر الرابط المباشر.",
    },
]


# Add missing competitor sources to the central source inventory. They remain
# Needs Integration until the Data Hub has a real reader; this is intentionally
# conservative and avoids claiming a connection that does not exist on GCE.
for source_name in ("FOZ", "CashUp", "Cefour", "SDC App Saudi"):
    if not any(row[0] == source_name for row in ai_company_sources.SOURCE_DEFS):
        ai_company_sources.SOURCE_DEFS.append((source_name, "Market", "Needs Integration"))


def _admin_redirect(request: Request):
    try:
        core.require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)
    return None


@core.app.get("/admin/company/competitors", response_class=HTMLResponse)
def competitor_watchlist(request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect

    rows = "".join(
        "<tr>"
        f"<td><strong>{core.esc(item['name'])}</strong></td>"
        f"<td>{core.esc(item['type'])}</td>"
        f"<td>{core.esc(item['focus'])}</td>"
        f"<td><a class='btn btn-muted' target='_blank' rel='noopener' href='{core.esc(item['url'])}'>فتح المصدر</a></td>"
        "</tr>"
        for item in WATCHLIST
    )

    body = f"""
    <main class='wrap' style='padding:28px 0 48px'>
      <div style='display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap'>
        <div><h1 style='margin-bottom:4px'>رادار المنافسين والمنتجات</h1>
        <p class='muted' style='margin:0'>المنافسون المباشرون + مصادر المنتجات المطلوبة في السعودية.</p></div>
        <a class='btn btn-muted' href='/admin/company'>مركز التحكم</a>
      </div>
      <div class='alert' style='background:#fff7ed;color:#9a3412;border:1px solid #fed7aa;margin-top:18px'>
        <strong>حالة الربط:</strong> هذه هي قائمة المصادر المعتمدة للرصد. إشعارات الرصد الدورية تعمل خارج Data Hub حالياً؛ إدخال النتائج تلقائياً في قاعدة Google سيكون مرحلة الربط التالية، لذلك لا نعرضها كـ Connected داخل Source Inventory قبل تنفيذ هذا الربط فعلياً.
      </div>
      <section class='card' style='padding:22px;margin-top:18px'>
        <div class='table-wrap'><table><thead><tr><th>المصدر</th><th>الدور</th><th>ما الذي نراقبه</th><th>الرابط</th></tr></thead><tbody>{rows}</tbody></table></div>
      </section>
    </main>
    """
    return HTMLResponse(core.page_shell("رادار المنافسين والمنتجات", body, admin=True))


def _find_company_route():
    for route in core.app.routes:
        if isinstance(route, APIRoute) and route.path == "/admin/company" and "GET" in route.methods:
            return route
    return None


_company_route = _find_company_route()
if _company_route is not None:
    _original_dashboard = _company_route.dependant.call

    def _dashboard_with_watchlist(request: Request, db: Session = Depends(core.get_db)):
        response = _original_dashboard(request, db)
        if not isinstance(response, HTMLResponse):
            return response
        section = """
        <section class='card' style='padding:22px;margin-bottom:18px'>
          <div style='display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap'>
            <div><h2 style='margin-bottom:4px'>رادار المنافسين والمنتجات</h2>
            <p class='muted' style='margin:0'>كوبون · وفرها · فوز · CashUp · سيفور · SDC · نون · أمازون</p></div>
            <a class='btn btn-blue' href='/admin/company/competitors'>فتح قائمة الرصد</a>
          </div>
        </section>
        """
        html = response.body.decode("utf-8", errors="replace")
        html = html.replace("</main>", section + "</main>", 1)
        response.body = html.encode("utf-8")
        response.headers["content-length"] = str(len(response.body))
        return response

    _company_route.endpoint = _dashboard_with_watchlist
    _company_route.dependant.call = _dashboard_with_watchlist
