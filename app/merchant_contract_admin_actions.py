"""Admin review actions for merchant onboarding.

The merchant first signs/stamps the generated agreement and uploads it. Pakgat
then reviews that copy, signs/stamps it, uploads the final joint PDF, and only
then may explicitly approve/activate the merchant. Legacy Sadq states remain
recognized for compatibility, but they are not part of the active onboarding
journey.
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
from app import merchant_onboarding as onboarding


_BASE_CONTRACT_SUMMARY = contracts.merchant_contract_summary_html


def _latest_contract(db: Session, merchant_id: int) -> Optional[finance.MerchantContract]:
    return db.scalar(
        select(finance.MerchantContract)
        .where(finance.MerchantContract.merchant_id == merchant_id)
        .order_by(finance.MerchantContract.created_at.desc())
        .limit(1)
    )


def _application(db: Session, merchant_id: int) -> Optional[onboarding.MerchantOnboardingApplication]:
    return db.scalar(
        select(onboarding.MerchantOnboardingApplication)
        .where(onboarding.MerchantOnboardingApplication.merchant_id == merchant_id)
        .limit(1)
    )


def _approval_for_contract(db: Session, contract_id: int) -> Optional[contracts.MerchantContractApproval]:
    return db.scalar(
        select(contracts.MerchantContractApproval)
        .where(contracts.MerchantContractApproval.merchant_contract_id == contract_id)
        .limit(1)
    )


def _document_list_html(db: Session, application_id: int) -> str:
    rows = db.scalars(
        select(onboarding.MerchantOnboardingDocument)
        .where(onboarding.MerchantOnboardingDocument.application_id == application_id)
        .order_by(onboarding.MerchantOnboardingDocument.created_at.asc())
    ).all()
    if not rows:
        return "<p class='muted'>لا توجد مستندات مرفوعة.</p>"
    items = "".join(
        f"<li>{core.esc(row.original_name)} <span class='muted'>({row.size_bytes // 1024} KB)</span></li>"
        for row in rows
    )
    return f"<ul style='margin:8px 0 0'>{items}</ul>"


def merchant_contract_summary_html(db: Session, merchant_id: int) -> str:
    """Render onboarding review state and expose activation only after final PDF."""
    contract = _latest_contract(db, merchant_id)
    application = _application(db, merchant_id)
    base = _BASE_CONTRACT_SUMMARY(db, merchant_id)

    if application is None:
        return base

    status_label = {
        "profile": "جاري إدخال البيانات",
        "documents": "جاري استكمال المستندات",
        "contract_ready": "العقد جاهز للتوقيع والختم من التاجر",
        "merchant_signed": "تم استلام عقد التاجر الموقّع والمختوم",
        "pending_review": "بانتظار مراجعة Pakgat",
        "changes_requested": "مطلوب استكمال",
        "approved": "معتمد",
        "rejected": "مرفوض",
        # Legacy compatibility only.
        "ready_for_sadq": "حالة توثيق قديمة",
        "sadq_pending": "حالة توثيق قديمة قيد الانتظار",
    }.get(application.status, application.status)
    note_html = (
        f"<p><strong>ملاحظة المراجعة:</strong> {core.esc(application.review_note)}</p>"
        if application.review_note else ""
    )
    documents_html = _document_list_html(db, application.id)

    action_html = ""
    if contract is not None and contract.status == "signed" and application.status == "pending_review":
        action_html = f"""
        <div style='display:grid;gap:10px;margin-top:16px'>
          <form method='post' action='/admin/merchants/{merchant_id}/contracts/{contract.id}/approve-onboarding'>
            <button class='btn btn-blue' type='submit'>اعتماد التاجر</button>
          </form>
          <form method='post' action='/admin/merchants/{merchant_id}/onboarding/request-changes' style='display:flex;gap:8px;flex-wrap:wrap'>
            <input name='note' required placeholder='ما المطلوب استكماله؟' style='min-width:280px;flex:1'>
            <button class='btn' type='submit'>طلب استكمال</button>
          </form>
          <form method='post' action='/admin/merchants/{merchant_id}/onboarding/reject' style='display:flex;gap:8px;flex-wrap:wrap'>
            <input name='note' required placeholder='سبب الرفض' style='min-width:280px;flex:1'>
            <button class='btn' type='submit'>رفض الطلب</button>
          </form>
        </div>
        """

    review_html = f"""
    <section id='merchant-onboarding-review' class='card' style='padding:18px;margin-bottom:18px'>
      <h2>طلب تسجيل التاجر</h2>
      <p><strong>الحالة:</strong> {core.esc(status_label)}</p>
      {note_html}
      <h3 style='margin-bottom:6px'>المستندات الرسمية المرفوعة</h3>
      {documents_html}
      {action_html}
    </section>
    """

    approval_html = ""
    if contract is not None:
        approval = _approval_for_contract(db, contract.id)
        if approval is not None:
            approval_html = f"""
            <section class='card' style='padding:18px;margin-bottom:18px'>
              <h2>اعتماد Pakgat النهائي</h2>
              <div class='grid grid-mobile-1' style='grid-template-columns:repeat(2,1fr);gap:10px'>
                <p><strong>الممثل:</strong> {core.esc(approval.pakgat_signer_name)}</p>
                <p><strong>الصفة:</strong> {core.esc(approval.pakgat_signer_title)}</p>
                <p><strong>الجوال:</strong> <span dir='ltr'>{core.esc(approval.pakgat_signer_phone)}</span></p>
                <p><strong>تاريخ الاعتماد:</strong> {core.fmt_dt(approval.approved_at)}</p>
                <p><strong>رقم الاتفاقية:</strong> <span dir='ltr'>{core.esc(approval.agreement_number_snapshot)}</span></p>
              </div>
            </section>
            """

    return base + review_html + approval_html


@core.app.post("/admin/merchants/{merchant_id}/contracts/{contract_id}/approve-onboarding")
def admin_approve_onboarding(
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
    try:
        onboarding.approve_signed_onboarding(db, contract)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RedirectResponse(f"/admin/merchants/{merchant_id}", status_code=303)


@core.app.post("/admin/merchants/{merchant_id}/onboarding/request-changes")
async def admin_request_onboarding_changes(
    merchant_id: int,
    request: Request,
    db: Session = Depends(core.get_db),
):
    redirect = contracts._admin_guard(request)
    if redirect:
        return redirect
    application = _application(db, merchant_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Merchant onboarding application not found")
    form = await request.form()
    note = str(form.get("note") or "").strip()
    try:
        onboarding.request_onboarding_changes(db, application, note)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RedirectResponse(f"/admin/merchants/{merchant_id}", status_code=303)


@core.app.post("/admin/merchants/{merchant_id}/onboarding/reject")
async def admin_reject_onboarding(
    merchant_id: int,
    request: Request,
    db: Session = Depends(core.get_db),
):
    redirect = contracts._admin_guard(request)
    if redirect:
        return redirect
    application = _application(db, merchant_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Merchant onboarding application not found")
    form = await request.form()
    note = str(form.get("note") or "").strip()
    try:
        onboarding.reject_onboarding(db, application, note)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RedirectResponse(f"/admin/merchants/{merchant_id}", status_code=303)


# Keep the enhanced review summary as the canonical contract summary even when
# modules are imported directly outside main.py (for example tests/workers).
contracts.merchant_contract_summary_html = merchant_contract_summary_html


__all__ = [
    "merchant_contract_summary_html",
    "admin_approve_onboarding",
    "admin_request_onboarding_changes",
    "admin_reject_onboarding",
]
