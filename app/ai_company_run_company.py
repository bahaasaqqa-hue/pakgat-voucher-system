"""One-click 'run the company' orchestration for currently connected systems."""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.routing import APIRoute
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import application as core
from app import ai_company
from app.ai_company_governance import generate_ceo_brief
from app.ai_company_radar_focus import sync_focused_feed
from app.ai_company_sources import refresh_source_inventory
from app.ai_company_store_ops import run_store_ops_scan


def _admin_redirect(request: Request):
    try:
        core.require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)
    return None


def run_connected_company_cycle(db: Session) -> dict:
    """Run every AUTO-safe check available from connected data only."""
    created_opportunities, archived_legacy = sync_focused_feed(db)
    refresh_source_inventory(db)
    store = run_store_ops_scan(db)
    snapshot = ai_company.collect_company_snapshot(db)
    ai_company.evaluate_alerts(db, snapshot)
    ai_company.save_snapshot(db, snapshot)
    generate_ceo_brief(db, period="daily", save=True)

    # Every open P0/P1 alert should have a task so it cannot disappear inside a table.
    alerts = list(db.scalars(select(ai_company.CompanyAlert).where(
        ai_company.CompanyAlert.status == "open",
        ai_company.CompanyAlert.severity.in_(["P0", "P1"]),
    )).all())
    tasks_created = 0
    for alert in alerts:
        existing = db.scalar(select(ai_company.CompanyTask).where(
            ai_company.CompanyTask.status == "open",
            ai_company.CompanyTask.title == alert.title,
        ))
        if existing:
            continue
        db.add(ai_company.CompanyTask(priority=alert.severity, department=alert.source, title=alert.title, status="open"))
        tasks_created += 1
    if tasks_created:
        db.commit()

    result = {
        "opportunities_created": created_opportunities,
        "legacy_archived": archived_legacy,
        "store_issues_open": store["open"],
        "tasks_created": tasks_created,
        "company_health": snapshot["overall_score"],
    }
    core.log_event(db, "company_cycle_run", details="; ".join(f"{k}={v}" for k, v in result.items()))
    return result


@core.app.post("/admin/company/run-company")
def run_company(request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect
    run_connected_company_cycle(db)
    return RedirectResponse("/admin/company?company_run=1", status_code=303)


def _find_company_route():
    for route in core.app.routes:
        if isinstance(route, APIRoute) and route.path == "/admin/company" and "GET" in route.methods:
            return route
    return None


_company_route = _find_company_route()
if _company_route is not None:
    _original_dashboard = _company_route.dependant.call

    def _dashboard_with_run_button(request: Request, db: Session = Depends(core.get_db)):
        response = _original_dashboard(request, db)
        if not isinstance(response, HTMLResponse):
            return response
        html = response.body.decode("utf-8", errors="replace")
        button = "<form method='post' action='/admin/company/run-company' style='margin:0'><button class='btn btn-blue' type='submit'>شغّل الشركة</button></form>"
        marker = "<form method='post' action='/admin/company/refresh'>"
        pos = html.find(marker)
        if pos >= 0 and "action='/admin/company/run-company'" not in html:
            html = html[:pos] + button + html[pos:]
        response.body = html.encode("utf-8")
        response.headers["content-length"] = str(len(response.body))
        return response

    _company_route.endpoint = _dashboard_with_run_button
    _company_route.dependant.call = _dashboard_with_run_button
