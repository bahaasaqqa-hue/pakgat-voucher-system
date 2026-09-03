"""Sales, Growth and Product Intelligence views for Pakgat AI Company.

Metrics are derived only from signed Salla order snapshots already captured in the
Google Data Hub. Metrics that require wider Salla/Analytics access are shown as
pending rather than estimated.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.routing import APIRoute
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app import application as core
from app.salla_data import SallaOrderItemSnapshot, SallaOrderSnapshot, salla_metrics


PAID_STATUSES = ["paid", "completed", "success", "successful", "تم الدفع", "مدفوع"]
FINAL_STATUSES = ["closed", "completed", "fulfilled", "مكتمل", "مغلق", "تم التنفيذ"]


def _admin_redirect(request: Request):
    try:
        core.require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)
    return None


def _confirmed_condition():
    return or_(
        SallaOrderSnapshot.payment_status.in_(PAID_STATUSES),
        SallaOrderSnapshot.order_status.in_(FINAL_STATUSES),
        (SallaOrderSnapshot.total_amount > 0)
        & (SallaOrderSnapshot.paid_amount >= SallaOrderSnapshot.total_amount),
    )


def _money(value: float) -> str:
    return f"{float(value or 0):,.2f} SAR"


def growth_metrics(db: Session) -> dict:
    base = salla_metrics(db)
    confirmed = int(base.get("confirmed_orders") or 0)
    revenue = float(base.get("revenue") or 0)
    aov = revenue / confirmed if confirmed else 0.0

    confirmed_units = int(
        db.scalar(
            select(func.coalesce(func.sum(SallaOrderItemSnapshot.quantity), 0))
            .join(
                SallaOrderSnapshot,
                SallaOrderSnapshot.order_id == SallaOrderItemSnapshot.order_id,
            )
            .where(_confirmed_condition())
        )
        or 0
    )

    products_sold = int(
        db.scalar(
            select(func.count(func.distinct(SallaOrderItemSnapshot.product_id)))
            .join(
                SallaOrderSnapshot,
                SallaOrderSnapshot.order_id == SallaOrderItemSnapshot.order_id,
            )
            .where(
                _confirmed_condition(),
                SallaOrderItemSnapshot.product_id.is_not(None),
            )
        )
        or 0
    )

    return {
        **base,
        "aov": round(aov, 2),
        "confirmed_units": confirmed_units,
        "products_sold": products_sold,
    }


def product_performance(db: Session, limit: int = 20):
    rows = list(
        db.execute(
            select(
                SallaOrderItemSnapshot.product_id,
                SallaOrderItemSnapshot.product_name,
                SallaOrderItemSnapshot.sku,
                func.count(func.distinct(SallaOrderItemSnapshot.order_id)).label("orders"),
                func.sum(SallaOrderItemSnapshot.quantity).label("units"),
                func.sum(SallaOrderItemSnapshot.line_total).label("revenue"),
                func.max(SallaOrderItemSnapshot.updated_at).label("last_seen"),
            )
            .join(
                SallaOrderSnapshot,
                SallaOrderSnapshot.order_id == SallaOrderItemSnapshot.order_id,
            )
            .where(_confirmed_condition())
            .group_by(
                SallaOrderItemSnapshot.product_id,
                SallaOrderItemSnapshot.product_name,
                SallaOrderItemSnapshot.sku,
            )
            .order_by(
                func.sum(SallaOrderItemSnapshot.quantity).desc(),
                func.sum(SallaOrderItemSnapshot.line_total).desc(),
            )
            .limit(limit)
        ).all()
    )
    return rows


def _observed_class(rank: int, count: int, units: int) -> tuple[str, str]:
    """Conservative classification based only on captured confirmed sales.

    We intentionally do not label Growing/Dormant/Old yet because those require
    historical catalog-wide observations. This avoids inventing intelligence.
    """
    if count <= 0 or units <= 0:
        return "No sales", "badge-expired"
    if count >= 3 and rank <= max(1, round(count * 0.25)):
        return "Hot · captured", "badge-active"
    return "Active · captured", "badge-active"


def _summary_html(db: Session) -> str:
    m = growth_metrics(db)
    products = product_performance(db, 5)
    product_rows = []
    total_products = len(product_performance(db, 100))
    for rank, row in enumerate(products, start=1):
        product_id, name, sku, orders, units, revenue, last_seen = row
        label, cls = _observed_class(rank, total_products, int(units or 0))
        product_rows.append(
            "<tr>"
            f"<td>{core.esc(name)}</td>"
            f"<td>{int(units or 0)}</td>"
            f"<td dir='ltr'>{_money(revenue or 0)}</td>"
            f"<td><span class='badge {cls}'>{core.esc(label)}</span></td>"
            "</tr>"
        )
    rows_html = "".join(product_rows) or "<tr><td colspan='4' class='muted'>لا توجد مبيعات مؤكدة محفوظة بعد.</td></tr>"

    return f"""
      <section class='card' style='padding:22px;margin-bottom:18px'>
        <div style='display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap'>
          <div><h2 style='margin-bottom:4px'>Sales & Growth</h2>
          <p class='muted' style='margin-top:0'>KPIs من مبيعات سلة المؤكدة التي وصلت إلى Google Data Hub.</p></div>
          <a class='btn btn-blue' href='/admin/company/growth'>فتح Growth & Products</a>
        </div>
        <div class='grid grid-mobile-1' style='grid-template-columns:repeat(5,1fr);margin-top:14px'>
          <div style='background:#f8faff;border-radius:14px;padding:16px'><div class='muted'>Revenue</div><div style='font-size:23px;font-weight:900'>{_money(m['revenue'])}</div></div>
          <div style='background:#f8faff;border-radius:14px;padding:16px'><div class='muted'>Orders</div><div style='font-size:28px;font-weight:900'>{m['confirmed_orders']}</div></div>
          <div style='background:#f8faff;border-radius:14px;padding:16px'><div class='muted'>AOV</div><div style='font-size:23px;font-weight:900'>{_money(m['aov'])}</div></div>
          <div style='background:#f8faff;border-radius:14px;padding:16px'><div class='muted'>Units Sold</div><div style='font-size:28px;font-weight:900'>{m['confirmed_units']}</div></div>
          <div style='background:#f8faff;border-radius:14px;padding:16px'><div class='muted'>Products Sold</div><div style='font-size:28px;font-weight:900'>{m['products_sold']}</div></div>
        </div>
        <div class='table-wrap' style='margin-top:16px'><table><thead><tr><th>Top Product</th><th>Units</th><th>Revenue</th><th>Observed Status</th></tr></thead><tbody>{rows_html}</tbody></table></div>
        <p class='muted' style='margin:12px 0 0'>Conversion, Repeat Purchase وAbandoned Carts تبقى Pending حتى يتوفر مصدر قراءة مناسب؛ لا يتم تقديرها أو اختراعها.</p>
      </section>
    """


@core.app.get("/admin/company/growth", response_class=HTMLResponse)
def growth_dashboard(request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect

    m = growth_metrics(db)
    rows = product_performance(db, 50)
    count = len(rows)
    product_html = []
    for rank, row in enumerate(rows, start=1):
        product_id, name, sku, orders, units, revenue, last_seen = row
        label, cls = _observed_class(rank, count, int(units or 0))
        product_html.append(
            "<tr>"
            f"<td>{rank}</td>"
            f"<td>{core.esc(name)}</td>"
            f"<td dir='ltr'>{core.esc(sku or '—')}</td>"
            f"<td>{int(orders or 0)}</td>"
            f"<td>{int(units or 0)}</td>"
            f"<td dir='ltr'>{_money(revenue or 0)}</td>"
            f"<td><span class='badge {cls}'>{core.esc(label)}</span></td>"
            f"<td>{core.esc(core.fmt_dt(last_seen))}</td>"
            "</tr>"
        )
    rows_html = "".join(product_html) or "<tr><td colspan='8' class='muted'>لا توجد مبيعات مؤكدة محفوظة بعد.</td></tr>"

    body = f"""
    <main class='wrap' style='padding:28px 0 48px'>
      <div style='display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap'>
        <div><h1 style='margin-bottom:4px'>Growth & Product Intelligence</h1>
        <p class='muted'>Pakgat AI Company · Salla signed data · Google Data Hub</p></div>
        <a class='btn btn-muted' href='/admin/company'>العودة إلى Control Center</a>
      </div>

      <div class='grid grid-mobile-1' style='grid-template-columns:repeat(6,1fr);margin:18px 0'>
        <section class='card' style='padding:18px'><div class='muted'>Revenue</div><div style='font-size:22px;font-weight:900'>{_money(m['revenue'])}</div></section>
        <section class='card' style='padding:18px'><div class='muted'>Confirmed Orders</div><div style='font-size:28px;font-weight:900'>{m['confirmed_orders']}</div></section>
        <section class='card' style='padding:18px'><div class='muted'>AOV</div><div style='font-size:22px;font-weight:900'>{_money(m['aov'])}</div></section>
        <section class='card' style='padding:18px'><div class='muted'>Pending</div><div style='font-size:28px;font-weight:900'>{m['pending_orders']}</div></section>
        <section class='card' style='padding:18px'><div class='muted'>Units Sold</div><div style='font-size:28px;font-weight:900'>{m['confirmed_units']}</div></section>
        <section class='card' style='padding:18px'><div class='muted'>Products Sold</div><div style='font-size:28px;font-weight:900'>{m['products_sold']}</div></section>
      </div>

      <div class='alert alert-ok'><strong>مفعّل الآن:</strong> Revenue، Orders، AOV، confirmed units، product sales ranking — من البيانات الفعلية الملتقطة فقط.</div>
      <div class='alert' style='background:#fff7ed;color:#9a3412;border:1px solid #fed7aa'><strong>لا يزال يحتاج ربط:</strong> Conversion Rate، Repeat Purchase، Abandoned Carts، Sell-through، Time-to-first-sale، Growing/Slow/Dormant/Old، Price Competitiveness. هذه المؤشرات لن تظهر كأرقام مصطنعة.</div>

      <section class='card' style='padding:22px;margin-bottom:18px'>
        <h2>Product Performance — Confirmed Sales</h2>
        <div class='table-wrap'><table><thead><tr><th>#</th><th>Product</th><th>SKU</th><th>Orders</th><th>Units</th><th>Revenue</th><th>Status</th><th>Last Seen</th></tr></thead><tbody>{rows_html}</tbody></table></div>
      </section>

      <section class='card' style='padding:22px'>
        <h2>Blueprint KPI Coverage</h2>
        <table><tbody>
          <tr><th>Revenue</th><td><span class='badge badge-active'>Live</span></td></tr>
          <tr><th>Orders</th><td><span class='badge badge-active'>Live</span></td></tr>
          <tr><th>AOV</th><td><span class='badge badge-active'>Live</span></td></tr>
          <tr><th>Conversion Rate</th><td><span class='badge badge-expired'>Needs traffic/session source</span></td></tr>
          <tr><th>Repeat Purchase</th><td><span class='badge badge-expired'>Needs privacy-safe customer identity source</span></td></tr>
          <tr><th>Abandoned Carts</th><td><span class='badge badge-expired'>Needs Salla read integration</span></td></tr>
          <tr><th>Full Product Classification</th><td><span class='badge badge-expired'>Needs historical catalog/product observations</span></td></tr>
        </tbody></table>
      </section>
    </main>
    """
    return HTMLResponse(core.page_shell("Growth & Product Intelligence", body, admin=True))


def _find_company_route():
    for route in core.app.routes:
        if isinstance(route, APIRoute) and route.path == "/admin/company" and "GET" in route.methods:
            return route
    return None


_company_route = _find_company_route()
if _company_route is not None:
    _original_company_dashboard = _company_route.dependant.call

    def _company_dashboard_with_growth(
        request: Request,
        db: Session = Depends(core.get_db),
    ):
        response = _original_company_dashboard(request, db)
        if not isinstance(response, HTMLResponse):
            return response
        html = response.body.decode("utf-8", errors="replace")
        section = _summary_html(db)
        marker = "<section class='card' style='padding:22px;margin-bottom:18px'>\n        <h2>Critical Alerts</h2>"
        if marker in html:
            html = html.replace(marker, section + marker, 1)
        else:
            html = html.replace("</main>", section + "</main>", 1)
        response.body = html.encode("utf-8")
        response.headers["content-length"] = str(len(response.body))
        return response

    _company_route.endpoint = _company_dashboard_with_growth
    _company_route.dependant.call = _company_dashboard_with_growth
