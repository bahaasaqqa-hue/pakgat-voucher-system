"""Start the real Sadq/Nafath signing journey for merchant onboarding.

This module is loaded after the core onboarding routes. It replaces only the
POST /merchant/onboarding/submit endpoint so the validated Pakgat agreement is
rendered, initiated in Sadq, and the merchant is redirected to the Nafath-
authenticated Sadq invitation. It never activates a merchant.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from app import application as core
from app import merchant_contract_pdf
from app import merchant_finance as finance
from app import merchant_onboarding as onboarding
from app import merchant_portal as portal
from app import sadq_client


SIGNING_REDIRECT_URL = "https://merchant.pakgat.com/merchant/onboarding"
SIGNING_WINDOW_DAYS = 7

# Capture the presentation layer that was already installed by
# merchant_onboarding_ui before this module is loaded.  We add only one
# state-aware override for an already-created Sadq request.
_presentation_onboarding_page = onboarding._onboarding_page


def _existing_application(db, merchant_id: int):
    return db.scalar(
        select(onboarding.MerchantOnboardingApplication)
        .where(onboarding.MerchantOnboardingApplication.merchant_id == merchant_id)
        .limit(1)
    )


def _latest_contract(db, merchant_id: int):
    return db.scalar(
        select(finance.MerchantContract)
        .where(finance.MerchantContract.merchant_id == merchant_id)
        .order_by(finance.MerchantContract.created_at.desc())
        .limit(1)
    )


def _is_sadq_pending(db, merchant: finance.Merchant) -> bool:
    application = _existing_application(db, merchant.id)
    contract = _latest_contract(db, merchant.id)
    return bool(
        (application is not None and application.status == "sadq_pending")
        or (contract is not None and contract.status == "sadq_pending")
    )


def _sadq_pending_page(db, merchant: finance.Merchant, message: str = "") -> str:
    """Render a locked status page after the signing request already exists.

    The page intentionally contains no profile/document/submit forms.  Once a
    Sadq request exists, re-submitting onboarding must never try to replace the
    existing contract or create another signing destination.
    """
    contract = _latest_contract(db, merchant.id)
    agreement_number = str(getattr(contract, "agreement_number", "") or "").strip()
    agreement_row = (
        "<div style='margin:16px 0;padding:13px 15px;border:1px solid #dce8f5;"
        "border-radius:12px;background:#f8fbff'>"
        "<span class='muted'>رقم الاتفاقية</span><br>"
        f"<strong dir='ltr'>{core.esc(agreement_number)}</strong></div>"
        if agreement_number
        else ""
    )
    notice = (
        "<div style='margin:14px 0;padding:12px 14px;border-radius:12px;"
        "background:#fff8e8;border:1px solid #f0d79c;color:#6d5317'>"
        f"{core.esc(message)}</div>"
        if message
        else ""
    )
    return portal._portal_shell(
        "متابعة التوثيق",
        f"""
        <main class='portal-wrap' style='padding:38px 0 58px'>
          <section class='portal-card' style='max-width:720px;margin:auto;padding:28px'>
            <div style='margin-bottom:15px'>
              <span class='pill'>بانتظار إكمال التحقق والتوقيع</span>
            </div>
            <h1 style='margin:0 0 10px'>تم إنشاء اتفاقية الشراكة وإرسالها للتوثيق</h1>
            <p class='muted' style='font-size:15px;line-height:1.9'>
              طلبك محفوظ والعقد قائم بالفعل. لا تحتاج إلى إعادة إدخال البيانات أو رفع
              المستندات أو إرسال الطلب مرة أخرى.
            </p>
            {agreement_row}
            {notice}
            <div style='margin:18px 0;padding:16px;border-radius:14px;background:#eef7ff;"
                 "border:1px solid #d5e9fb'>
              <strong>الخطوة الحالية</strong>
              <p class='muted' style='margin:7px 0 0'>
                أكمل التحقق من هوية ممثل المنشأة عبر نفاذ ثم التوقيع الإلكتروني من
                صفحة التوثيق التي تم فتحها لك. بعد اكتمال التوقيع ينتقل الطلب تلقائيًا
                إلى مراجعة فريق Pakgat.
              </p>
            </div>
            <a class='portal-btn' style='width:100%;margin-top:10px'
               href='/merchant/onboarding'>تحديث حالة الطلب</a>
            <a class='portal-btn portal-btn-muted' style='width:100%;margin-top:9px'
               href='/merchant/dashboard'>العودة إلى بوابة الشريك</a>
          </section>
        </main>
        """,
    )


def _sadq_aware_onboarding_page(db, merchant: finance.Merchant, message: str = "") -> str:
    if _is_sadq_pending(db, merchant):
        return _sadq_pending_page(db, merchant, message)
    return _presentation_onboarding_page(db, merchant, message)


def _contract_data(
    merchant: finance.Merchant,
    application: onboarding.MerchantOnboardingApplication,
    contract: finance.MerchantContract,
) -> merchant_contract_pdf.ContractData:
    submitted = onboarding._as_utc(application.submitted_at) or core.now_utc()
    agreement_date = submitted.astimezone(finance.RIYADH_TZ).strftime("%d / %m / %Y")
    return merchant_contract_pdf.ContractData(
        agreement_number=str(contract.agreement_number or "").strip(),
        agreement_date=agreement_date,
        legal_name=str(merchant.legal_name or "").strip(),
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


def start_sadq_signing(
    db,
    merchant: finance.Merchant,
    application: onboarding.MerchantOnboardingApplication,
    contract: finance.MerchantContract,
    *,
    client=None,
    render_pdf=None,
) -> str:
    """Create/reuse the Sadq envelope, send Nafath invitation, persist pending state."""
    if application.status != "ready_for_sadq" or contract.status != "ready_for_sadq":
        raise ValueError("الطلب غير جاهز للتوقيع عبر صادق")
    if not str(contract.agreement_number or "").strip():
        raise ValueError("رقم الاتفاقية غير موجود")

    provider = client or sadq_client.get_default_client()
    renderer = render_pdf or merchant_contract_pdf.render_contract_pdf

    # Persist provider identifiers immediately after envelope creation. If the
    # invitation call later fails, a retry reuses the same envelope instead of
    # creating duplicate agreements in Sadq.
    if not str(contract.sadq_document_id or "").strip():
        pdf_content = renderer(_contract_data(merchant, application, contract))
        envelope = provider.initiate_base64_pdf(
            pdf_content,
            f"{contract.agreement_number}.pdf",
        )
        contract.sadq_document_id = envelope.document_id
        contract.sadq_transaction_id = envelope.envelope_id
        contract.updated_at = core.now_utc()
        db.add(contract)
        db.commit()
        db.refresh(contract)

    phone = core.normalize_saudi_phone(merchant.contact_phone or "")
    if not phone:
        raise ValueError("رقم جوال ممثل المنشأة غير صالح")
    representative_name = str(application.representative_name or "").strip()
    if not representative_name:
        raise ValueError("اسم ممثل المنشأة غير موجود")

    available_to = (
        core.now_utc().astimezone(finance.RIYADH_TZ) + timedelta(days=SIGNING_WINDOW_DAYS)
    ).date().isoformat()
    invitation = provider.send_nafath_invitation(
        str(contract.sadq_document_id),
        destination_name=representative_name,
        destination_email=str(merchant.contact_email or "").strip(),
        destination_phone=f"+{phone}",
        redirect_url=SIGNING_REDIRECT_URL,
        available_to=available_to,
    )
    invitation_url = str(invitation.invitation_url or "").strip()
    if not invitation_url.startswith("https://"):
        raise ValueError("لم تُرجع صادق رابط توقيع صالح")

    now = core.now_utc()
    contract.status = "sadq_pending"
    contract.updated_at = now
    application.status = "sadq_pending"
    application.review_note = None
    application.updated_at = now
    merchant.status = "pending"
    merchant.updated_at = now
    db.add_all([contract, application, merchant])
    db.commit()
    db.refresh(contract)
    db.refresh(application)
    return invitation_url


async def merchant_onboarding_submit_to_sadq(
    request: Request,
    db=Depends(core.get_db),
):
    """Validate onboarding, initiate Sadq, then send the merchant to Sadq."""
    merchant = portal._merchant_from_request(request, db)
    if merchant is None:
        return RedirectResponse("/merchant/register", status_code=303)

    # A signing request already exists. Never call submit_onboarding() again,
    # because that path is intentionally allowed to create/prepare a contract
    # only before the first Sadq submission.
    if _is_sadq_pending(db, merchant):
        return HTMLResponse(onboarding._onboarding_page(db, merchant), status_code=200)

    form = await request.form()
    accepted = onboarding._form_value(form, "declaration") == "1"
    try:
        application, contract = onboarding.submit_onboarding(
            db,
            merchant,
            declaration_accepted=accepted,
        )
    except ValueError as exc:
        return HTMLResponse(
            onboarding._onboarding_page(db, merchant, str(exc)),
            status_code=422,
        )

    try:
        signing_url = start_sadq_signing(db, merchant, application, contract)
    except (ValueError, sadq_client.SadqError, merchant_contract_pdf.ContractRenderError):
        return HTMLResponse(
            onboarding._onboarding_page(
                db,
                merchant,
                "تعذر بدء التحقق والتوقيع الآن. حاول مرة أخرى بعد قليل.",
            ),
            status_code=502,
        )
    return RedirectResponse(signing_url, status_code=303)


def install_submit_route() -> None:
    """Replace only the legacy fail-closed onboarding submit route."""
    routes = core.app.router.routes
    removed = 0
    for route in list(routes):
        methods = getattr(route, "methods", set()) or set()
        if getattr(route, "path", "") == "/merchant/onboarding/submit" and "POST" in methods:
            routes.remove(route)
            removed += 1
    if removed != 1:
        raise RuntimeError(
            f"Expected exactly one merchant onboarding submit route, found {removed}"
        )
    core.app.add_api_route(
        "/merchant/onboarding/submit",
        merchant_onboarding_submit_to_sadq,
        methods=["POST"],
        response_class=HTMLResponse,
        name="merchant_onboarding_submit",
    )


# Expose the helper through the existing onboarding module for tests/callers and
# make the existing GET /merchant/onboarding route state-aware without replacing
# that route itself.
onboarding.start_sadq_signing = start_sadq_signing
onboarding._onboarding_page = _sadq_aware_onboarding_page


__all__ = [
    "SIGNING_REDIRECT_URL",
    "SIGNING_WINDOW_DAYS",
    "start_sadq_signing",
    "merchant_onboarding_submit_to_sadq",
    "install_submit_route",
]
