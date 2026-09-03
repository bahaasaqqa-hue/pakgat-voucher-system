"""Salla business view for Pakgat AI Company Control Center."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.routing import APIRoute
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import application as core
from app import ai_company
from app.salla_data import SallaOrderItemSnapshot, latest_items, latest_orders, salla_metrics


def _admin_redirect(request: Request):
    try:
        core.require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)
    return None


def _money(value: float) -> str:
    return f"{float(value or 0):,.2f} SAR"


def _salla_summary_html(db: Session) -> str:
    metrics = salla_metrics(db)
    return f"""
      <section class='card' style='padding:22px;margin-bottom:18px'>
        <div style='display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap'>
          <div><h2 style='margin-bottom:4px'>Salla · Sales & Orders</h2>
          <p class='muted' style='margin-top:0'>بيانات تشغيلية محفوظة في Data Hub من Webhooks الموقعة التي تصل إلى Google.</p></div>
          <a class='btn btn-blue' href='/admin/company/salla'>فتح تفاصيل سلة</a>
        </div>
        <div class='grid grid-mobile-1' style='grid-template-columns:repeat(4,1fr);margin-top:14px'>
          <div style='background:#f8faff;border-radius:14px;padding:16px'><div class='muted'>Orders Captured</div><div style='font-size:26px;font-weight:900'>{metrics['orders_total']}</div></div>
          <div style='background:#f8faff;border-radius:14px;padding:16px'><div class='muted'>Confirmed Sales</div><div style='font-size:26px;font-weight:900'>{metrics['confirmed_orders']}</div></div>
          <div style='background:#f8faff;border-radius:14px;padding:16px'><div class='muted'>Captured Revenue</div><div style='font-size:26px;font-weight:900'>{_money(metrics['revenue'])}</div></div>
          <div style='background:#f8faff;border-radius:14px;padding:16px'><div class='muted'>Products Seen</div><div style='font-size:26px;font-weight:900'>{metrics['products']}</div></div>
        </div>
        <p class='muted' style='margin:14px 0 0'>Abandoned carts: غير مربوط بعد. سيتم تفعيله عند توفر قراءة Salla المناسبة بدون تغيير إعدادات التطبيق الحالية.</p>
      </section>
    """


@core.app.get("/admin/company/salla", response_class=HTMLResponse)
def company_salla_dashboard(request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect

    metrics = salla_metrics(db)
    orders = latest_orders(db, 25)
    items = latest_items(db, 35)

    order_rows = "".join(
        "<tr>"
        f"<td dir='ltr'>{core.esc(o.reference_id or o.order_id)}</td>"
        f"<td>{core.esc(o.order_status or '—')}</td>"
        f"<td>{core.esc(o.payment_status or '—')}</td>"
        f"<td dir='ltr'>{_money(o.total_amount)}</td>"
        f"<td>{core.esc(o.items_count)}</td>"
        f"<td dir='ltr'>{core.esc(o.last_event)}</td>"
        f"<td>{core.esc(core.fmt_dt(o.updated_at))}</td>"
        "</tr>"
        for o in orders
    ) or "<tr><td colspan='7' class='muted'>لا توجد طلبات محفوظة في Data Hub حتى الآن. ستظهر الطلبات الجديدة تلقائياً بعد وصول Webhooks إلى Google.</td></tr>"

    item_rows = "".join(
        "<tr>"
        f"<td>{core.esc(i.product_name)}</td>"
        f"<td dir='ltr'>{core.esc(i.sku or '—')}</td>"
        f"<td>{core.esc(i.quantity)}</td>"
        f"<td dir='ltr'>{_money(i.unit_price)}</td>"
        f"<td dir='ltr'>{_money(i.line_total)}</td>"
        "</tr>"
        for i in items
    ) or "<tr><td colspan='5' class='muted'>لا توجد بيانات منتجات من الطلبات حتى الآن.</td></tr>"

    top_products = list(
        db.execute(
            select(
                SallaOrderItemSnapshot.product_name,
                func.sum(SallaOrderItemSnapshot.quantity).label("units"),
                func.sum(SallaOrderItemSnapshot.line_total).label("value"),
            )
            .group_by(SallaOrderItemSnapshot.product_name)
            .order_by(func.sum(SallaOrderItemSnapshot.quantity).desc())
            .limit(10)
        ).all()
    )
    top_rows = "".join(
        f"<tr><td>{core.esc(name)}</td><td>{int(units or 0)}</td><td dir='ltr'>{_money(value or 0)}</td></tr>"
        for name, units, value in top_products
    ) or "<tr><td colspan='3' class='muted'>لا توجد بيانات بعد.</td></tr>"

    body = f"""
    <main class='wrap' style='padding:28px 0 48px'>
      <div style='display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap'>
        <div><h1 style='margin-bottom:4px'>Salla Data Hub</h1><p class='muted'>Pakgat AI Company · Google Cloud</p></div>
        <a class='btn btn-muted' href='/admin/company'>العودة إلى Control Center</a>
      </div>

      <div class='grid grid-mobile-1' style='grid-template-columns:repeat(5,1fr);margin:18px 0'>
        <section class='card' style='padding:18px'><div class='muted'>Orders</div><div style='font-size:30px;font-weight:900'>{metrics['orders_total']}</div></section>
        <section class='card' style='padding:18px'><div class='muted'>Confirmed</div><div style='font-size:30px;font-weight:900'>{metrics['confirmed_orders']}</div></section>
        <section class='card' style='padding:18px'><div class='muted'>Pending</div><div style='font-size:30px;font-weight:900'>{metrics['pending_orders']}</div></section>
        <section class='card' style='padding:18px'><div class='muted'>Revenue</div><div style='font-size:25px;font-weight:900'>{_money(metrics['revenue'])}</div></section>
        <section class='card' style='padding:18px'><div class='muted'>Units</div><div style='font-size:30px;font-weight:900'>{metrics['units']}</div></section>
      </div>

      <div class='alert alert-ok'><strong>Privacy:</strong> Data Hub يحفظ بيانات الأعمال فقط من أحداث الطلبات الموقعة، ولا يحفظ اسم العميل أو جواله أو بريده ولا يحتفظ بالـraw webhook payload.</div>
      <div class='alert' style='background:#fff7ed;color:#9a3412;border:1px solid #fed7aa'><strong>Historical coverage:</strong> الأرقام هنا تبدأ من الأحداث التي تصل إلى Google بعد تفعيل هذا الإصدار. لا يتم اختراع أو تقدير مبيعات قديمة غير موجودة في Data Hub.</div>

      <section class='card' style='padding:22px;margin-bottom:18px'>
        <h2>Latest Orders</h2>
        <div class='table-wrap'><table><thead><tr><th>Order</th><th>Status</th><th>Payment</th><th>Total</th><th>Items</th><th>Event</th><th>Updated</th></tr></thead><tbody>{order_rows}</tbody></table></div>
      </section>

      <div class='grid grid-mobile-1' style='grid-template-columns:1fr 1fr'>
        <section class='card' style='padding:22px'>
          <h2>Top Products Seen</h2>
          <div class='table-wrap'><table><thead><tr><th>Product</th><th>Units</th><th>Captured Value</th></tr></thead><tbody>{top_rows}</tbody></table></div>
        </section>
        <section class='card' style='padding:22px'>
          <h2>Latest Product Lines</h2>
          <div class='table-wrap'><table><thead><tr><th>Product</th><th>SKU</th><th>Qty</th><th>Unit Price</th><th>Line Total</th></tr></thead><tbody>{item_rows}</tbody></table></div>
        </section>
      </div>

      <section class='card' style='padding:22px;margin-top:18px'>
        <h2>Connection Coverage</h2>
        <table><tbody>
          <tr><th>Orders</th><td><span class='badge badge-active'>Webhook Data Hub</span></td></tr>
          <tr><th>Sales / Revenue</th><td><span class='badge badge-active'>From confirmed order snapshots</span></td></tr>
          <tr><th>Products / SKU / Qty</th><td><span class='badge badge-active'>From order items</span></td></tr>
          <tr><th>Catalog-wide prices & stock</th><td><span class='badge badge-expired'>ينتظر Salla read access</span></td></tr>
          <tr><th>Abandoned carts</th><td><span class='badge badge-expired'>ينتظر Salla read access</span></td></tr>
        </tbody></table>
      </section>
    </main>
    """
    return HTMLResponse(core.page_shell("Salla Data Hub", body, admin=True))


def _find_company_route():
    for route in core.app.routes:
        if isinstance(route, APIRoute) and route.path == "/admin/company" and "GET" in route.methods:
            return route
    return None


_company_route = _find_company_route()
if _company_route is not None:
    _original_company_dashboard = _company_route.dependant.call

    def _company_dashboard_with_salla(
        request: Request,
        db: Session = Depends(core.get_db),
    ):
        response = _original_company_dashboard(request, db)
        if not isinstance(response, HTMLResponse):
            return response
        html = response.body.decode("utf-8", errors="replace")
        section = _salla_summary_html(db)
        marker = "<section class='card' style='padding:22px;margin-bottom:18px'>\n        <h2>Critical Alerts</h2>"
        if marker in html:
            html = html.replace(marker, section + marker, 1)
        else:
            html = html.replace("</main>", section + "</main>", 1)
        response.body = html.encode("utf-8")
        response.headers["content-length"] = str(len(response.body))
        return response

    _company_route.endpoint = _company_dashboard_with_salla
    _company_route.dependant.call = _company_dashboard_with_salla
