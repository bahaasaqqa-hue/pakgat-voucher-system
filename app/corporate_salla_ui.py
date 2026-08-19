"""Final Corporate Benefits UI wording for the Salla-managed verification flow."""
from __future__ import annotations

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from app import application as core
from app.corporate_benefits import _admin_redirect
from app.corporate_salla_profile_bridge import salla_managed_readiness


def _find_route(path: str, method: str):
    for route in core.app.routes:
        if isinstance(route, APIRoute) and route.path == path and method in route.methods:
            return route
    return None


_admin_route = _find_route("/admin/company/corporate", "GET")
if _admin_route is not None:
    _original_admin = _admin_route.dependant.call

    def _corporate_admin_salla_ui(request: Request, db: Session = Depends(core.get_db)):
        response = _original_admin(request, db)
        if not isinstance(response, HTMLResponse):
            return response
        html = response.body.decode("utf-8", errors="replace")
        html = html.replace(
            "الجوال → البريد الوظيفي → OTP → مجموعة سلة",
            "سلة: دخول + OTP الجوال + OTP البريد · Google: الشركة + العضوية + مجموعة سلة",
        )
        html = html.replace(
            "<div class='muted'>بريد OTP</div><strong>جاهز</strong>",
            "<div class='muted'>تحقق البريد</div><strong>تديره سلة</strong>",
        )
        html = html.replace(
            "<div class='muted'>بريد OTP</div><strong>بانتظار الإعداد</strong>",
            "<div class='muted'>تحقق البريد</div><strong>تديره سلة</strong>",
        )
        sync_button = "<form method='post' action='/admin/company/corporate/sync-pending' style='margin:0'><button class='btn btn-muted' type='submit'>مزامنة المنتظرين مع سلة</button></form>"
        marker = "<a class='btn btn-blue' href='/admin/company/corporate/companies/new'>إضافة شركة</a>"
        if marker in html and "/admin/company/corporate/sync-pending" not in html:
            html = html.replace(marker, f"<div style='display:flex;gap:8px;flex-wrap:wrap'>{sync_button}{marker}</div>", 1)
        response.body = html.encode("utf-8")
        response.headers["content-length"] = str(len(response.body))
        return response

    _admin_route.endpoint = _corporate_admin_salla_ui
    _admin_route.dependant.call = _corporate_admin_salla_ui


_readiness_route = _find_route("/admin/company/corporate/readiness", "GET")
if _readiness_route is not None:
    def _readiness_salla(request: Request, db: Session = Depends(core.get_db)):
        redirect = _admin_redirect(request)
        if redirect:
            return redirect
        ready = salla_managed_readiness(db)
        return {
            "live": ready["live"],
            "verification_provider": "Salla",
            "salla_profile_mode": ready["salla_profile_mode"],
            "salla_oauth": ready["salla_oauth"],
            "companies": ready["companies"],
            "companies_with_group": ready["companies_with_group"],
            "webhook_path": ready["webhook_path"],
            "storefront_activation_url": ready["public_url"],
        }

    _readiness_route.endpoint = _readiness_salla
    _readiness_route.dependant.call = _readiness_salla
