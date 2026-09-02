"""Manual merchant agreement workflow for Pakgat onboarding.

Approved flow:
1. Pakgat generates a PDF populated from the saved merchant profile.
2. Merchant downloads it, signs/stamps it, and uploads the signed PDF.
3. Pakgat reviews that PDF, signs/stamps it, and uploads the final joint PDF.
4. Merchant activation remains a separate explicit Pakgat approval action.

Sadq/Nafath modules remain in the repository for possible future use, but this
module removes them from the active merchant onboarding journey.
"""

from __future__ import annotations

import hashlib
import os
import secrets
from pathlib import Path
from typing import Optional

from fastapi import Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import application as core
from app import merchant_contract_admin_actions as admin_actions
from app import merchant_contract_pdf as contract_pdf
from app import merchant_contracts as contracts
from app import merchant_finance as finance
from app import merchant_onboarding as onboarding
from app import merchant_portal as portal

MAX_CONTRACT_BYTES = 10 * 1024 * 1024
MERCHANT_SIGNED_PREFIX = "merchant-signed-"
FINAL_SIGNED_PREFIX = "final-signed-"


def _latest_contract(db: Session, merchant_id: int) -> Optional[finance.MerchantContract]:
    return db.scalar(
        select(finance.MerchantContract)
        .where(finance.MerchantContract.merchant_id == merchant_id)
        .order_by(finance.MerchantContract.created_at.desc(), finance.MerchantContract.id.desc())
        .limit(1)
    )


def _application(db: Session, merchant_id: int) -> Optional[onboarding.MerchantOnboardingApplication]:
    return db.scalar(
        select(onboarding.MerchantOnboardingApplication)
        .where(onboarding.MerchantOnboardingApplication.merchant_id == merchant_id)
        .limit(1)
    )


def contract_data_for(
    merchant: finance.Merchant,
    application: onboarding.MerchantOnboardingApplication,
    contract: finance.MerchantContract,
) -> contract_pdf.ContractData:
    """Build the approved template data only from persisted Pakgat records."""
    created = contract.created_at or core.now_utc()
    if created.tzinfo is None:
        created = created.replace(tzinfo=finance.timezone.utc)
    agreement_date = created.astimezone(finance.RIYADH_TZ).strftime("%Y-%m-%d")
    return contract_pdf.ContractData(
        agreement_number=str(contract.agreement_number or "").strip(),
        agreement_date=agreement_date,
        legal_name=str(merchant.legal_name or merchant.display_name or "").strip(),
        commercial_registration=str(merchant.commercial_registration or "").strip(),
        activity=str(application.activity or "").strip(),
        tax_number=str(merchant.tax_number or "").strip(),
        bank_name=str(merchant.bank_name or "").strip(),
        iban=str(merchant.iban or "").strip(),
        national_address=str(application.national_address or "").strip(),
        contact_phone=str(merchant.contact_phone or "").strip(),
        contact_email=str(merchant.contact_email or "").strip(),
        website=str(application.website or "").strip(),
        representative_name=str(application.representative_name or "").strip(),
        representative_title=str(application.representative_title or "").strip(),
    )


def _validate_pdf(filename: str, content: bytes) -> bytes:
    payload = bytes(content or b"")
    if not payload:
        raise ValueError("ملف العقد فارغ")
    if len(payload) > MAX_CONTRACT_BYTES:
        raise ValueError("حجم ملف العقد يتجاوز 10MB")
    if Path(str(filename or "contract.pdf")).suffix.lower() != ".pdf":
        raise ValueError("يجب رفع العقد بصيغة PDF فقط")
    if not payload.startswith(b"%PDF"):
        raise ValueError("ملف العقد المرفوع ليس PDF صالحًا")
    return payload


def _store_contract_pdf(
    db: Session,
    merchant: finance.Merchant,
    application: onboarding.MerchantOnboardingApplication,
    contract: finance.MerchantContract,
    *,
    prefix: str,
    filename: str,
    content: bytes,
) -> onboarding.MerchantOnboardingDocument:
    payload = _validate_pdf(filename, content)
    agreement = str(contract.agreement_number or contract.id or "contract").strip()
    relative = Path(str(merchant.id)) / f"{prefix}{secrets.token_hex(18)}.pdf"
    root = onboarding._document_root()
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)

    row = onboarding.MerchantOnboardingDocument(
        application_id=application.id,
        merchant_id=merchant.id,
        original_name=f"{prefix}{agreement}.pdf",
        storage_key=relative.as_posix(),
        content_type="application/pdf",
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        created_at=core.now_utc(),
    )
    db.add(row)
    db.flush()
    return row


def latest_contract_document(
    db: Session,
    application_id: int,
    prefix: str,
) -> Optional[onboarding.MerchantOnboardingDocument]:
    return db.scalar(
        select(onboarding.MerchantOnboardingDocument)
        .where(
            onboarding.MerchantOnboardingDocument.application_id == application_id,
            onboarding.MerchantOnboardingDocument.original_name.like(f"{prefix}%"),
        )
        .order_by(
            onboarding.MerchantOnboardingDocument.created_at.desc(),
            onboarding.MerchantOnboardingDocument.id.desc(),
        )
        .limit(1)
    )


def store_merchant_signed_pdf(
    db: Session,
    merchant: finance.Merchant,
    application: onboarding.MerchantOnboardingApplication,
    contract: finance.MerchantContract,
    *,
    filename: str,
    content: bytes,
) -> onboarding.MerchantOnboardingDocument:
    if contract.merchant_id != merchant.id or application.merchant_id != merchant.id:
        raise ValueError("العقد لا يخص هذه المنشأة")
    if contract.status not in {"contract_ready", "merchant_signed"}:
        raise ValueError("العقد غير جاهز لرفع نسخة التاجر")
    row = _store_contract_pdf(
        db, merchant, application, contract,
        prefix=MERCHANT_SIGNED_PREFIX,
        filename=filename,
        content=content,
    )
    now = core.now_utc()
    contract.status = "merchant_signed"
    contract.updated_at = now
    application.status = "pending_review"
    application.review_note = None
    application.updated_at = now
    merchant.status = "pending"
    merchant.updated_at = now
    db.add_all([row, contract, application, merchant])
    db.commit()
    db.refresh(row)
    return row


def store_pakgat_final_pdf(
    db: Session,
    merchant: finance.Merchant,
    application: onboarding.MerchantOnboardingApplication,
    contract: finance.MerchantContract,
    *,
    filename: str,
    content: bytes,
) -> onboarding.MerchantOnboardingDocument:
    if contract.merchant_id != merchant.id or application.merchant_id != merchant.id:
        raise ValueError("العقد لا يخص هذه المنشأة")
    if latest_contract_document(db, application.id, MERCHANT_SIGNED_PREFIX) is None:
        raise ValueError("يجب استلام نسخة التاجر الموقعة والمختومة أولًا")
    if contract.status not in {"merchant_signed", "signed"}:
        raise ValueError("العقد ليس في مرحلة توقيع Pakgat")
    row = _store_contract_pdf(
        db, merchant, application, contract,
        prefix=FINAL_SIGNED_PREFIX,
        filename=filename,
        content=content,
    )
    now = core.now_utc()
    contract.status = "signed"
    contract.signed_at = contract.signed_at or now
    contract.signed_document_url = f"/merchant/onboarding/contract/final/{row.id}"
    contract.updated_at = now
    application.status = "pending_review"
    application.updated_at = now
    merchant.status = "pending"
    merchant.updated_at = now
    db.add_all([row, contract, application, merchant])
    db.commit()
    db.refresh(row)
    return row


def _read_document(row: onboarding.MerchantOnboardingDocument) -> bytes:
    root = onboarding._document_root().resolve()
    path = (root / row.storage_key).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=403, detail="Invalid document path")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Contract PDF not found")
    payload = path.read_bytes()
    if not payload.startswith(b"%PDF"):
        raise HTTPException(status_code=422, detail="Stored contract is not a valid PDF")
    return payload


def _pdf_response(payload: bytes, filename: str) -> Response:
    safe_name = "".join(ch for ch in str(filename or "contract.pdf") if ch.isalnum() or ch in "-_.") or "contract.pdf"
    return Response(
        content=payload,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )


# Preserve the validated existing onboarding data checks and only replace its
# external signing transition with the approved manual state transition.
_original_submit_onboarding = onboarding.submit_onboarding


def submit_onboarding_manual(db: Session, merchant: finance.Merchant, *, declaration_accepted: bool):
    application, contract = _original_submit_onboarding(
        db, merchant, declaration_accepted=declaration_accepted
    )
    if application.status == "ready_for_sadq":
        now = core.now_utc()
        application.status = "contract_ready"
        application.updated_at = now
        contract.status = "contract_ready"
        contract.updated_at = now
        merchant.status = "pending"
        merchant.updated_at = now
        db.add_all([application, contract, merchant])
        db.commit()
        db.refresh(application)
        db.refresh(contract)
    return application, contract


onboarding.submit_onboarding = submit_onboarding_manual


@core.app.get("/merchant/onboarding/contract.pdf")
def merchant_download_generated_contract(request: Request, db: Session = Depends(core.get_db)):
    merchant = portal._merchant_from_request(request, db)
    if merchant is None:
        return RedirectResponse("/merchant/register", status_code=303)
    application = _application(db, merchant.id)
    contract = _latest_contract(db, merchant.id)
    if application is None or contract is None:
        raise HTTPException(status_code=404, detail="Merchant contract not found")
    if contract.status not in {"contract_ready", "merchant_signed", "signed", "approved"}:
        raise HTTPException(status_code=409, detail="Merchant contract is not ready")
    try:
        payload = contract_pdf.render_contract_pdf(contract_data_for(merchant, application, contract))
    except contract_pdf.ContractRenderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _pdf_response(payload, f"{contract.agreement_number or 'merchant-agreement'}.pdf")


@core.app.post("/merchant/onboarding/contract/upload-signed", response_class=HTMLResponse)
async def merchant_upload_signed_contract(
    request: Request,
    signed_contract: UploadFile = File(...),
    db: Session = Depends(core.get_db),
):
    merchant = portal._merchant_from_request(request, db)
    if merchant is None:
        return RedirectResponse("/merchant/register", status_code=303)
    application = _application(db, merchant.id)
    contract = _latest_contract(db, merchant.id)
    if application is None or contract is None:
        raise HTTPException(status_code=404, detail="Merchant contract not found")
    content = await signed_contract.read(MAX_CONTRACT_BYTES + 1)
    try:
        store_merchant_signed_pdf(
            db, merchant, application, contract,
            filename=signed_contract.filename or "signed.pdf",
            content=content,
        )
    except ValueError as exc:
        return HTMLResponse(onboarding._onboarding_page(db, merchant, str(exc)), status_code=422)
    return RedirectResponse("/merchant/onboarding", status_code=303)


@core.app.get("/merchant/onboarding/contract/final/{document_id}")
def merchant_download_final_contract(
    document_id: int,
    request: Request,
    db: Session = Depends(core.get_db),
):
    merchant = portal._merchant_from_request(request, db)
    if merchant is None:
        return RedirectResponse("/merchant/register", status_code=303)
    row = db.get(onboarding.MerchantOnboardingDocument, document_id)
    if row is None or row.merchant_id != merchant.id or not row.original_name.startswith(FINAL_SIGNED_PREFIX):
        raise HTTPException(status_code=404, detail="Final contract not found")
    return _pdf_response(_read_document(row), row.original_name)


def _require_admin(request: Request) -> None:
    core.require_admin(request)


@core.app.get("/admin/merchants/{merchant_id}/contracts/{contract_id}/merchant-signed.pdf")
def admin_download_merchant_signed_contract(
    merchant_id: int,
    contract_id: int,
    request: Request,
    db: Session = Depends(core.get_db),
):
    _require_admin(request)
    contract = db.get(finance.MerchantContract, contract_id)
    application = _application(db, merchant_id)
    if contract is None or contract.merchant_id != merchant_id or application is None:
        raise HTTPException(status_code=404, detail="Merchant contract not found")
    row = latest_contract_document(db, application.id, MERCHANT_SIGNED_PREFIX)
    if row is None:
        raise HTTPException(status_code=404, detail="Merchant signed contract not found")
    return _pdf_response(_read_document(row), row.original_name)


@core.app.post("/admin/merchants/{merchant_id}/contracts/{contract_id}/upload-final")
async def admin_upload_final_contract(
    merchant_id: int,
    contract_id: int,
    request: Request,
    final_contract: UploadFile = File(...),
    db: Session = Depends(core.get_db),
):
    _require_admin(request)
    merchant = db.get(finance.Merchant, merchant_id)
    contract = db.get(finance.MerchantContract, contract_id)
    application = _application(db, merchant_id)
    if merchant is None or contract is None or contract.merchant_id != merchant_id or application is None:
        raise HTTPException(status_code=404, detail="Merchant contract not found")
    content = await final_contract.read(MAX_CONTRACT_BYTES + 1)
    try:
        store_pakgat_final_pdf(
            db, merchant, application, contract,
            filename=final_contract.filename or "final.pdf",
            content=content,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RedirectResponse(f"/admin/merchants/{merchant_id}", status_code=303)


# UI adapters are deliberately loaded after merchant_onboarding_ui. Existing
# HTML/layout stays intact; only the signing language and contract controls change.
_original_onboarding_page = onboarding._onboarding_page
_original_register_page = onboarding._register_page
_original_contract_summary = contracts.merchant_contract_summary_html


def _manual_contract_panel(db: Session, merchant: finance.Merchant) -> str:
    application = _application(db, merchant.id)
    contract = _latest_contract(db, merchant.id)
    if application is None or contract is None:
        return ""
    final_doc = latest_contract_document(db, application.id, FINAL_SIGNED_PREFIX)
    agreement = core.esc(contract.agreement_number or "—")
    if contract.status == "contract_ready":
        return f"""
        <section class='portal-card' style='padding:22px;margin-top:16px'>
          <h2 style='margin-top:0'>4. توقيع وختم عقد الشراكة</h2>
          <p class='muted'>رقم الاتفاقية: <strong dir='ltr'>{agreement}</strong></p>
          <p class='muted'>حمّل العقد المعبأ ببيانات منشأتك، وقّعه واختمه، ثم ارفع النسخة الموقعة بصيغة PDF.</p>
          <a class='portal-btn' href='/merchant/onboarding/contract.pdf'>تحميل العقد PDF</a>
          <form method='post' enctype='multipart/form-data' action='/merchant/onboarding/contract/upload-signed' style='margin-top:14px'>
            <input class='portal-input' type='file' name='signed_contract' accept='.pdf,application/pdf' required>
            <button class='portal-btn' type='submit' style='margin-top:10px'>رفع العقد الموقّع والمختوم</button>
          </form>
        </section>"""
    if final_doc is not None:
        return f"""
        <section class='portal-card' style='padding:22px;margin-top:16px'>
          <h2 style='margin-top:0'>عقد الشراكة النهائي</h2>
          <p class='muted'>تم حفظ النسخة النهائية المشتركة من اتفاقية <strong dir='ltr'>{agreement}</strong>.</p>
          <a class='portal-btn' href='/merchant/onboarding/contract/final/{final_doc.id}'>تحميل النسخة النهائية PDF</a>
        </section>"""
    if contract.status in {"merchant_signed", "signed"} or application.status == "pending_review":
        return f"""
        <section class='portal-card' style='padding:22px;margin-top:16px'>
          <h2 style='margin-top:0'>تم استلام عقدك</h2>
          <p class='muted'>استلمنا النسخة الموقعة والمختومة من اتفاقية <strong dir='ltr'>{agreement}</strong>. الطلب الآن لدى فريق Pakgat للمراجعة والتوقيع النهائي.</p>
        </section>"""
    return ""


def manual_onboarding_page(db: Session, merchant: finance.Merchant, message: str = "") -> str:
    html = _original_onboarding_page(db, merchant, message)
    replacements = {
        "جاهز للانتقال إلى صادق": "العقد جاهز للتحميل والتوقيع",
        "بانتظار إكمال التوقيع عبر صادق": "بانتظار رفع العقد الموقّع",
        "ready_for_sadq": "contract_ready",
        "sadq_pending": "contract_ready",
        "صادق": "Pakgat",
        "نفاذ": "التوقيع اليدوي",
    }
    for old, new in replacements.items():
        html = html.replace(old, new)
    panel = _manual_contract_panel(db, merchant)
    return html.replace("</main>", panel + "</main>") if "</main>" in html else html + panel


def manual_register_page(challenge_token: str = "", message: str = "") -> str:
    html = _original_register_page(challenge_token, message)
    replacements = {
        "إكمال التوثيق الإلكتروني": "إكمال عقد الشراكة",
        "يتم التحقق من هوية ممثل المنشأة عبر <strong>النفاذ الوطني الموحد (نفاذ)</strong>، وبعدها": "بعد توقيع وختم العقد ورفعه،",
        "تحقق موثوق عبر نفاذ": "عقد واضح ببيانات منشأتك",
        "عقد إلكتروني بخطوات واضحة": "تحميل، توقيع وختم، ثم رفع",
        "تراجع بياناتك ومسار الشراكة قبل الإقرار وإكمال التوثيق الإلكتروني.": "تراجع بياناتك ثم تحمّل العقد المعبأ تلقائيًا لتوقيعه وختمه.",
        "تحقق عبر نفاذ": "توقيع وختم العقد",
        "يتم التحقق من هوية ممثل المنشأة عبر النفاذ الوطني الموحد ضمن رحلة التوثيق.": "حمّل العقد، وقّعه واختمه، ثم ارفع النسخة بصيغة PDF.",
        "تحقق عبر نفاذ وأكمل التوقيع": "حمّل العقد ووقّعه واختمه",
        "أكمل التحقق من الهوية والتوقيع الإلكتروني.": "ارفع النسخة الموقعة والمختومة بصيغة PDF.",
        "بيانات منظمة، مستندات مجمعة، توثيق إلكتروني، ثم مراجعة واعتماد من فريق بكجات.": "بيانات منظمة، مستندات مجمعة، عقد واضح، ثم مراجعة واعتماد من فريق بكجات.",
        "هوية موثوقة": "عقد مشترك وواضح",
        "يتم التحقق من هوية ممثل المنشأة عبر النفاذ الوطني الموحد، بينما تبقى تفاصيل أنظمة الربط التقنية في الخلفية.": "بعد توقيع وختم التاجر للعقد، يراجعه فريق بكجات ويضيف توقيع وختم Pakgat على النسخة النهائية.",
        "✓ التحقق عبر نفاذ": "✓ توقيع وختم الطرفين",
    }
    for old, new in replacements.items():
        html = html.replace(old, new)
    return html


def manual_contract_summary_html(db: Session, merchant_id: int) -> str:
    base = _original_contract_summary(db, merchant_id)
    contract = _latest_contract(db, merchant_id)
    application = _application(db, merchant_id)
    if contract is None or application is None:
        return base
    merchant_signed = latest_contract_document(db, application.id, MERCHANT_SIGNED_PREFIX)
    final_doc = latest_contract_document(db, application.id, FINAL_SIGNED_PREFIX)
    controls = ""
    if merchant_signed is not None:
        controls += f"<p><a class='btn btn-muted' href='/admin/merchants/{merchant_id}/contracts/{contract.id}/merchant-signed.pdf'>تحميل نسخة التاجر الموقعة</a></p>"
    if merchant_signed is not None and final_doc is None:
        controls += f"""
        <form method='post' enctype='multipart/form-data' action='/admin/merchants/{merchant_id}/contracts/{contract.id}/upload-final' style='margin-top:12px'>
          <label>بعد توقيع وختم Pakgat، ارفع النسخة النهائية المشتركة PDF</label>
          <input class='input' type='file' name='final_contract' accept='.pdf,application/pdf' required>
          <button class='btn btn-blue' type='submit' style='margin-top:10px'>رفع النسخة النهائية</button>
        </form>"""
    if final_doc is not None:
        controls += "<p class='muted'>✓ تم حفظ النسخة النهائية المشتركة. الاعتماد والتفعيل يبقيان بإجراء Pakgat الصريح.</p>"
    if not controls:
        return base
    block = f"<section class='card' style='padding:18px;margin-bottom:18px'><h2>التوقيع اليدوي للعقد</h2>{controls}</section>"
    return base + block


onboarding._onboarding_page = manual_onboarding_page
onboarding._register_page = manual_register_page
contracts.merchant_contract_summary_html = manual_contract_summary_html
admin_actions.merchant_contract_summary_html = manual_contract_summary_html


__all__ = [
    "MERCHANT_SIGNED_PREFIX",
    "FINAL_SIGNED_PREFIX",
    "contract_data_for",
    "latest_contract_document",
    "store_merchant_signed_pdf",
    "store_pakgat_final_pdf",
    "submit_onboarding_manual",
]
