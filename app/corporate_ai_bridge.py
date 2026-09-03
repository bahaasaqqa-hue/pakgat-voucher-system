"""Expose Corporate Benefits inside the Pakgat AI Company V2 navigation/dashboard."""
from __future__ import annotations

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import application as core
from app import ai_company_dashboard_v2 as v2
from app.corporate_benefits import CorporateCompany, CorporateMember, corporate_readiness


# Add a clear B2B section to the existing Arabic sidebar.
if not any(item[1] == "/admin/company/corporate" for item in v2.NAV_ITEMS):
    insert_at = next((i for i, item in enumerate(v2.NAV_ITEMS) if item[1] == "/admin/company/technology"), len(v2.NAV_ITEMS))
    v2.NAV_ITEMS.insert(insert_at, ("الشركات والموظفون", "/admin/company/corporate", "▣"))


def _find_company_route():
    for route in core.app.routes:
        if isinstance(route, APIRoute) and route.path == "/admin/company" and "GET" in route.methods:
            return route
    return None


_route = _find_company_route()
if _route is not None:
    _original = _route.dependant.call

    def _dashboard_with_corporate(request: Request, db: Session = Depends(core.get_db)):
        response = _original(request, db)
        if not isinstance(response, HTMLResponse):
            return response
        ready = corporate_readiness(db)
        companies = int(db.scalar(select(func.count(CorporateCompany.id)).where(CorporateCompany.status == "active")) or 0)
        active_members = int(db.scalar(select(func.count(CorporateMember.id)).where(CorporateMember.status == "active")) or 0)
        pending = int(db.scalar(select(func.count(CorporateMember.id)).where(CorporateMember.status == "verified_pending_sync")) or 0)
        status = "جاهز للربط" if ready["salla_oauth"] and companies else "قيد التجهيز"
        section = f"""
        <section class='ai-panel'>
          <div class='ai-panel-head'><h2>الشركات والموظفون</h2><a class='ai-link' href='/admin/company/corporate'>فتح النظام</a></div>
          <div class='ai-stat-row'><span>الحالة</span><strong class='ai-number'>{core.esc(status)}</strong></div>
          <div class='ai-stat-row'><span>شركات مفعلة</span><strong class='ai-number'>{companies}</strong></div>
          <div class='ai-stat-row'><span>موظفون نشطون</span><strong class='ai-number'>{active_members}</strong></div>
          <div class='ai-stat-row'><span>بانتظار مزامنة سلة</span><strong class='ai-number'>{pending}</strong></div>
          <div class='ai-note'>سلة: تسجيل الدخول + OTP الجوال + OTP البريد · Google: نطاق الشركة + العضوية + مجموعة العميل</div>
        </section>
        """
        html = response.body.decode("utf-8", errors="replace")
        marker = "<div class='ai-section-title'>"
        pos = html.rfind(marker)
        if pos >= 0:
            html = html[:pos] + section + html[pos:]
        else:
            html = html.replace("</main>", section + "</main>", 1)
        response.body = html.encode("utf-8")
        response.headers["content-length"] = str(len(response.body))
        return response

    _route.endpoint = _dashboard_with_corporate
    _route.dependant.call = _dashboard_with_corporate
