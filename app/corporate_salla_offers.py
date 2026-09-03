"""Optional Salla Special Offer provisioning for Corporate Benefits.

Kept behind an explicit feature flag so employee verification/group sync can go
live independently from discount mechanics. Requires Salla specialoffers.read_write.
"""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import application as core
from app.corporate_benefits import CorporateCompany, CorporateAudit, _admin_redirect, _salla_request


OFFER_PROVISION_ENABLED = core.env("CORPORATE_ENABLE_OFFER_PROVISION", "false").lower() == "true"


def provision_percentage_offer(db: Session, company: CorporateCompany) -> tuple[bool, str]:
    if not OFFER_PROVISION_ENABLED:
        return False, "Corporate offer provisioning is disabled by safety flag"
    if not company.salla_group_id:
        return False, "Company has no Salla Customer Group ID"
    if float(company.discount_percent or 0) <= 0:
        return False, "Company discount percentage is zero"

    start = date.today()
    expiry = start + timedelta(days=max(30, int(company.membership_days or 365)))
    payload = {
        "name": f"{company.name} Corporate Benefits",
        "message": f"مزايا موظفي {company.name} عبر بكجات",
        "applied_channel": "browser_and_application",
        "offer_type": "percentage",
        "applied_to": "order",
        "start_date": start.isoformat(),
        "expiry_date": expiry.isoformat(),
        "min_purchase_amount": 0,
        "get": {
            "discount_type": "percentage",
            "discount_amount": float(company.discount_percent),
        },
        "customer_groups": [int(company.salla_group_id)],
        "select_by": "mobile",
        "applied_with_coupon": False,
    }
    ok, result, status = _salla_request(db, "POST", "/specialoffers", payload=payload)
    if not ok or not isinstance(result, dict):
        return False, f"Salla HTTP {status or 'connection'}: {str(result)[:350]}"
    data = result.get("data") or {}
    offer_id = data.get("id") if isinstance(data, dict) else None
    if not offer_id:
        return False, "Salla did not return a Special Offer ID"
    company.salla_special_offer_id = str(offer_id)
    db.commit()
    return True, str(offer_id)


@core.app.post("/admin/company/corporate/companies/{company_id}/provision-offer")
def corporate_provision_offer(company_id: int, request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect
    company = db.get(CorporateCompany, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="الشركة غير موجودة")
    ok, message = provision_percentage_offer(db, company)
    db.add(CorporateAudit(action="corporate_offer_provisioned" if ok else "corporate_offer_failed", company_id=company.id, details=message[:1000]))
    db.commit()
    return RedirectResponse(f"/admin/company/corporate?offer={'ok' if ok else 'failed'}", status_code=303)
