"""Admin-only merchant contract draft and Pakgat approval actions.

This module stays additive: it does not send anything to Sadq and does not
activate a merchant. It only creates an internal draft and freezes Pakgat's
first-party approval snapshot when an admin confirms it.
"""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import application as core
from app import merchant_contracts as contracts
from app import merchant_finance as finance


_BASE_CONTRACT_SUMMARY = contracts.merchant_contract_summary_html


def _latest_contract(db: Session, merchant_id: int) -> Optional[finance.MerchantContract]:
    return db.scalar(
        select(finance.MerchantContract)
        .where(finance.MerchantContract.merchant_id == merchant_id)
        .order_by(finance.MerchantContract.created_at.desc())
        .limit(1)
    )


def _approval_for_contract(
    db: Session,
    contract_id: int,
) -> Optional[contracts.MerchantContractApproval]:
    return db.scalar(
        select(contracts.MerchantContractApproval)
        .where(contracts.MerchantContractApproval.merchant_contract_id == contract_id)
        .limit(1)
    )


def merchant_contract_summary_html(db: Session, merchant_id: int) -> str:
    """Add draft/approval controls and Pakgat approval audit to the contract card."""
    contract = _latest_contract(db, merchant_id)
    if contract is None:
        return f"""
        <section id='merchant-contract-summary' class='card' style='padding:18px;margin-bottom:18px'>
          <h2>اتفاقية الشراكة</h2>
          <p class='muted'>لا توجد اتفاقية شراكة مرتبطة بهذا التاجر بعد.</p>
          <form method='post' action='/admin/merchants/{merchant_id}/contracts/create-draft' style='margin-top:14px'>
            <button class='btn btn-blue' type='submit'>إنشاء مسودة عقد</button>
          </form>
        </section>
        """

    base = _BASE_CONTRACT_SUMMARY(db, merchant_id)
    action_html = ""
    if contract.status == "draft":
        action_html = f"""
        <section class='card' style='padding:18px;margin-bottom:18px'>
          <h2>اعتماد Pakgat</h2>
          <p class='muted'>عند الاعتماد يتم تثبيت رقم الاتفاقية، تاريخ الاعتماد، ونسخة بيانات التاجر. لا يتم إرسال العقد إلى صادق في هذه الخطوة.</p>
          <form method='post' action='/admin/merchants/{merchant_id}/contracts/{contract.id}/approve'>
            <button class='btn btn-blue' type='submit'>اعتماد العقد من Pakgat</button>
          </form>
        </section>
        """

    approval = _approval_for_contract(db, contract.id)
    approval_html = ""
    if approval is not None:
        approval_html = f"""
        <section class='card' style='padding:18px;margin-bottom:18px'>
          <h2>اعتماد Pakgat</h2>
          <div class='grid grid-mobile-1' style='grid-template-columns:repeat(2,1fr);gap:10px'>
            <p><strong>الممثل:</strong> {core.esc(approval.pakgat_signer_name)}</p>
            <p><strong>الصفة:</strong> {core.esc(approval.pakgat_signer_title)}</p>
            <p><strong>الجوال:</strong> <span dir='ltr'>{core.esc(approval.pakgat_signer_phone)}</span></p>
            <p><strong>تاريخ الاعتماد:</strong> {core.fmt_dt(approval.approved_at)}</p>
            <p><strong>نسخة القالب:</strong> <span dir='ltr'>{core.esc(approval.template_version)}</span></p>
            <p><strong>رقم الاتفاقية المثبت:</strong> <span dir='ltr'>{core.esc(approval.agreement_number_snapshot)}</span></p>
          </div>
          <p class='muted' style='margin-bottom:0'>بيانات الاعتماد محفوظة كلقطة ثابتة ولا تتغير عند تعديل ملف التاجر لاحقًا.</p>
        </section>
        """

    return base + action_html + approval_html


@core.app.post("/admin/merchants/{merchant_id}/contracts/create-draft")
def admin_create_contract_draft(
    merchant_id: int,
    request: Request,
    db: Session = Depends(core.get_db),
):
    redirect = contracts._admin_guard(request)
    if redirect:
        return redirect

    merchant = db.get(finance.Merchant, merchant_id)
    if merchant is None:
        raise HTTPException(status_code=404, detail="Merchant not found")

    existing = _latest_contract(db, merchant_id)
    if existing is None:
        now = core.now_utc()
        db.add(
            finance.MerchantContract(
                merchant_id=merchant_id,
                status="draft",
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()

    return RedirectResponse(f"/admin/merchants/{merchant_id}", status_code=303)


@core.app.post("/admin/merchants/{merchant_id}/contracts/{contract_id}/approve")
def admin_approve_contract(
    merchant_id: int,
    contract_id: int,
    request: Request,
    db: Session = Depends(core.get_db),
):
    redirect = contracts._admin_guard(request)
    if redirect:
        return redirect

    contract = db.get(finance.MerchantContract, contract_id)
    if contract is None or contract.merchant_id != merchant_id:
        raise HTTPException(status_code=404, detail="Merchant contract not found")

    contracts.approve_contract(db, contract)
    return RedirectResponse(f"/admin/merchants/{merchant_id}", status_code=303)


__all__ = [
    "merchant_contract_summary_html",
    "admin_create_contract_draft",
    "admin_approve_contract",
]
