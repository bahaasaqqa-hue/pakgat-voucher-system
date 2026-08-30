"""Public Pakgat merchant portal routes.

Authentication and dashboard behavior are added incrementally under tests. This
module is intentionally separate from the internal `/admin` merchant experience.
"""

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import application as core


@core.app.get("/merchant", response_class=HTMLResponse)
def merchant_portal_home(request: Request, db: Session = Depends(core.get_db)):
    _ = request, db
    return HTMLResponse("<h1>Pakgat Merchant Portal</h1>")


@core.app.post("/merchant/login/request", response_class=HTMLResponse)
async def merchant_portal_request_login(request: Request, db: Session = Depends(core.get_db)):
    _ = request, db
    return HTMLResponse("<h1>Pakgat Merchant Login</h1>")


@core.app.post("/merchant/login/verify")
async def merchant_portal_verify_login(request: Request, db: Session = Depends(core.get_db)):
    _ = request, db
    return RedirectResponse("/merchant", status_code=303)


@core.app.get("/merchant/dashboard", response_class=HTMLResponse)
def merchant_portal_dashboard(request: Request, db: Session = Depends(core.get_db)):
    _ = request, db
    return HTMLResponse("<h1>Pakgat Merchant Dashboard</h1>")


@core.app.post("/merchant/logout")
def merchant_portal_logout(request: Request):
    _ = request
    return RedirectResponse("/merchant", status_code=303)


__all__ = [
    "merchant_portal_home",
    "merchant_portal_request_login",
    "merchant_portal_verify_login",
    "merchant_portal_dashboard",
    "merchant_portal_logout",
]
