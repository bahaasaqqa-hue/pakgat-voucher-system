"""Operational opportunity UX for the Pakgat AI Company Control Center."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.routing import APIRoute
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import ai_company
from app import ai_company_agent_reporting as reporting
from app import application as core
from app.ai_company_dispatch import CompanyAgent, OpportunityDispatch
from app.ai_company_radar_focus import sync_focused_feed


NEW_STATUSES = ["new"]
EXECUTION_STATUSES = ["review", "approved", "active", "assigned", "contacted", "replied", "negotiating"]
RECENT_STATUSES = ["won", "lost"]
ARCHIVE_STATUSES = ["archived"]

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
STATUS_CLASS = {
    "new": "opp-new",
    "review": "opp-progress",
    "approved": "opp-progress",
    "active": "opp-progress",
    "assigned": "opp-assigned",
    "contacted": "opp-progress",
    "replied": "opp-progress",
    "negotiating": "opp-progress",
    "won": "opp-won",
    "lost": "opp-lost",
    "archived": "opp-archived",
}

OPPORTUNITY_CSS = r"""
.opp-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:16px 0}.opp-kpi{padding:14px!important;min-height:88px}.opp-kpi-label{font-size:11px;color:#64748b;font-weight:900}.opp-kpi-value{font-size:28px!important;line-height:1.15;font-weight:950;color:#0b2d75;margin-top:7px}.opp-section{padding:17px!important;margin-bottom:14px!important}.opp-section-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:11px}.opp-section-head h2{margin:0!important}.opp-count{font-size:10px;font-weight:900;background:#f1f5f9;color:#475569;border-radius:999px;padding:5px 8px}.opp-table td{vertical-align:top!important}.opp-title{font-size:13px;font-weight:950;color:#102a5e;line-height:1.5}.opp-id{font-size:10px;color:#64748b;font-weight:900;margin-bottom:3px}.opp-meta{font-size:10px;color:#64748b;line-height:1.65;margin-top:5px}.opp-status{display:inline-flex;border-radius:999px;padding:5px 8px;font-size:10px;font-weight:950}.opp-new{background:#eff6ff;color:#1d4ed8}.opp-progress{background:#fff7ed;color:#b45309}.opp-assigned{background:#eef2ff;color:#5b21b6}.opp-won{background:#ecfdf5;color:#047857}.opp-lost{background:#fef2f2;color:#b91c1c}.opp-archived{background:#f1f5f9;color:#64748b}.opp-agent{margin-top:7px;border:1px solid #c7d2fe;background:#eef2ff;color:#3730a3;border-radius:9px;padding:7px 9px;font-size:11px;font-weight:950}.opp-latest{margin-top:6px;border-right:3px solid #2563eb;padding-right:8px;font-size:11px;line-height:1.65;color:#334155}.opp-actions{display:flex;gap:6px;flex-wrap:wrap;align-items:center}.opp-actions .btn{min-height:32px!important;padding:7px 9px!important}.opp-actions .select{min-height:32px!important;padding:6px 8px!important;width:auto!important;font-size:11px!important}.opp-details{margin-top:7px}.opp-details summary{cursor:pointer;color:#2563eb;font-size:10px;font-weight:900}.opp-history{display:grid;gap:7px;margin-top:8px}.opp-report{border:1px solid #e2e8f0;background:#f8fafc;border-radius:9px;padding:8px;font-size:10px;line-height:1.65}.opp-report strong{color:#0f2f70}.opp-evidence{display:inline-flex;margin-top:5px;background:#eff6ff;color:#1d4ed8;border-radius:7px;padding:5px 7px;font-weight:900}.opp-empty{text-align:center;padding:18px;color:#64748b;font-size:12px}.opp-archive summary{cursor:pointer;font-size:17px!important;font-weight:950;color:#173b7d}.opp-primary-meta{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}.opp-chip{font-size:9px;border:1px solid #e2e8f0;background:#fff;border-radius:999px;padding:4px 6px;color:#64748b;font-weight:850}@media(max-width:900px){.opp-kpis{grid-template-columns:repeat(2,1fr)}.opp-table th:nth-child(3),.opp-table td:nth-child(3){display:none}}@media(max-width:560px){.opp-kpis{grid-template-columns:1fr 1fr}.opp-table th,.opp-table td{white-space:normal!important}.opp-table th:nth-child(4),.opp-table td:nth-child(4){display:none}.opp-actions{min-width:120px}}
"""


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
        ) or 0
    )


def _remove_section_containing(html: str, marker: str) -> str:
    marker_pos = html.find(marker)
    if marker_pos < 0:
        return html
    start = html.rfind("<section", 0, marker_pos)
    if start < 0:
        return html
    end = html.find("</section>", marker_pos)
    if end < 0:
        return html
    return html[:start] + html[end + len("</section>"):]


def _replace_opportunity_kpi(html: str, new_count: int) -> str:
    badge = (
        f"<span style='position:absolute;top:12px;left:12px;background:#dc2626;color:#fff;border-radius:999px;padding:4px 9px;font-size:12px;font-weight:900'>{new_count} جديدة</span>"
        if new_count
        else "<span style='position:absolute;top:12px;left:12px;background:#e8eefc;color:#64748b;border-radius:999px;padding:4px 9px;font-size:12px;font-weight:900'>لا جديد</span>"
    )
    tile = (
        "<a href='/admin/company/opportunities' class='card' style='padding:20px;display:block;position:relative;min-height:140px'>"
        f"{badge}<div class='muted' style='margin-top:6px'>أحدث الفرص</div>"
        f"<div style='font-size:34px;font-weight:900;margin-top:12px'>{new_count}</div>"
        "<div class='muted' style='font-size:13px;margin-top:4px'>اضغط لعرض الفرص والإسناد</div></a>"
    )
    for label in ("Opportunities", "الفرص"):
        pattern = re.compile(
            r"<section class='card' style='padding:20px'>"
            rf"<div class='muted'>{re.escape(label)}</div>"
            r"<div style='font-size:34px;font-weight:900'>.*?</div></section>",
            re.DOTALL,
        )
        html, replaced = pattern.subn(tile, html, count=1)
        if replaced:
            break
    return html


def _compact_dashboard_html(html: str, db: Session) -> str:
    html = _replace_opportunity_kpi(html, _new_count(db))
    for marker in (
        "الفرص الجديدة لـ Pakgat",
        "Opportunity Dispatch · المندوبون",
        "إسناد الفرص · المندوبون",
    ):
        html = _remove_section_containing(html, marker)
    return html


def _context_maps(db: Session, opportunity_ids: list[int]):
    if not opportunity_ids:
        return {}, {}, {}

    dispatch_rows = list(
        db.scalars(
            select(OpportunityDispatch)
            .where(
                OpportunityDispatch.opportunity_id.in_(opportunity_ids),
                OpportunityDispatch.status == "sent",
            )
            .order_by(OpportunityDispatch.created_at.desc(), OpportunityDispatch.id.desc())
        ).all()
    )
    dispatch_by_opportunity = {}
    for row in dispatch_rows:
        dispatch_by_opportunity.setdefault(row.opportunity_id, row)

    agent_ids = {row.agent_id for row in dispatch_by_opportunity.values()}
    agents_by_id = {}
    if agent_ids:
        agents_by_id = {
            row.id: row
            for row in db.scalars(select(CompanyAgent).where(CompanyAgent.id.in_(agent_ids))).all()
        }

    report_rows = list(
        db.scalars(
            select(reporting.OpportunityAgentReport)
            .where(reporting.OpportunityAgentReport.opportunity_id.in_(opportunity_ids))
            .order_by(reporting.OpportunityAgentReport.created_at.desc(), reporting.OpportunityAgentReport.id.desc())
        ).all()
    )
    reports_by_opportunity: dict[int, list[reporting.OpportunityAgentReport]] = {}
    for row in report_rows:
        reports_by_opportunity.setdefault(row.opportunity_id, []).append(row)
    return dispatch_by_opportunity, agents_by_id, reports_by_opportunity


def _report_history_html(reports: list[reporting.OpportunityAgentReport]) -> str:
    if not reports:
        return "<div class='opp-meta'>لا توجد تقارير من المندوب حتى الآن.</div>"
    items = []
    for report in reports:
        evidence = ""
        if report.evidence_filename:
            evidence = (
                f"<a class='opp-evidence' target='_blank' href='/admin/company/agent-reports/{report.id}/evidence'>عرض صورة الإثبات</a>"
            )
        follow_up = (
            f"<div>متابعة: {core.esc(core.fmt_dt(report.follow_up_at))}</div>"
            if report.follow_up_at else ""
        )
        items.append(
            "<div class='opp-report'>"
            f"<strong>{core.esc(reporting.REPORT_ACTIONS.get(report.action, report.action))}</strong> · {core.esc(core.fmt_dt(report.created_at))}"
            f"<div>{core.esc(report.notes or 'بدون ملاحظات')}</div>{follow_up}{evidence}</div>"
        )
    return "<div class='opp-history'>" + "".join(items) + "</div>"


def _opportunity_rows(
    rows,
    allow_assign: bool,
    dispatch_by_opportunity: dict,
    agents_by_id: dict,
    reports_by_opportunity: dict,
    archive_button: bool = True,
) -> str:
    rendered = []
    for opportunity in rows:
        dispatch = dispatch_by_opportunity.get(opportunity.id)
        agent = agents_by_id.get(dispatch.agent_id) if dispatch else None
        reports = reports_by_opportunity.get(opportunity.id, [])
        latest_report = reports[0] if reports else None

        action_html = ""
        if allow_assign:
            action_html += f"<a class='btn btn-blue' href='/admin/company/opportunities/{opportunity.id}/assign'>إسناد</a>"
        if opportunity.status in EXECUTION_STATUSES:
            action_html += f"""
            <form method='post' action='/admin/company/opportunities/{opportunity.id}/stage' style='display:inline-flex;gap:5px;align-items:center'>
              <select class='select' name='stage'>
                <option value='contacted'>تم التواصل</option><option value='replied'>تم الرد</option>
                <option value='negotiating'>قيد التفاوض</option><option value='won'>ناجحة</option><option value='lost'>غير ناجحة</option>
              </select><button class='btn btn-muted' type='submit'>تحديث</button>
            </form>"""
        if archive_button and opportunity.status != "archived":
            action_html += f"""
            <form method='post' action='/admin/company/opportunities/{opportunity.id}/archive' style='display:inline'>
              <button class='btn btn-muted' type='submit' onclick="return confirm('أرشفة هذه الفرصة؟');">أرشفة</button>
            </form>"""

        assigned_html = ""
        if dispatch and agent:
            assigned_html = (
                f"<div class='opp-agent'>مسندة إلى: {core.esc(agent.name)}"
                f"<div class='opp-meta'>منذ {core.esc(core.fmt_dt(dispatch.sent_at or dispatch.created_at))}</div></div>"
            )
        latest_html = ""
        if latest_report:
            latest_html = (
                f"<div class='opp-latest'><strong>آخر تحديث:</strong> {core.esc(reporting.REPORT_ACTIONS.get(latest_report.action, latest_report.action))}"
                f" · {core.esc(core.fmt_dt(latest_report.created_at))}</div>"
            )

        rendered.append(
            "<tr>"
            f"<td><div class='opp-id'>OP-{opportunity.id:04d}</div><div class='opp-title'>{core.esc(opportunity.title)}</div>"
            f"<div class='opp-primary-meta'><span class='opp-chip'>{core.esc(opportunity.priority)}</span><span class='opp-chip'>Score {core.esc(f'{opportunity.score:.0f}' if opportunity.score is not None else '—')}</span></div>"
            f"<details class='opp-details'><summary>التفاصيل وسجل المندوب ({len(reports)})</summary><div class='opp-meta'>{core.esc(opportunity.details or '—')}</div>{_report_history_html(reports)}</details></td>"
            f"<td><span class='opp-status {STATUS_CLASS.get(opportunity.status, 'opp-progress')}'>{core.esc(STATUS_AR.get(opportunity.status, opportunity.status))}</span>{assigned_html}{latest_html}</td>"
            f"<td>{_source_badge(opportunity.source)}</td>"
            f"<td><div class='opp-meta'>أُنشئت<br>{core.esc(core.fmt_dt(opportunity.created_at))}</div><div class='opp-meta'>آخر تحديث<br>{core.esc(core.fmt_dt(opportunity.updated_at))}</div></td>"
            f"<td><div class='opp-actions'>{action_html or '—'}</div></td></tr>"
        )
    return "".join(rendered)


def opportunities_unified_page(request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect

    sync_focused_feed(db)
    reporting.archive_completed_opportunities(db)
    recent_cutoff = datetime.now(timezone.utc) - timedelta(hours=reporting.COMPLETION_ARCHIVE_HOURS)

    new_rows = list(
        db.scalars(
            select(ai_company.CompanyOpportunity)
            .where(ai_company.CompanyOpportunity.status.in_(NEW_STATUSES))
            .order_by(ai_company.CompanyOpportunity.created_at.desc(), ai_company.CompanyOpportunity.id.desc())
        ).all()
    )
    execution_rows = list(
        db.scalars(
            select(ai_company.CompanyOpportunity)
            .where(ai_company.CompanyOpportunity.status.in_(EXECUTION_STATUSES))
            .order_by(ai_company.CompanyOpportunity.updated_at.desc(), ai_company.CompanyOpportunity.id.desc())
        ).all()
    )
    recent_rows = list(
        db.scalars(
            select(ai_company.CompanyOpportunity)
            .where(
                ai_company.CompanyOpportunity.status.in_(RECENT_STATUSES),
                ai_company.CompanyOpportunity.updated_at >= recent_cutoff,
            )
            .order_by(ai_company.CompanyOpportunity.updated_at.desc(), ai_company.CompanyOpportunity.id.desc())
        ).all()
    )
    archived_rows = list(
        db.scalars(
            select(ai_company.CompanyOpportunity)
            .where(ai_company.CompanyOpportunity.status.in_(ARCHIVE_STATUSES))
            .order_by(ai_company.CompanyOpportunity.updated_at.desc(), ai_company.CompanyOpportunity.id.desc())
            .limit(100)
        ).all()
    )
    agents_count = int(
        db.scalar(select(func.count(CompanyAgent.id)).where(CompanyAgent.status == "active")) or 0
    )

    all_rows = new_rows + execution_rows + recent_rows + archived_rows
    opportunity_ids = list(dict.fromkeys(row.id for row in all_rows))
    dispatch_map, agents_map, reports_map = _context_maps(db, opportunity_ids)

    new_html = _opportunity_rows(new_rows, True, dispatch_map, agents_map, reports_map) or "<tr><td colspan='5' class='opp-empty'>لا توجد فرص جديدة.</td></tr>"
    execution_html = _opportunity_rows(execution_rows, False, dispatch_map, agents_map, reports_map) or "<tr><td colspan='5' class='opp-empty'>لا توجد فرص تحت التنفيذ.</td></tr>"
    recent_html = _opportunity_rows(recent_rows, False, dispatch_map, agents_map, reports_map) or "<tr><td colspan='5' class='opp-empty'>لا توجد فرص مكتملة خلال آخر 48 ساعة.</td></tr>"
    archive_html = _opportunity_rows(archived_rows, False, dispatch_map, agents_map, reports_map, archive_button=False) or "<tr><td colspan='5' class='opp-empty'>لا يوجد أرشيف بعد.</td></tr>"

    table_head = "<thead><tr><th>الفرصة</th><th>الحالة والمتابعة</th><th>المصدر</th><th>الوقت</th><th>الإجراء</th></tr></thead>"
    body = f"""
    <style>{OPPORTUNITY_CSS}</style>
    <main class='wrap'>
      <div style='display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap'>
        <div><h1 style='margin-bottom:4px'>الفرص والإسناد</h1><p class='muted' style='margin:0'>الجديد أولًا، والمسند يظهر باسم المندوب، والمكتمل يبقى 48 ساعة قبل الأرشفة التلقائية.</p></div>
        <div style='display:flex;gap:8px;flex-wrap:wrap'><a class='btn btn-muted' href='/admin/company'>مركز التحكم</a><a class='btn btn-blue' href='/admin/company/agents'>المندوبون ({agents_count})</a></div>
      </div>

      <div class='opp-kpis'>
        <section class='card opp-kpi'><div class='opp-kpi-label'>جديدة</div><div class='opp-kpi-value'>{len(new_rows)}</div></section>
        <section class='card opp-kpi'><div class='opp-kpi-label'>تحت التنفيذ</div><div class='opp-kpi-value'>{len(execution_rows)}</div></section>
        <section class='card opp-kpi'><div class='opp-kpi-label'>مكتملة مؤخرًا · 48 ساعة</div><div class='opp-kpi-value'>{len(recent_rows)}</div></section>
        <section class='card opp-kpi'><div class='opp-kpi-label'>الأرشيف</div><div class='opp-kpi-value'>{len(archived_rows)}</div></section>
      </div>

      <section class='card opp-section'><div class='opp-section-head'><h2>فرص جديدة</h2><span class='opp-count'>{len(new_rows)}</span></div><div class='table-wrap'><table class='opp-table'>{table_head}<tbody>{new_html}</tbody></table></div></section>
      <section class='card opp-section'><div class='opp-section-head'><h2>تحت التنفيذ</h2><span class='opp-count'>{len(execution_rows)}</span></div><div class='table-wrap'><table class='opp-table'>{table_head}<tbody>{execution_html}</tbody></table></div></section>
      <section class='card opp-section'><div class='opp-section-head'><h2>مكتملة مؤخرًا · 48 ساعة</h2><span class='opp-count'>{len(recent_rows)}</span></div><div class='table-wrap'><table class='opp-table'>{table_head}<tbody>{recent_html}</tbody></table></div></section>
      <details class='card opp-section opp-archive'><summary>الأرشيف ({len(archived_rows)})</summary><div class='table-wrap' style='margin-top:12px'><table class='opp-table'>{table_head}<tbody>{archive_html}</tbody></table></div></details>
    </main>"""
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
    reporting.revoke_opportunity_links(db, row.id)
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
        html = _compact_dashboard_html(response.body.decode("utf-8", errors="replace"), db)
        response.body = html.encode("utf-8")
        response.headers["content-length"] = str(len(response.body))
        return response

    _dashboard_route.endpoint = _compact_dashboard
    _dashboard_route.dependant.call = _compact_dashboard


_opportunities_route = _find_route("/admin/company/opportunities", "GET")
if _opportunities_route is not None:
    _opportunities_route.endpoint = opportunities_unified_page
    _opportunities_route.dependant.call = opportunities_unified_page
