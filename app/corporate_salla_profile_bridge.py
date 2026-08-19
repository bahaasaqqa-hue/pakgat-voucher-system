"""Salla-managed Corporate Benefits activation bridge.

Final activation model:
- Salla owns customer login/mobile OTP and email OTP in the storefront/theme.
- Google/Pakgat receives customer.updated, resolves the Salla profile email,
  maps the email domain to a corporate company, and syncs the customer into the
  company's Salla Customer Group.

This module intentionally does not send OTP codes and does not replace Salla
customer authentication.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import timedelta

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.routing import APIRoute
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import application as core
from app import corporate_benefits as corporate_base
from app.corporate_benefits import (
    CORPORATE_LIVE,
    CorporateCompany,
    CorporateCompanyDomain,
    CorporateMember,
    _admin_redirect,
    _audit,
    _email_domain,
    _now,
    _salla_access_token,
    _salla_request,
    salla_add_customer_to_group,
    salla_create_company_group,
)


CORPORATE_SALLA_PROFILE_MODE = core.env("CORPORATE_SALLA_PROFILE_MODE", "true").lower() == "true"
CORPORATE_STOREFRONT_ACTIVATION_URL = core.env("CORPORATE_STOREFRONT_ACTIVATION_URL", "https://pakgat.com").strip()


def _valid_salla_signature(body: bytes, provided: str) -> bool:
    """Verify Salla X-Salla-Signature using the configured webhook secret."""
    if not core.SALLA_WEBHOOK_SECRET or not provided:
        return False
    expected = hmac.new(core.SALLA_WEBHOOK_SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, provided.strip())


def _payload_customer_id(payload: dict) -> str:
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        return ""
    candidates = [
        data.get("id"),
        (data.get("customer") or {}).get("id") if isinstance(data.get("customer"), dict) else None,
        data.get("customer_id"),
    ]
    for value in candidates:
        if value not in (None, ""):
            return str(value).strip()
    return ""


def salla_customer_details(db: Session, customer_id: str) -> tuple[bool, dict | str]:
    ok, result, status = _salla_request(db, "GET", f"/customers/{customer_id}")
    if not ok:
        return False, f"Salla customer details failed ({status or 'connection'}): {str(result)[:300]}"
    data = result.get("data") if isinstance(result, dict) else None
    if not isinstance(data, dict):
        return False, "Salla customer details response is missing data"
    return True, data


def _upsert_member_from_salla(db: Session, customer: dict) -> tuple[str, CorporateMember | None, CorporateCompany | None]:
    customer_id = str(customer.get("id") or "").strip()
    email = str(customer.get("email") or "").strip().lower()
    mobile = str(customer.get("mobile") or customer.get("phone") or "").strip()
    domain = _email_domain(email)

    if not customer_id:
        return "missing_customer_id", None, None
    if not domain:
        return "no_corporate_email", None, None

    domain_row = db.scalar(
        select(CorporateCompanyDomain).where(
            CorporateCompanyDomain.domain == domain,
            CorporateCompanyDomain.status == "active",
        )
    )
    if not domain_row:
        return "domain_not_enrolled", None, None

    company = db.get(CorporateCompany, domain_row.company_id)
    if not company or company.status != "active":
        return "company_inactive", None, None

    # Keep one active employer locally. Removing a previous Salla group is a
    # separate controlled offboarding action and is not performed here.
    old_rows = list(
        db.scalars(
            select(CorporateMember).where(
                CorporateMember.salla_customer_id == customer_id,
                CorporateMember.company_id != company.id,
                CorporateMember.status.in_(["active", "verified_pending_sync"]),
            )
        ).all()
    )
    for old in old_rows:
        old.status = "superseded"
        old.updated_at = _now()

    member = db.scalar(
        select(CorporateMember).where(
            CorporateMember.salla_customer_id == customer_id,
            CorporateMember.company_id == company.id,
        )
    )
    if member is None:
        member = CorporateMember(
            salla_customer_id=customer_id,
            mobile=mobile,
            company_id=company.id,
            corporate_email=email,
            email_verified=True,
            verified_at=_now(),
            expires_at=_now() + timedelta(days=max(1, int(company.membership_days or 365))),
            status="verified_pending_sync",
        )
        db.add(member)
        db.commit()
        db.refresh(member)
    else:
        member.mobile = mobile
        member.corporate_email = email
        member.email_verified = True
        member.verified_at = _now()
        member.expires_at = _now() + timedelta(days=max(1, int(company.membership_days or 365)))
        if member.status != "active":
            member.status = "verified_pending_sync"
        member.updated_at = _now()
        member.last_error = None
        db.commit()

    _audit(
        db,
        "corporate_salla_profile_verified",
        company_id=company.id,
        member_id=member.id,
        details=f"customer_id={customer_id}; domain={domain}",
    )
    return "eligible", member, company


def sync_member_to_salla_group(db: Session, member: CorporateMember, company: CorporateCompany) -> tuple[bool, str]:
    if not CORPORATE_LIVE:
        member.status = "verified_pending_sync"
        member.last_error = "Corporate live mode is disabled"
        member.updated_at = _now()
        db.commit()
        return False, "Corporate live mode is disabled"

    if not company.salla_group_id:
        created, message = salla_create_company_group(db, company)
        if not created:
            member.status = "verified_pending_sync"
            member.last_error = message
            member.updated_at = _now()
            db.commit()
            return False, message

    ok, customer_or_error = salla_customer_details(db, member.salla_customer_id)
    if not ok:
        member.status = "verified_pending_sync"
        member.last_error = str(customer_or_error)
        member.updated_at = _now()
        db.commit()
        return False, str(customer_or_error)

    groups = customer_or_error.get("groups") or []
    group_id = str(company.salla_group_id)
    if any(str(value) == group_id for value in groups):
        member.status = "active"
        member.salla_synced_at = _now()
        member.last_error = None
        member.updated_at = _now()
        db.commit()
        return True, "Customer already belongs to the corporate Salla group"

    added, message = salla_add_customer_to_group(db, member.salla_customer_id, group_id)
    if added:
        member.status = "active"
        member.salla_synced_at = _now()
        member.last_error = None
        member.updated_at = _now()
        db.commit()
        _audit(db, "corporate_salla_group_synced", company_id=company.id, member_id=member.id, details=message)
        return True, message

    member.status = "verified_pending_sync"
    member.last_error = message
    member.updated_at = _now()
    db.commit()
    _audit(db, "corporate_salla_group_sync_failed", company_id=company.id, member_id=member.id, details=message)
    return False, message


def process_customer_updated(db: Session, payload: dict) -> dict:
    event = str(payload.get("event") or "").strip()
    if event != "customer.updated":
        return {"ok": True, "ignored": True, "reason": "event_not_customer_updated"}

    customer_id = _payload_customer_id(payload)
    if not customer_id:
        return {"ok": True, "ignored": True, "reason": "missing_customer_id"}

    ok, customer_or_error = salla_customer_details(db, customer_id)
    if not ok:
        _audit(db, "corporate_customer_fetch_failed", details=f"customer_id={customer_id}; error={customer_or_error}")
        return {"ok": False, "customer_id": customer_id, "reason": str(customer_or_error)}

    state, member, company = _upsert_member_from_salla(db, customer_or_error)
    if state != "eligible" or member is None or company is None:
        return {"ok": True, "ignored": True, "customer_id": customer_id, "reason": state}

    synced, message = sync_member_to_salla_group(db, member, company)
    return {
        "ok": True,
        "customer_id": customer_id,
        "company_id": company.id,
        "member_id": member.id,
        "status": member.status,
        "synced": synced,
        "message": message,
    }


@core.app.post("/webhooks/salla-corporate")
async def corporate_salla_webhook(request: Request, db: Session = Depends(core.get_db)):
    """Dedicated signed webhook endpoint prepared for customer.updated."""
    if not CORPORATE_SALLA_PROFILE_MODE:
        return JSONResponse({"ok": True, "disabled": True})

    body = await request.body()
    signature = request.headers.get("x-salla-signature", "")
    if not _valid_salla_signature(body, signature):
        raise HTTPException(status_code=401, detail="Invalid Salla signature")

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc

    result = process_customer_updated(db, payload)
    # Acknowledge accepted events even if group sync must retry later; local
    # membership state retains the failure safely.
    return JSONResponse(result, status_code=200)


@core.app.post("/admin/company/corporate/sync-pending")
def corporate_sync_pending(request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect

    rows = list(
        db.scalars(
            select(CorporateMember).where(
                CorporateMember.status == "verified_pending_sync",
                CorporateMember.email_verified.is_(True),
            )
        ).all()
    )
    synced = 0
    for member in rows:
        company = db.get(CorporateCompany, member.company_id)
        if not company or company.status != "active":
            continue
        ok, _ = sync_member_to_salla_group(db, member, company)
        synced += int(ok)

    _audit(db, "corporate_pending_sync_run", details=f"candidates={len(rows)}; synced={synced}")
    return RedirectResponse(f"/admin/company/corporate?sync_pending={len(rows)}&sync_ok={synced}", status_code=303)


def salla_managed_readiness(db: Session) -> dict:
    companies = int(db.scalar(select(func.count(CorporateCompany.id)).where(CorporateCompany.status == "active")) or 0)
    groups = int(
        db.scalar(
            select(func.count(CorporateCompany.id)).where(
                CorporateCompany.status == "active",
                CorporateCompany.salla_group_id.is_not(None),
            )
        )
        or 0
    )
    return {
        "live": CORPORATE_LIVE,
        "salla_oauth": bool(_salla_access_token(db)),
        "salla_profile_mode": CORPORATE_SALLA_PROFILE_MODE,
        "verification_provider": "Salla",
        "companies": companies,
        "companies_with_group": groups,
        "webhook_path": "/webhooks/salla-corporate",
        "public_url": CORPORATE_STOREFRONT_ACTIVATION_URL,
        # Compatibility key for the legacy admin template. SMTP is deliberately
        # not a production requirement in the approved Salla-managed flow.
        "smtp": True,
    }


# Make all existing Corporate admin/readiness callers use the final Salla-owned
# verification architecture without rewriting the older database/admin module.
corporate_base.corporate_readiness = salla_managed_readiness


def _legacy_public_home():
    html = f"""<!doctype html><html lang='ar' dir='rtl'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>مزايا الشركات | بكجات</title></head><body style='font-family:Arial,Tahoma,sans-serif;background:#f4f8ff;color:#10233f'><main style='width:min(680px,calc(100% - 28px));margin:40px auto'><section style='background:#fff;border:1px solid #dce6f7;border-radius:18px;padding:28px'><h1 style='color:#0d47d9'>فعّل مزايا شركتك</h1><p>التفعيل يتم من داخل متجر بكجات باستخدام حساب سلة. سلة تتولى تسجيل الدخول والتحقق من الجوال والبريد الوظيفي.</p><a href='{core.esc(CORPORATE_STOREFRONT_ACTIVATION_URL)}' style='display:inline-block;background:#0d47d9;color:#fff;padding:12px 18px;border-radius:10px;text-decoration:none;font-weight:800'>الذهاب إلى بكجات</a></section></main></body></html>"""
    return HTMLResponse(html)


async def _legacy_public_post(request: Request, db: Session = Depends(core.get_db)):
    return RedirectResponse(CORPORATE_STOREFRONT_ACTIVATION_URL, status_code=303)


def _disable_legacy_google_otp_routes() -> None:
    """Prevent the obsolete Google/SMTP OTP flow from being enabled accidentally."""
    for route in core.app.routes:
        if not isinstance(route, APIRoute):
            continue
        if route.path == "/corporate" and "GET" in route.methods:
            route.endpoint = _legacy_public_home
            route.dependant.call = _legacy_public_home
        elif route.path in {"/corporate/start", "/corporate/request-otp", "/corporate/verify"} and "POST" in route.methods:
            route.endpoint = _legacy_public_post
            route.dependant.call = _legacy_public_post


_disable_legacy_google_otp_routes()
