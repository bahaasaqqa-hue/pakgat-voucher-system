"""OTP acceptance for Pakgat merchant partnership agreements.

The merchant reviews the generated agreement and signs it with a dedicated OTP
sent to the registered merchant phone.  The OTP is separate from login OTP and
is bound to the agreement number plus a fingerprint of the rendered contract
content.  Successful OTP verification moves the application to Pakgat review;
it never activates the merchant automatically.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import DateTime, Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app import application as core
from app import merchant_contract_admin_actions as admin_actions
from app import merchant_contract_pdf as contract_pdf
from app import merchant_contracts as contracts
from app import merchant_finance as finance
from app import merchant_manual_contract as manual
from app import merchant_onboarding as onboarding
from app import merchant_portal as portal
from app.jood_outbound import _send_whatsloop_text

SIGNATURE_OTP_TTL = timedelta(minutes=5)
SIGNATURE_OTP_RESEND_COOLDOWN = timedelta(seconds=60)
SIGNATURE_OTP_MAX_ATTEMPTS = 5


class MerchantContractOtpChallenge(core.Base):
    __tablename__ = "merchant_contract_otp_challenges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    merchant_id: Mapped[int] = mapped_column(Integer, index=True)
    contract_id: Mapped[int] = mapped_column(Integer, index=True)
    destination: Mapped[str] = mapped_column(String(40), index=True)
    agreement_number_snapshot: Mapped[str] = mapped_column(String(40), index=True)
    contract_fingerprint: Mapped[str] = mapped_column(String(64))
    otp_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_ip: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    accepted_user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=core.now_utc, index=True)


def ensure_contract_otp_schema() -> None:
    MerchantContractOtpChallenge.__table__.create(core.engine, checkfirst=True)


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _signature_digest(contract_id: int, agreement_number: str, otp: str) -> str:
    secret = portal._portal_secret()
    payload = f"merchant-contract-sign:{contract_id}:{agreement_number}:{otp}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def contract_fingerprint(
    merchant: finance.Merchant,
    application: onboarding.MerchantOnboardingApplication,
    contract: finance.MerchantContract,
) -> str:
    data = manual.contract_data_for(merchant, application, contract)
    html = contract_pdf.build_contract_html(data)
    return hashlib.sha256(html.encode("utf-8")).hexdigest()


def latest_signature_challenge(db: Session, contract_id: int) -> Optional[MerchantContractOtpChallenge]:
    return db.scalar(
        select(MerchantContractOtpChallenge)
        .where(MerchantContractOtpChallenge.contract_id == contract_id)
        .order_by(MerchantContractOtpChallenge.created_at.desc(), MerchantContractOtpChallenge.id.desc())
        .limit(1)
    )


def _live_pending(challenge: Optional[MerchantContractOtpChallenge]) -> bool:
    if challenge is None or challenge.status != "pending":
        return False
    expires = _as_utc(challenge.expires_at)
    return bool(expires and expires > core.now_utc())


def _signature_message(agreement_number: str, code: str) -> str:
    return (
        f"رمز توقيع اتفاقية Pakgat رقم {agreement_number}: {code}\n"
        "باستخدام الرمز تؤكد موافقتك على الاتفاقية المعروضة في بوابة التاجر.\n"
        "الرمز صالح لمدة 5 دقائق. لا تشاركه مع أي شخص."
    )


def request_signature_otp(
    db: Session,
    merchant: finance.Merchant,
    application: onboarding.MerchantOnboardingApplication,
    contract: finance.MerchantContract,
    *,
    sender=_send_whatsloop_text,
) -> tuple[MerchantContractOtpChallenge, bool]:
    if contract.merchant_id != merchant.id or application.merchant_id != merchant.id:
        raise ValueError("العقد لا يخص هذه المنشأة")
    if contract.status != "contract_ready" or application.status != "contract_ready":
        raise ValueError("العقد غير جاهز للتوقيع")
    agreement = str(contract.agreement_number or "").strip()
    if not agreement:
        raise ValueError("رقم الاتفاقية غير موجود")
    destination = core.normalize_saudi_phone(merchant.contact_phone or "")
    if not destination:
        raise ValueError("رقم جوال التاجر غير صالح")

    now = core.now_utc()
    latest = latest_signature_challenge(db, contract.id)
    if latest is not None:
        created = _as_utc(latest.created_at)
        if created and now - created < SIGNATURE_OTP_RESEND_COOLDOWN and latest.status == "pending":
            return latest, bool(latest.sent_at)

    previous = db.scalars(
        select(MerchantContractOtpChallenge).where(
            MerchantContractOtpChallenge.contract_id == contract.id,
            MerchantContractOtpChallenge.status == "pending",
        )
    ).all()
    for old in previous:
        old.status = "expired"

    code = f"{secrets.randbelow(1_000_000):06d}"
    challenge = MerchantContractOtpChallenge(
        merchant_id=merchant.id,
        contract_id=contract.id,
        destination=destination,
        agreement_number_snapshot=agreement,
        contract_fingerprint=contract_fingerprint(merchant, application, contract),
        otp_hash=_signature_digest(contract.id, agreement, code),
        status="pending",
        attempt_count=0,
        expires_at=now + SIGNATURE_OTP_TTL,
        created_at=now,
    )
    db.add(challenge)
    db.commit()
    db.refresh(challenge)

    delivered, _summary = sender(destination, _signature_message(agreement, code))
    if delivered:
        challenge.sent_at = core.now_utc()
    else:
        challenge.status = "failed"
    db.add(challenge)
    db.commit()
    db.refresh(challenge)
    return challenge, bool(delivered)


def verify_signature_otp(
    db: Session,
    merchant: finance.Merchant,
    application: onboarding.MerchantOnboardingApplication,
    contract: finance.MerchantContract,
    otp: str,
    *,
    ip_address: str = "",
    user_agent: str = "",
) -> bool:
    if contract.merchant_id != merchant.id or application.merchant_id != merchant.id:
        return False
    if contract.status != "contract_ready" or application.status != "contract_ready":
        return False
    challenge = latest_signature_challenge(db, contract.id)
    if challenge is None or challenge.status != "pending":
        return False

    now = core.now_utc()
    expires = _as_utc(challenge.expires_at)
    if expires is None or expires <= now:
        challenge.status = "expired"
        db.commit()
        return False
    if int(challenge.attempt_count or 0) >= SIGNATURE_OTP_MAX_ATTEMPTS:
        challenge.status = "failed"
        db.commit()
        return False
    if challenge.agreement_number_snapshot != str(contract.agreement_number or "").strip():
        challenge.status = "failed"
        db.commit()
        return False
    if challenge.contract_fingerprint != contract_fingerprint(merchant, application, contract):
        challenge.status = "failed"
        db.commit()
        return False

    supplied = str(otp or "").strip()
    expected = _signature_digest(contract.id, challenge.agreement_number_snapshot, supplied)
    if not hmac.compare_digest(expected, challenge.otp_hash):
        challenge.attempt_count = int(challenge.attempt_count or 0) + 1
        if challenge.attempt_count >= SIGNATURE_OTP_MAX_ATTEMPTS:
            challenge.status = "failed"
        db.add(challenge)
        db.commit()
        return False

    challenge.status = "used"
    challenge.accepted_at = now
    challenge.accepted_ip = str(ip_address or "")[:100] or None
    challenge.accepted_user_agent = str(user_agent or "")[:1000] or None
    contract.status = "signed"
    contract.signed_at = now
    contract.updated_at = now
    application.status = "pending_review"
    application.review_note = None
    application.updated_at = now
    merchant.status = "pending"
    merchant.updated_at = now
    db.add_all([challenge, contract, application, merchant])
    db.commit()
    return True


def _merchant_context(request: Request, db: Session):
    merchant = portal._merchant_from_request(request, db)
    if merchant is None:
        return None, None, None
    application = manual._application(db, merchant.id)
    contract = manual._latest_contract(db, merchant.id)
    return merchant, application, contract


@core.app.post("/merchant/onboarding/contract/request-signature-otp", response_class=HTMLResponse)
async def merchant_request_contract_signature_otp(request: Request, db: Session = Depends(core.get_db)):
    merchant, application, contract = _merchant_context(request, db)
    if merchant is None:
        return RedirectResponse("/merchant/register", status_code=303)
    if application is None or contract is None:
        raise HTTPException(status_code=404, detail="Merchant contract not found")
    form = await request.form()
    if str(form.get("accepted_terms") or "") != "1":
        return HTMLResponse(onboarding._onboarding_page(db, merchant, "يجب الموافقة على الاتفاقية قبل إرسال رمز التوقيع"), status_code=422)
    try:
        _challenge, delivered = request_signature_otp(db, merchant, application, contract)
    except ValueError as exc:
        return HTMLResponse(onboarding._onboarding_page(db, merchant, str(exc)), status_code=422)
    message = "تم إرسال رمز توقيع الاتفاقية إلى رقم الجوال المسجل" if delivered else "تعذر إرسال رمز التوقيع، حاول مرة أخرى"
    return HTMLResponse(onboarding._onboarding_page(db, merchant, message), status_code=200 if delivered else 503)


@core.app.post("/merchant/onboarding/contract/confirm-signature-otp", response_class=HTMLResponse)
async def merchant_confirm_contract_signature_otp(request: Request, db: Session = Depends(core.get_db)):
    merchant, application, contract = _merchant_context(request, db)
    if merchant is None:
        return RedirectResponse("/merchant/register", status_code=303)
    if application is None or contract is None:
        raise HTTPException(status_code=404, detail="Merchant contract not found")
    form = await request.form()
    code = str(form.get("otp") or "").strip()
    accepted = verify_signature_otp(
        db,
        merchant,
        application,
        contract,
        code,
        ip_address=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent", ""),
    )
    if not accepted:
        return HTMLResponse(onboarding._onboarding_page(db, merchant, "رمز التوقيع غير صحيح أو منتهي"), status_code=422)
    return RedirectResponse("/merchant/onboarding", status_code=303)


_previous_onboarding_page = onboarding._onboarding_page
_previous_register_page = onboarding._register_page
_previous_contract_summary = contracts.merchant_contract_summary_html


def _remove_old_manual_panel(html: str) -> str:
    titles = ("4. توقيع وختم عقد الشراكة", "تم استلام عقدك", "عقد الشراكة النهائي")
    for title in titles:
        pattern = rf"<section class='portal-card' style='padding:22px;margin-top:16px'>\s*<h2 style='margin-top:0'>{re.escape(title)}</h2>.*?</section>"
        html = re.sub(pattern, "", html, flags=re.S)
    return html


def _otp_panel(db: Session, merchant: finance.Merchant) -> str:
    application = manual._application(db, merchant.id)
    contract = manual._latest_contract(db, merchant.id)
    if application is None or contract is None:
        return ""
    agreement = core.esc(contract.agreement_number or "—")
    challenge = latest_signature_challenge(db, contract.id)
    if contract.status == "contract_ready" and application.status == "contract_ready":
        verify_form = ""
        if _live_pending(challenge):
            verify_form = """
            <div style='margin-top:14px;padding:14px;border:1px solid #c9d8f5;border-radius:12px;background:#f6f9ff'>
              <p style='margin-top:0'><strong>تم إرسال رمز التوقيع إلى رقم الجوال المسجل.</strong></p>
              <form method='post' action='/merchant/onboarding/contract/confirm-signature-otp'>
                <input class='portal-input' name='otp' inputmode='numeric' autocomplete='one-time-code' maxlength='6' placeholder='أدخل رمز التحقق المكون من 6 أرقام' required>
                <button class='portal-btn' type='submit' style='margin-top:10px'>تأكيد وتوقيع الاتفاقية</button>
              </form>
            </div>"""
        return f"""
        <section class='portal-card' style='padding:22px;margin-top:16px'>
          <h2 style='margin-top:0'>4. مراجعة وتوقيع عقد الشراكة</h2>
          <p class='muted'>رقم الاتفاقية: <strong dir='ltr'>{agreement}</strong></p>
          <p>راجع الاتفاقية. لا تحتاج إلى طباعتها أو توقيعها أو ختمها ورفعها.</p>
          <p><a class='portal-btn' href='/merchant/onboarding/contract.pdf'>عرض / تحميل العقد PDF (اختياري)</a></p>
          <form method='post' action='/merchant/onboarding/contract/request-signature-otp' style='margin-top:14px'>
            <label style='display:flex;gap:8px;align-items:flex-start'>
              <input type='checkbox' name='accepted_terms' value='1' required style='margin-top:5px'>
              <span>أقر بأنني قرأت اتفاقية الشراكة رقم <strong dir='ltr'>{agreement}</strong> وأوافق على جميع بنودها، وأرغب بتوقيعها إلكترونياً عبر رمز تحقق يرسل إلى رقم الجوال المسجل.</span>
            </label>
            <button class='portal-btn' type='submit' style='margin-top:12px'>إرسال رمز توقيع العقد</button>
          </form>
          {verify_form}
        </section>"""
    if contract.status in {"signed", "approved"} or application.status in {"pending_review", "approved"}:
        used = challenge if challenge and challenge.status == "used" else None
        when = core.fmt_dt(used.accepted_at) if used and used.accepted_at else "—"
        state = "تم اعتماد التاجر من Pakgat" if application.status == "approved" else "تم توقيع الاتفاقية إلكترونياً، والطلب الآن قيد مراجعة Pakgat"
        return f"""
        <section class='portal-card' style='padding:22px;margin-top:16px'>
          <h2 style='margin-top:0'>حالة اتفاقية الشراكة</h2>
          <p><strong>{state}</strong></p>
          <p class='muted'>رقم الاتفاقية: <strong dir='ltr'>{agreement}</strong> &nbsp; | &nbsp; وقت موافقة التاجر: {core.esc(when)}</p>
          <a class='portal-btn' href='/merchant/onboarding/contract.pdf'>تحميل نسخة العقد PDF</a>
        </section>"""
    return ""


def otp_onboarding_page(db: Session, merchant: finance.Merchant, message: str = "") -> str:
    html = _remove_old_manual_panel(_previous_onboarding_page(db, merchant, message))
    panel = _otp_panel(db, merchant)
    return html.replace("</main>", panel + "</main>") if "</main>" in html else html + panel


def otp_register_page(challenge_token: str = "", message: str = "") -> str:
    html = _previous_register_page(challenge_token, message)
    replacements = {
        "بعد توقيع وختم العقد ورفعه،": "بعد مراجعة العقد وتأكيده برمز تحقق مستقل،",
        "تحميل، توقيع وختم، ثم رفع": "مراجعة العقد ثم توقيعه برمز OTP",
        "تراجع بياناتك ثم تحمّل العقد المعبأ تلقائيًا لتوقيعه وختمه.": "تراجع بياناتك والعقد ثم تؤكد موافقتك برمز تحقق يرسل إلى جوالك.",
        "توقيع وختم العقد": "توقيع العقد برمز OTP",
        "حمّل العقد، وقّعه واختمه، ثم ارفع النسخة بصيغة PDF.": "راجع العقد ثم أكد موافقتك برمز OTP مستقل يرسل إلى رقم الجوال المسجل.",
        "حمّل العقد ووقّعه واختمه": "راجع العقد ووقّعه برمز OTP",
        "ارفع النسخة الموقعة والمختومة بصيغة PDF.": "أدخل رمز التحقق لتأكيد توقيع الاتفاقية.",
        "✓ توقيع وختم الطرفين": "✓ توقيع التاجر برمز OTP",
    }
    for old, new in replacements.items():
        html = html.replace(old, new)
    return html


def otp_contract_summary_html(db: Session, merchant_id: int) -> str:
    base = _previous_contract_summary(db, merchant_id)
    contract = manual._latest_contract(db, merchant_id)
    if contract is None:
        return base
    challenge = latest_signature_challenge(db, contract.id)
    if challenge is None or challenge.status != "used":
        return base
    return base + f"""
    <section class='card' style='padding:18px;margin-bottom:18px'>
      <h2>توقيع التاجر الإلكتروني</h2>
      <p><strong>الحالة:</strong> تم توقيع الاتفاقية عبر OTP</p>
      <p><strong>رقم الاتفاقية:</strong> <span dir='ltr'>{core.esc(challenge.agreement_number_snapshot)}</span></p>
      <p><strong>رقم الجوال:</strong> <span dir='ltr'>{core.esc(challenge.destination)}</span></p>
      <p><strong>وقت الموافقة:</strong> {core.esc(core.fmt_dt(challenge.accepted_at))}</p>
      <p class='muted'>بصمة نسخة الاتفاقية: <span dir='ltr'>{core.esc(challenge.contract_fingerprint)}</span></p>
    </section>"""


onboarding._onboarding_page = otp_onboarding_page
onboarding._register_page = otp_register_page
contracts.merchant_contract_summary_html = otp_contract_summary_html
admin_actions.merchant_contract_summary_html = otp_contract_summary_html


__all__ = [
    "MerchantContractOtpChallenge",
    "ensure_contract_otp_schema",
    "latest_signature_challenge",
    "request_signature_otp",
    "verify_signature_otp",
    "contract_fingerprint",
]
