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

from app import application as core
from app import merchant_contract_pdf
from app import merchant_finance as finance
from app import merchant_onboarding as onboarding
from app import merchant_portal as portal
from app import sadq_client


SIGNING_REDIRECT_URL = "https://merchant.pakgat.com/merchant/onboarding"
SIGNING_WINDOW_DAYS = 7


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
                "تعذر بدء التحقق والتوقيع عبر صادق الآن. حاول مرة أخرى بعد قليل.",
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


# Expose the helper through the existing onboarding module for tests and callers.
onboarding.start_sadq_signing = start_sadq_signing


__all__ = [
    "SIGNING_REDIRECT_URL",
    "SIGNING_WINDOW_DAYS",
    "start_sadq_signing",
    "merchant_onboarding_submit_to_sadq",
    "install_submit_route",
]
