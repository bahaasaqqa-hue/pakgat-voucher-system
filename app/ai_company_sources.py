"""Source inventory for Pakgat AI Company.

Tracks whether each Blueprint source is Connected, Readable, Writable or Needs Integration.
The inventory is factual: it reflects only integrations actually available to the Google runtime.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.routing import APIRoute
from sqlalchemy import DateTime, Integer, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app import application as core
from app import ai_company
from app.ai_company_readiness import salla_source_access


class CompanySourceStatus(core.Base):
    __tablename__ = "company_source_status"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    category: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    detail: Mapped[str] = mapped_column(String(500), default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


SOURCE_DEFS = [
    ("Voucher System", "Internal", "Connected"),
    ("WhatsLoop", "Internal", "Connected"),
    ("Salla Webhooks", "Commerce", "Connected"),
    ("Salla OAuth / Merchant API", "Commerce", "Needs Integration"),
    ("Salla Products / Inventory", "Commerce", "Needs Integration"),
    ("Salla Abandoned Carts", "Commerce", "Needs Integration"),
    ("Salla Reviews", "Commerce", "Needs Integration"),
    ("Google Analytics", "Acquisition", "Needs Integration"),
    ("Google Search Console", "Acquisition", "Needs Integration"),
    ("GitHub", "Technology", "Readable"),
    ("Google Compute Engine", "Technology", "Connected"),
    ("PostgreSQL", "Technology", "Connected"),
    ("Amazon.sa", "Market", "Needs Integration"),
    ("Noon Saudi", "Market", "Needs Integration"),
    ("Cobone", "Market", "Needs Integration"),
    ("Waffarha", "Market", "Needs Integration"),
    ("Google Trends / Web", "Market", "Needs Integration"),
]


def refresh_source_inventory(db: Session) -> None:
    oauth_row = db.scalar(
        select(core.SallaOAuthCredential)
        .order_by(core.SallaOAuthCredential.updated_at.desc())
        .limit(1)
    )
    oauth_connected = bool(oauth_row)
    oauth_scope = str(oauth_row.scope or "") if oauth_row else ""
    now = datetime.now(timezone.utc)

    for source, category, default_status in SOURCE_DEFS:
        status = default_status
        detail = ""
        if source == "WhatsLoop":
            status = "Connected" if core.WHATSLOOP_API_BASE_URL and core.WHATSLOOP_API_TOKEN else "Needs Integration"
        elif source == "Salla Webhooks":
            status = "Connected" if core.SALLA_WEBHOOK_SECRET else "Needs Integration"
        elif source == "Salla OAuth / Merchant API":
            status = "Connected" if oauth_connected else "Needs Integration"
            if oauth_connected:
                detail = "OAuth stored in Google DB; scope captured" if oauth_scope else "OAuth stored in Google DB; scope missing"
            else:
                detail = "Current mode: Local fallback"
        elif source in {"Salla Products / Inventory", "Salla Abandoned Carts", "Salla Reviews"}:
            status, detail = salla_source_access(source, oauth_connected, oauth_scope)
        elif source == "Google Analytics":
            from app.google_analytics import google_analytics_connection_state

            status, detail = google_analytics_connection_state(db)
        elif source == "Google Search Console":
            from app.google_search_console import connection_state

            status, detail = connection_state(db)
        elif source == "GitHub":
            detail = "Source control / deployment history"
        elif source == "Google Compute Engine":
            detail = "Production runtime"
        elif source == "PostgreSQL":
            detail = "Google VM Data Hub"

        row = db.scalar(select(CompanySourceStatus).where(CompanySourceStatus.source == source))
        if row is None:
            row = CompanySourceStatus(source=source, category=category, status=status, detail=detail, updated_at=now)
            db.add(row)
        else:
            row.category = category
            row.status = status
            row.detail = detail
            row.updated_at = now
    db.commit()


def _admin_redirect(request: Request):
    try:
        core.require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)
    return None


def _badge(status: str) -> str:
    if status == "Connected":
        cls = "badge-active"
    elif status in {"Readable", "Writable"}:
        cls = "badge-active"
    else:
        cls = "badge-expired"
    return f"<span class='badge {cls}'>{core.esc(status)}</span>"


def source_summary(db: Session) -> dict:
    refresh_source_inventory(db)
    rows = list(db.scalars(select(CompanySourceStatus).order_by(CompanySourceStatus.category, CompanySourceStatus.source)).all())
    counts = {"Connected": 0, "Readable": 0, "Writable": 0, "Needs Integration": 0}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    return {"rows": rows, "counts": counts}


@core.app.get("/admin/company/sources", response_class=HTMLResponse)
def company_sources(request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect
    summary = source_summary(db)
    rows_html = "".join(
        "<tr>"
        f"<td>{core.esc(r.source)}</td>"
        f"<td>{core.esc(r.category)}</td>"
        f"<td>{_badge(r.status)}</td>"
        f"<td>{core.esc(r.detail or '—')}</td>"
        f"<td>{core.esc(core.fmt_dt(r.updated_at))}</td>"
        "</tr>"
        for r in summary["rows"]
    )
    c = summary["counts"]
    body = f"""
    <main class='wrap' style='padding:28px 0 48px'>
      <div style='display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap'>
        <div><h1 style='margin-bottom:4px'>Source Inventory</h1><p class='muted'>Connected · Readable · Writable · Needs Integration</p></div>
        <a class='btn btn-muted' href='/admin/company'>العودة إلى Control Center</a>
      </div>
      <div class='grid grid-mobile-1' style='grid-template-columns:repeat(4,1fr);margin:18px 0'>
        <section class='card' style='padding:18px'><div class='muted'>Connected</div><div style='font-size:30px;font-weight:900'>{c.get('Connected',0)}</div></section>
        <section class='card' style='padding:18px'><div class='muted'>Readable</div><div style='font-size:30px;font-weight:900'>{c.get('Readable',0)}</div></section>
        <section class='card' style='padding:18px'><div class='muted'>Writable</div><div style='font-size:30px;font-weight:900'>{c.get('Writable',0)}</div></section>
        <section class='card' style='padding:18px'><div class='muted'>Needs Integration</div><div style='font-size:30px;font-weight:900'>{c.get('Needs Integration',0)}</div></section>
      </div>
      <section class='card' style='padding:22px'>
        <div class='table-wrap'><table><thead><tr><th>Source</th><th>Category</th><th>Status</th><th>Detail</th><th>Updated</th></tr></thead><tbody>{rows_html}</tbody></table></div>
      </section>
    </main>
    """
    return HTMLResponse(core.page_shell("Source Inventory", body, admin=True))


def _find_company_route():
    for route in core.app.routes:
        if isinstance(route, APIRoute) and route.path == "/admin/company" and "GET" in route.methods:
            return route
    return None


_company_route = _find_company_route()
if _company_route is not None:
    _original_dashboard = _company_route.dependant.call

    def _dashboard_with_sources(request: Request, db: Session = Depends(core.get_db)):
        response = _original_dashboard(request, db)
        if not isinstance(response, HTMLResponse):
            return response
        summary = source_summary(db)
        c = summary["counts"]
        section = f"""
        <section class='card' style='padding:22px;margin-bottom:18px'>
          <div style='display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap'>
            <div><h2 style='margin-bottom:4px'>Data Sources</h2><p class='muted' style='margin-top:0'>حالة مصادر الـBlueprint الفعلية، بدون افتراض أن المصدر مربوط لمجرد وجوده.</p></div>
            <a class='btn btn-blue' href='/admin/company/sources'>فتح Source Inventory</a>
          </div>
          <table><tbody>
            <tr><th>Connected</th><td>{c.get('Connected',0)}</td></tr>
            <tr><th>Readable</th><td>{c.get('Readable',0)}</td></tr>
            <tr><th>Needs Integration</th><td>{c.get('Needs Integration',0)}</td></tr>
          </tbody></table>
        </section>
        """
        html = response.body.decode("utf-8", errors="replace")
        marker = "<section class='card' style='padding:22px;margin-bottom:18px'>\n        <h2>Critical Alerts</h2>"
        if marker in html:
            html = html.replace(marker, section + marker, 1)
        else:
            html = html.replace("</main>", section + "</main>", 1)
        response.body = html.encode("utf-8")
        response.headers["content-length"] = str(len(response.body))
        return response

    _company_route.endpoint = _dashboard_with_sources
    _company_route.dependant.call = _dashboard_with_sources
