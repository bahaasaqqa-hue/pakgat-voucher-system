"""Compact opportunity UX for the Pakgat AI Company Control Center.

Dashboard rule: opportunities do not render as cards/tables on the CEO dashboard.
The existing KPI tile becomes one clickable "latest opportunities" tile with a
new-opportunity indicator. All opportunity details, assignment, execution stages
and archive live on the dedicated secondary page.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.routing import APIRoute
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import ai_company
from app import application as core
from app.ai_company_dispatch import CompanyAgent
from app.ai_company_radar_focus import sync_focused_feed


NEW_STATUSES = ["new"]
EXECUTION_STATUSES = ["review", "approved", "active", "assigned", "contacted", "replied", "negotiating"]
ARCHIVE_STATUSES = ["won", "lost", "archived"]

STATUS_AR = {
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
    "archived": "مؤرشفة",
}


def _admin_redirect(request: Request):
    try:
        core.require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)
    return None


def _find_route(path: str, method: str = "GET"):
    for route in core.app.routes:
        if isinstance(route, APIRoute) and route.path == path and method in route.methods:
            return route
    return None


def _source_badge(source: str) -> str:
    label = source
    if source.startswith("كوبون"):
        label = "كوبون"
    elif source.startswith("نون"):
        label = "نون"
    elif source.startswith("أمازون"):
        label = "أمازون"
    return f"<span class='badge badge-active'>{core.esc(label)}</span>"


def _new_count(db: Session) -> int:
    sync_focused_feed(db)
    return int(
        db.scalar(
            select(func.count(ai_company.CompanyOpportunity.id)).where(
                ai_company.CompanyOpportunity.status == "new"
            )
        )
        or 0
    )


def _remove_section_containing(html: str, marker: str) -> str:
    """Remove only the single <section> that contains marker.

    This avoids the broad regex that previously swallowed unrelated dashboard
    sections below the opportunities area.
    """
    marker_pos = html.find(marker)
    if marker_pos < 0:
        return html
    start = html.rfind("<section", 0, marker_pos)
    if start < 0:
        return html
    end = html.find("</section>", marker_pos)
    if end < 0:
        return html
    end += len("</section>")
    return html[:start] + html[end:]


def _replace_opportunity_kpi(html: str, new_count: int) -> str:
    """Turn the existing Opportunities KPI into the only dashboard entry point."""
    badge = (
        f"<span style='position:absolute;top:12px;left:12px;background:#dc2626;color:#fff;"
        f"border-radius:999px;padding:4px 9px;font-size:12px;font-weight:900'>{new_count} جديدة</span>"
        if new_count
        else "<span style='position:absolute;top:12px;left:12px;background:#e8eefc;color:#64748b;border-radius:999px;padding:4px 9px;font-size:12px;font-weight:900'>لا جديد</span>"
    )
    tile = (
        "<a href='/admin/company/opportunities' class='card' "
        "style='padding:20px;display:block;position:relative;min-height:140px'>"
        f"{badge}"
        "<div class='muted' style='margin-top:6px'>أحدث الفرص</div>"
        f"<div style='font-size:34px;font-weight:900;margin-top:12px'>{new_count}</div>"
        "<div class='muted' style='font-size:13px;margin-top:4px'>اضغط لعرض الفرص والإسناد</div>"
        "</a>"
    )

    pattern = re.compile(
        r"<section class='card' style='padding:20px'>"
        r"<div class='muted'>Opportunities</div>"
        r"<div style='font-size:34px;font-weight:900'>.*?</div>"
        r"</section>",
        re.DOTALL,
    )
    html, replaced = pattern.subn(tile, html, count=1)
    if replaced:
        return html

    pattern_ar = re.compile(
        r"<section class='card' style='padding:20px'>"
        r"<div class='muted'>الفرص</div>"
        r"<div style='font-size:34px;font-weight:900'>.*?</div>"
        r"</section>",
        re.DOTALL,
    )
    return pattern_ar.sub(tile, html, count=1)


def _compact_dashboard_html(html: str, db: Session) -> str:
    count = _new_count(db)
    html = _replace_opportunity_kpi(html, count)
    html = _remove_section_containing(html, "الفرص الجديدة لـ Pakgat")
    html = _remove_section_containing(html, "Opportunity Dispatch · المندوبون")
    html = _remove_section_containing(html, "إسناد الفرص · المندوبون")
    return html


def _opportunity_rows(rows, allow_assign: bool, archive_button: bool = True) -> str:
    rendered = []
    for o in rows:
        action = ""
        if allow_assign:
            action += f"<a class='btn btn-blue' href='/admin/company/opportunities/{o.id}/assign'>إسناد</a> "
        if o.status in EXECUTION_STATUSES:
            action += f"""
            <form method='post' action='/admin/company/opportunities/{o.id}/stage' style='display:inline-flex;gap:6px;align-items:center;flex-wrap:wrap'>
              <select class='select' name='stage' style='width:auto;padding:8px 10px'>
                <option value='contacted'>تم التواصل</option>
                <option value='replied'>تم الرد</option>
                <option value='negotiating'>قيد التفاوض</option>
                <option value='won'>ناجحة</option>
                <option value='lost'>غير ناجحة</option>
              </select>
              <button class='btn btn-muted' type='submit'>تحديث</button>
            </form> """
        if archive_button and o.status not in ARCHIVE_STATUSES:
            action += f"""
            <form method='post' action='/admin/company/opportunities/{o.id}/archive' style='display:inline'>
              <button class='btn btn-muted' type='submit' onclick="return confirm('أرشفة هذه الفرصة؟');">أرشفة</button>
            </form>"""

        rendered.append(
            "<tr>"
            f"<td>OP-{o.id:04d}</td>"
            f"<td>{core.esc(o.priority)}</td>"
            f"<td>{_source_badge(o.source)}</td>"
            f"<td><strong>{core.esc(o.title)}</strong>"
            f"<details style='margin-top:6px'><summary class='muted' style='cursor:pointer'>عرض التفاصيل</summary>"
            f"<div style='margin-top:7px;line-height:1.7'>{core.esc(o.details or '—')}</div></details></td>"
            f"<td>{core.esc(f'{o.score:.0f}' if o.score is not None else '—')}</td>"
            f"<td>{core.esc(STATUS_AR.get(o.status, o.status))}</td>"
            f"<td>{action or '—'}</td>"
            "</tr>"
        )
    return "".join(rendered)


def opportunities_unified_page(request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect

    sync_focused_feed(db)
    new_rows = list(
        db.scalars(
            select(ai_company.CompanyOpportunity)
            .where(ai_company.CompanyOpportunity.status.in_(NEW_STATUSES))
            .order_by(ai_company.CompanyOpportunity.score.desc().nullslast(), ai_company.CompanyOpportunity.created_at.desc())
        ).all()
    )
    execution_rows = list(
        db.scalars(
            select(ai_company.CompanyOpportunity)
            .where(ai_company.CompanyOpportunity.status.in_(EXECUTION_STATUSES))
            .order_by(ai_company.CompanyOpportunity.updated_at.desc())
        ).all()
    )
    archived_rows = list(
        db.scalars(
            select(ai_company.CompanyOpportunity)
            .where(ai_company.CompanyOpportunity.status.in_(ARCHIVE_STATUSES))
            .order_by(ai_company.CompanyOpportunity.updated_at.desc())
            .limit(50)
        ).all()
    )
    agents_count = int(
        db.scalar(select(func.count(CompanyAgent.id)).where(CompanyAgent.status == "active")) or 0
    )

    new_html = _opportunity_rows(new_rows, allow_assign=True) or "<tr><td colspan='7' class='muted'>لا توجد فرص جديدة.</td></tr>"
    execution_html = _opportunity_rows(execution_rows, allow_assign=False) or "<tr><td colspan='7' class='muted'>لا توجد فرص تحت التنفيذ.</td></tr>"
    archive_html = _opportunity_rows(archived_rows, allow_assign=False, archive_button=False) or "<tr><td colspan='7' class='muted'>لا يوجد أرشيف بعد.</td></tr>"

    table_head = "<thead><tr><th>الرقم</th><th>الأولوية</th><th>المصدر</th><th>الفرصة</th><th>التقييم</th><th>الحالة</th><th>الإجراء</th></tr></thead>"
    body = f"""
    <main class='wrap' style='padding:28px 0 48px'>
      <div style='display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap'>
        <div><h1 style='margin-bottom:4px'>الفرص والإسناد</h1>
        <p class='muted' style='margin:0'>مكان واحد للفرص الجديدة، الإسناد، التنفيذ والأرشيف.</p></div>
        <div style='display:flex;gap:8px;flex-wrap:wrap'>
          <a class='btn btn-muted' href='/admin/company'>مركز التحكم</a>
          <a class='btn btn-blue' href='/admin/company/agents'>المندوبون ({agents_count})</a>
        </div>
      </div>

      <div class='grid grid-mobile-1' style='grid-template-columns:repeat(3,1fr);margin:18px 0'>
        <section class='card' style='padding:18px'><div class='muted'>جديدة</div><div style='font-size:30px;font-weight:900'>{len(new_rows)}</div></section>
        <section class='card' style='padding:18px'><div class='muted'>تحت التنفيذ</div><div style='font-size:30px;font-weight:900'>{len(execution_rows)}</div></section>
        <section class='card' style='padding:18px'><div class='muted'>في الأرشيف</div><div style='font-size:30px;font-weight:900'>{len(archived_rows)}</div></section>
      </div>

      <section class='card' style='padding:22px;margin-bottom:18px'>
        <h2>الفرص الجديدة</h2>
        <div class='table-wrap'><table>{table_head}<tbody>{new_html}</tbody></table></div>
      </section>

      <section class='card' style='padding:22px;margin-bottom:18px'>
        <h2>تحت التنفيذ</h2>
        <div class='table-wrap'><table>{table_head}<tbody>{execution_html}</tbody></table></div>
      </section>

      <details class='card' style='padding:22px'>
        <summary style='font-size:21px;font-weight:900;cursor:pointer'>الأرشيف ({len(archived_rows)})</summary>
        <div class='table-wrap' style='margin-top:14px'><table>{table_head}<tbody>{archive_html}</tbody></table></div>
      </details>
    </main>
    """
    return HTMLResponse(core.page_shell("الفرص والإسناد", body, admin=True))


@core.app.post("/admin/company/opportunities/{opportunity_id}/archive")
def archive_opportunity(opportunity_id: int, request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect
    row = db.get(ai_company.CompanyOpportunity, opportunity_id)
    if not row:
        raise HTTPException(status_code=404, detail="الفرصة غير موجودة")
    row.status = "archived"
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    core.log_event(db, "opportunity_archived", details=f"OP-{row.id:04d}")
    return RedirectResponse("/admin/company/opportunities", status_code=303)


_dashboard_route = _find_route("/admin/company", "GET")
if _dashboard_route is not None:
    _original_dashboard = _dashboard_route.dependant.call

    def _compact_dashboard(request: Request, db: Session = Depends(core.get_db)):
        response = _original_dashboard(request, db)
        if not isinstance(response, HTMLResponse):
            return response
        html = response.body.decode("utf-8", errors="replace")
        html = _compact_dashboard_html(html, db)
        response.body = html.encode("utf-8")
        response.headers["content-length"] = str(len(response.body))
        return response

    _dashboard_route.endpoint = _compact_dashboard
    _dashboard_route.dependant.call = _compact_dashboard


_opportunities_route = _find_route("/admin/company/opportunities", "GET")
if _opportunities_route is not None:
    _opportunities_route.endpoint = opportunities_unified_page
    _opportunities_route.dependant.call = opportunities_unified_page
