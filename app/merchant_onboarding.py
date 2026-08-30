"""Self-service merchant onboarding for Pakgat.

Flow: phone verification -> establishment profile -> open multi-document upload
-> declaration -> Sadq signing -> Pakgat review.  Sadq signing never activates a
merchant; activation is an explicit Pakgat review decision.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import DateTime, Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app import application as core
from app import merchant_contracts as contracts
from app import merchant_finance as finance
from app import merchant_portal as portal
from app.jood_outbound import _send_whatsloop_text


REGISTRATION_OTP_TTL = timedelta(minutes=5)
REGISTRATION_RESEND_COOLDOWN = timedelta(seconds=60)
REGISTRATION_MAX_ATTEMPTS = 5
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
ALLOWED_DOCUMENT_TYPES = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


class MerchantRegistrationOtpChallenge(core.Base):
    __tablename__ = "merchant_registration_otp_challenges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    challenge_token: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    destination: Mapped[str] = mapped_column(String(40), index=True)
    otp_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=core.now_utc, index=True)


class MerchantOnboardingApplication(core.Base):
    __tablename__ = "merchant_onboarding_applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    merchant_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(40), default="profile", index=True)
    activity: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    national_address: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    website: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    representative_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    representative_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    declaration_accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=core.now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=core.now_utc)


class MerchantOnboardingDocument(core.Base):
    __tablename__ = "merchant_onboarding_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[int] = mapped_column(Integer, index=True)
    merchant_id: Mapped[int] = mapped_column(Integer, index=True)
    original_name: Mapped[str] = mapped_column(String(500))
    storage_key: Mapped[str] = mapped_column(String(700), unique=True)
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=core.now_utc)


ONBOARDING_TABLES = [
    MerchantRegistrationOtpChallenge.__table__,
    MerchantOnboardingApplication.__table__,
    MerchantOnboardingDocument.__table__,
]


def ensure_merchant_onboarding_schema() -> None:
    core.Base.metadata.create_all(bind=core.engine, tables=ONBOARDING_TABLES)


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _registration_digest(challenge_token: str, otp: str) -> str:
    secret = portal._portal_secret()
    payload = f"merchant-register:{challenge_token}:{otp}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def _registration_message(code: str) -> str:
    return (
        f"رمز تسجيل منشأتك في Pakgat: {code}\n"
        "الرمز صالح لمدة 5 دقائق.\n"
        "لا تشارك الرمز مع أي شخص."
    )


def request_registration_otp(db: Session, phone: str) -> tuple[Optional[str], bool]:
    """Send OTP to a new or existing establishment phone without creating a merchant yet."""
    portal._portal_secret()
    destination = core.normalize_saudi_phone(phone or "")
    if not destination:
        return None, False

    now = core.now_utc()
    latest = db.scalar(
        select(MerchantRegistrationOtpChallenge)
        .where(MerchantRegistrationOtpChallenge.destination == destination)
        .order_by(MerchantRegistrationOtpChallenge.created_at.desc())
        .limit(1)
    )
    if latest is not None:
        created = _as_utc(latest.created_at)
        if created and now - created < REGISTRATION_RESEND_COOLDOWN:
            return latest.challenge_token, False

    previous = db.scalars(
        select(MerchantRegistrationOtpChallenge).where(
            MerchantRegistrationOtpChallenge.destination == destination,
            MerchantRegistrationOtpChallenge.status == "pending",
        )
    ).all()
    for old in previous:
        old.status = "expired"

    challenge_token = secrets.token_urlsafe(32)
    code = f"{secrets.randbelow(1_000_000):06d}"
    challenge = MerchantRegistrationOtpChallenge(
        challenge_token=challenge_token,
        destination=destination,
        otp_hash=_registration_digest(challenge_token, code),
        status="pending",
        attempt_count=0,
        expires_at=now + REGISTRATION_OTP_TTL,
        created_at=now,
    )
    db.add(challenge)
    db.commit()

    delivered, _summary = _send_whatsloop_text(destination, _registration_message(code))
    if delivered:
        challenge.sent_at = core.now_utc()
    else:
        challenge.status = "failed"
    db.commit()
    db.refresh(challenge)
    return challenge_token, bool(delivered)


def _merchant_by_normalized_phone(db: Session, phone: str) -> Optional[finance.Merchant]:
    merchants = db.scalars(select(finance.Merchant).where(finance.Merchant.contact_phone.is_not(None))).all()
    for merchant in merchants:
        if core.normalize_saudi_phone(merchant.contact_phone or "") == phone:
            return merchant
    return None


def _get_or_create_application(db: Session, merchant: finance.Merchant) -> MerchantOnboardingApplication:
    application = db.scalar(
        select(MerchantOnboardingApplication)
        .where(MerchantOnboardingApplication.merchant_id == merchant.id)
        .limit(1)
    )
    if application is None:
        now = core.now_utc()
        application = MerchantOnboardingApplication(
            merchant_id=merchant.id,
            status="profile",
            created_at=now,
            updated_at=now,
        )
        db.add(application)
        db.commit()
        db.refresh(application)
    return application


def verify_registration_otp(db: Session, challenge_token: str, otp: str) -> Optional[int]:
    portal._portal_secret()
    challenge = db.scalar(
        select(MerchantRegistrationOtpChallenge)
        .where(MerchantRegistrationOtpChallenge.challenge_token == str(challenge_token or "").strip())
        .limit(1)
    )
    if challenge is None or challenge.status != "pending":
        return None
    now = core.now_utc()
    expires = _as_utc(challenge.expires_at)
    if expires is None or expires <= now:
        challenge.status = "expired"
        db.commit()
        return None
    if int(challenge.attempt_count or 0) >= REGISTRATION_MAX_ATTEMPTS:
        challenge.status = "failed"
        db.commit()
        return None

    expected = _registration_digest(challenge.challenge_token, str(otp or "").strip())
    if not hmac.compare_digest(expected, challenge.otp_hash):
        challenge.attempt_count = int(challenge.attempt_count or 0) + 1
        if challenge.attempt_count >= REGISTRATION_MAX_ATTEMPTS:
            challenge.status = "failed"
        db.commit()
        return None

    merchant = _merchant_by_normalized_phone(db, challenge.destination)
    if merchant is None:
        merchant = finance.Merchant(
            code=finance._new_merchant_code(db),
            display_name="منشأة جديدة",
            contact_phone=challenge.destination,
            status="pending",
            created_at=now,
            updated_at=now,
        )
        db.add(merchant)
        db.flush()
    elif merchant.status in {"rejected", "suspended"}:
        challenge.status = "failed"
        db.commit()
        return None

    _get_or_create_application(db, merchant)
    challenge.status = "used"
    challenge.used_at = now
    db.add(challenge)
    db.commit()
    return merchant.id


def save_onboarding_profile(
    db: Session,
    merchant: finance.Merchant,
    *,
    display_name: str,
    legal_name: str,
    commercial_registration: str,
    activity: str,
    tax_number: str,
    bank_name: str,
    iban: str,
    national_address: str,
    contact_email: str,
    website: str,
    representative_name: str,
    representative_title: str,
) -> MerchantOnboardingApplication:
    required = {
        "display_name": display_name,
        "legal_name": legal_name,
        "commercial_registration": commercial_registration,
        "activity": activity,
        "tax_number": tax_number,
        "bank_name": bank_name,
        "iban": iban,
        "national_address": national_address,
        "contact_email": contact_email,
        "representative_name": representative_name,
        "representative_title": representative_title,
    }
    if any(not str(value or "").strip() for value in required.values()):
        raise ValueError("جميع بيانات المنشأة الأساسية مطلوبة")

    application = _get_or_create_application(db, merchant)
    merchant.display_name = str(display_name).strip()
    merchant.legal_name = str(legal_name).strip()
    merchant.commercial_registration = str(commercial_registration).strip()
    merchant.tax_number = str(tax_number).strip()
    merchant.bank_name = str(bank_name).strip()
    merchant.iban = str(iban).strip().replace(" ", "").upper()
    merchant.contact_email = str(contact_email).strip()
    merchant.updated_at = core.now_utc()

    application.activity = str(activity).strip()
    application.national_address = str(national_address).strip()
    application.website = str(website or "").strip() or None
    application.representative_name = str(representative_name).strip()
    application.representative_title = str(representative_title).strip()
    application.status = "documents"
    application.review_note = None
    application.updated_at = core.now_utc()
    db.add_all([merchant, application])
    db.commit()
    db.refresh(application)
    return application


def _document_root() -> Path:
    return Path(
        os.getenv(
            "MERCHANT_DOCUMENT_ROOT",
            "/var/lib/pakgat/merchant-documents",
        )
    )


def store_onboarding_document(
    db: Session,
    merchant: finance.Merchant,
    *,
    filename: str,
    content_type: str,
    content: bytes,
) -> MerchantOnboardingDocument:
    application = _get_or_create_application(db, merchant)
    media_type = str(content_type or "").split(";", 1)[0].strip().lower()
    if media_type not in ALLOWED_DOCUMENT_TYPES:
        raise ValueError("يسمح فقط بملفات PDF أو الصور JPG/PNG/WEBP")
    payload = bytes(content or b"")
    if not payload:
        raise ValueError("الملف فارغ")
    if len(payload) > MAX_DOCUMENT_BYTES:
        raise ValueError("حجم الملف يتجاوز 10MB")

    original_name = Path(str(filename or "document")).name[:500] or "document"
    extension = ALLOWED_DOCUMENT_TYPES[media_type]
    relative = Path(str(merchant.id)) / f"{secrets.token_hex(18)}{extension}"
    root = _document_root()
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)

    row = MerchantOnboardingDocument(
        application_id=application.id,
        merchant_id=merchant.id,
        original_name=original_name,
        storage_key=relative.as_posix(),
        content_type=media_type,
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        created_at=core.now_utc(),
    )
    application.status = "documents"
    application.updated_at = core.now_utc()
    db.add_all([row, application])
    db.commit()
    db.refresh(row)
    return row


def submit_onboarding(
    db: Session,
    merchant: finance.Merchant,
    *,
    declaration_accepted: bool,
) -> tuple[MerchantOnboardingApplication, finance.MerchantContract]:
    application = _get_or_create_application(db, merchant)
    if not declaration_accepted:
        raise ValueError("يجب الموافقة على إقرار صحة البيانات والمستندات")
    documents = db.scalar(
        select(MerchantOnboardingDocument.id)
        .where(MerchantOnboardingDocument.application_id == application.id)
        .limit(1)
    )
    if documents is None:
        raise ValueError("يجب رفع مستند رسمي واحد على الأقل")
    profile_values = [
        merchant.display_name,
        merchant.legal_name,
        merchant.commercial_registration,
        merchant.tax_number,
        merchant.bank_name,
        merchant.iban,
        merchant.contact_email,
        application.activity,
        application.national_address,
        application.representative_name,
        application.representative_title,
    ]
    if any(not str(value or "").strip() for value in profile_values):
        raise ValueError("بيانات المنشأة غير مكتملة")

    contract = db.scalar(
        select(finance.MerchantContract)
        .where(finance.MerchantContract.merchant_id == merchant.id)
        .order_by(finance.MerchantContract.created_at.desc())
        .limit(1)
    )
    now = core.now_utc()
    if contract is None:
        contract = finance.MerchantContract(
            merchant_id=merchant.id,
            agreement_number=finance.next_agreement_number(db, now),
            status="ready_for_sadq",
            created_at=now,
            updated_at=now,
        )
        db.add(contract)
    elif contract.status in {"draft", "ready_for_sadq"}:
        if not contract.agreement_number:
            contract.agreement_number = finance.next_agreement_number(db, now)
        contract.status = "ready_for_sadq"
        contract.updated_at = now
    else:
        raise ValueError("يوجد عقد قائم لا يمكن استبداله من التسجيل")

    application.declaration_accepted_at = now
    application.submitted_at = now
    application.status = "ready_for_sadq"
    application.review_note = None
    application.updated_at = now
    merchant.status = "pending"
    merchant.updated_at = now
    db.add_all([application, merchant, contract])
    db.commit()
    db.refresh(application)
    db.refresh(contract)
    return application, contract


def mark_sadq_signed_for_review(db: Session, contract: finance.MerchantContract) -> MerchantOnboardingApplication:
    application = db.scalar(
        select(MerchantOnboardingApplication)
        .where(MerchantOnboardingApplication.merchant_id == contract.merchant_id)
        .limit(1)
    )
    if application is None:
        raise ValueError("طلب تسجيل التاجر غير موجود")
    now = core.now_utc()
    contract.status = "signed"
    if contract.signed_at is None:
        contract.signed_at = now
    contract.updated_at = now
    application.status = "pending_review"
    application.updated_at = now
    merchant = db.get(finance.Merchant, contract.merchant_id)
    if merchant is not None:
        merchant.status = "pending"
        merchant.updated_at = now
        db.add(merchant)
    db.add_all([contract, application])
    db.commit()
    db.refresh(application)
    return application


def approve_signed_onboarding(db: Session, contract: finance.MerchantContract) -> contracts.MerchantContractApproval:
    if contract.status not in {"signed", "approved"}:
        raise ValueError("لا يمكن اعتماد التاجر قبل اكتمال توقيع صادق")
    merchant = db.get(finance.Merchant, contract.merchant_id)
    if merchant is None:
        raise ValueError("التاجر غير موجود")
    application = db.scalar(
        select(MerchantOnboardingApplication)
        .where(MerchantOnboardingApplication.merchant_id == merchant.id)
        .limit(1)
    )
    if application is None:
        raise ValueError("طلب التسجيل غير موجود")

    approval = db.scalar(
        select(contracts.MerchantContractApproval)
        .where(contracts.MerchantContractApproval.merchant_contract_id == contract.id)
        .limit(1)
    )
    if approval is None:
        now = core.now_utc()
        if not contract.agreement_number:
            contract.agreement_number = finance.next_agreement_number(db, now)
        approval = contracts.MerchantContractApproval(
            merchant_contract_id=contract.id,
            merchant_id=merchant.id,
            agreement_number_snapshot=contract.agreement_number,
            approved_at=now,
            pakgat_signer_name=contracts.PAKGAT_CONTRACT_SIGNER_NAME,
            pakgat_signer_title=contracts.PAKGAT_CONTRACT_SIGNER_TITLE,
            pakgat_signer_phone=contracts.PAKGAT_CONTRACT_SIGNER_PHONE,
            merchant_snapshot_json=contracts._merchant_approval_snapshot(merchant),
            template_version=contracts.CONTRACT_TEMPLATE_VERSION,
            created_at=now,
        )
        db.add(approval)
    merchant.status = "active"
    merchant.updated_at = core.now_utc()
    contract.status = "approved"
    contract.updated_at = core.now_utc()
    application.status = "approved"
    application.review_note = None
    application.updated_at = core.now_utc()
    db.add_all([merchant, contract, application])
    db.commit()
    db.refresh(approval)
    return approval


def request_onboarding_changes(
    db: Session,
    application: MerchantOnboardingApplication,
    note: str,
) -> MerchantOnboardingApplication:
    message = str(note or "").strip()
    if not message:
        raise ValueError("سبب طلب الاستكمال مطلوب")
    merchant = db.get(finance.Merchant, application.merchant_id)
    application.status = "changes_requested"
    application.review_note = message
    application.updated_at = core.now_utc()
    if merchant is not None:
        merchant.status = "pending"
        merchant.updated_at = core.now_utc()
        db.add(merchant)
    db.add(application)
    db.commit()
    db.refresh(application)
    return application


def reject_onboarding(
    db: Session,
    application: MerchantOnboardingApplication,
    note: str,
) -> MerchantOnboardingApplication:
    message = str(note or "").strip()
    if not message:
        raise ValueError("سبب الرفض مطلوب")
    merchant = db.get(finance.Merchant, application.merchant_id)
    application.status = "rejected"
    application.review_note = message
    application.updated_at = core.now_utc()
    if merchant is not None:
        merchant.status = "rejected"
        merchant.updated_at = core.now_utc()
        db.add(merchant)
    db.add(application)
    db.commit()
    db.refresh(application)
    return application


def _form_value(form, name: str) -> str:
    value = form.get(name)
    return str(value or "").strip()


def _register_page(challenge_token: str = "", message: str = "") -> str:
    notice = f"<p class='muted'>{core.esc(message)}</p>" if message else ""
    if challenge_token:
        form = f"""
        <form method='post' action='/merchant/register/verify'>
          <input type='hidden' name='challenge_token' value='{core.esc(challenge_token)}'>
          <label style='font-weight:800'>رمز التحقق</label>
          <input class='portal-input' name='otp' dir='ltr' inputmode='numeric' minlength='6' maxlength='6' required>
          <button class='portal-btn' style='width:100%;margin-top:14px'>تحقق وابدأ التسجيل</button>
        </form>"""
    else:
        form = """
        <form method='post' action='/merchant/register/request'>
          <label style='font-weight:800'>رقم جوال ممثل المنشأة</label>
          <input class='portal-input' name='phone' dir='ltr' inputmode='tel' required>
          <button class='portal-btn' style='width:100%;margin-top:14px'>إرسال رمز التحقق</button>
        </form>"""
    return portal._portal_shell(
        "تسجيل شريك جديد",
        f"""<main class='portal-wrap' style='padding:44px 0'>
        <section class='portal-card' style='max-width:560px;margin:auto;padding:26px'>
          <h1 style='margin-top:0'>تسجيل منشأة شريكة</h1>
          <p class='muted'>تحقق من رقم الجوال، ثم أكمل بيانات المنشأة والمستندات والتوقيع عبر صادق.</p>
          {notice}{form}
          <a class='portal-btn portal-btn-muted' style='width:100%;margin-top:9px' href='/merchant'>لدي حساب بالفعل</a>
        </section></main>""",
    )


def _onboarding_page(db: Session, merchant: finance.Merchant, message: str = "") -> str:
    application = _get_or_create_application(db, merchant)
    documents = db.scalars(
        select(MerchantOnboardingDocument)
        .where(MerchantOnboardingDocument.application_id == application.id)
        .order_by(MerchantOnboardingDocument.created_at.asc())
    ).all()
    doc_rows = "".join(
        f"<li>{core.esc(doc.original_name)} <span class='muted'>({doc.size_bytes // 1024} KB)</span></li>"
        for doc in documents
    ) or "<li class='muted'>لم يتم رفع مستندات بعد.</li>"
    notice = f"<p class='muted'>{core.esc(message)}</p>" if message else ""
    status_text = {
        "profile": "أكمل بيانات المنشأة",
        "documents": "أكمل المستندات والإقرار",
        "ready_for_sadq": "جاهز للانتقال إلى صادق",
        "sadq_pending": "بانتظار إكمال التوقيع عبر صادق",
        "pending_review": "بانتظار مراجعة Pakgat",
        "changes_requested": "مطلوب استكمال بيانات أو مستندات",
        "approved": "تم اعتماد المنشأة",
        "rejected": "تم رفض الطلب",
    }.get(application.status, application.status)
    review = f"<p><strong>ملاحظة المراجعة:</strong> {core.esc(application.review_note)}</p>" if application.review_note else ""
    return portal._portal_shell(
        "تسجيل المنشأة",
        f"""
        <main class='portal-wrap' style='padding:30px 0 50px'>
          <div style='margin-bottom:16px'><span class='pill'>{core.esc(status_text)}</span></div>
          {notice}{review}
          <section class='portal-card' style='padding:22px;margin-bottom:16px'>
            <h2 style='margin-top:0'>1. بيانات المنشأة</h2>
            <form class='grid grid-two' style='grid-template-columns:1fr 1fr' method='post' action='/merchant/onboarding/profile'>
              <input class='portal-input' name='display_name' placeholder='الاسم التجاري' value='{core.esc(merchant.display_name if merchant.display_name != "منشأة جديدة" else "")}' required>
              <input class='portal-input' name='legal_name' placeholder='الاسم القانوني للمنشأة' value='{core.esc(merchant.legal_name or "")}' required>
              <input class='portal-input' name='commercial_registration' placeholder='السجل التجاري / الرقم الموحد' value='{core.esc(merchant.commercial_registration or "")}' required>
              <input class='portal-input' name='activity' placeholder='النشاط' value='{core.esc(application.activity or "")}' required>
              <input class='portal-input' name='tax_number' placeholder='الرقم الضريبي' value='{core.esc(merchant.tax_number or "")}' required>
              <input class='portal-input' name='bank_name' placeholder='اسم البنك' value='{core.esc(merchant.bank_name or "")}' required>
              <input class='portal-input' name='iban' dir='ltr' placeholder='IBAN' value='{core.esc(merchant.iban or "")}' required>
              <input class='portal-input' name='national_address' placeholder='العنوان الوطني' value='{core.esc(application.national_address or "")}' required>
              <input class='portal-input' name='contact_email' type='email' dir='ltr' placeholder='البريد الإلكتروني' value='{core.esc(merchant.contact_email or "")}' required>
              <input class='portal-input' name='website' dir='ltr' placeholder='الموقع الإلكتروني - اختياري' value='{core.esc(application.website or "")}' >
              <input class='portal-input' name='representative_name' placeholder='اسم ممثل المنشأة' value='{core.esc(application.representative_name or "")}' required>
              <input class='portal-input' name='representative_title' placeholder='صفة ممثل المنشأة' value='{core.esc(application.representative_title or "")}' required>
              <button class='portal-btn' type='submit' style='grid-column:1/-1'>حفظ البيانات</button>
            </form>
          </section>
          <section class='portal-card' style='padding:22px;margin-bottom:16px'>
            <h2 style='margin-top:0'>2. المستندات الرسمية للمنشأة</h2>
            <p class='muted'>ارفع جميع المستندات الرسمية المتوفرة للمنشأة، مثل: السجل التجاري، شهادة الرقم الضريبي، العنوان الوطني، شهادة أو خطاب الآيبان/الحساب البنكي، وأي تراخيص أو شهادات رسمية أخرى تخص المنشأة.</p>
            <form method='post' enctype='multipart/form-data' action='/merchant/onboarding/documents'>
              <input class='portal-input' type='file' name='documents' accept='.pdf,.jpg,.jpeg,.png,.webp' multiple required>
              <button class='portal-btn' type='submit' style='margin-top:12px'>رفع المستندات</button>
            </form>
            <ul>{doc_rows}</ul>
          </section>
          <section class='portal-card' style='padding:22px'>
            <h2 style='margin-top:0'>3. الإقرار والمتابعة إلى صادق</h2>
            <form method='post' action='/merchant/onboarding/submit'>
              <label style='display:flex;gap:9px;align-items:flex-start'>
                <input type='checkbox' name='declaration' value='1' required>
                <span>أقر بأن البيانات والمستندات المرفوعة صحيحة وحديثة وتخص المنشأة المسجلة.</span>
              </label>
              <button class='portal-btn' type='submit' style='margin-top:14px'>متابعة إلى صادق والتوقيع</button>
            </form>
          </section>
        </main>
        """,
    )


@core.app.get("/merchant/register", response_class=HTMLResponse)
def merchant_register_page():
    return HTMLResponse(_register_page())


@core.app.post("/merchant/register/request", response_class=HTMLResponse)
async def merchant_register_request(request: Request, db: Session = Depends(core.get_db)):
    form = await request.form()
    phone = _form_value(form, "phone")
    token, _delivered = request_registration_otp(db, phone)
    if not token:
        return HTMLResponse(_register_page(message="تحقق من رقم الجوال وحاول مرة أخرى."), status_code=400)
    return HTMLResponse(_register_page(token, "تم إرسال رمز التحقق عبر واتساب."))


@core.app.post("/merchant/register/verify")
async def merchant_register_verify(request: Request, db: Session = Depends(core.get_db)):
    form = await request.form()
    challenge_token = _form_value(form, "challenge_token")
    otp = _form_value(form, "otp")
    merchant_id = verify_registration_otp(db, challenge_token, otp)
    if merchant_id is None:
        return HTMLResponse(_register_page(challenge_token, "الرمز غير صحيح أو انتهت صلاحيته."), status_code=401)
    expires = int(core.now_utc().timestamp()) + portal.MERCHANT_SESSION_SECONDS
    response = RedirectResponse("/merchant/onboarding", status_code=303)
    response.set_cookie(
        "pakgat_merchant",
        portal.merchant_session_token(merchant_id, expires),
        max_age=portal.MERCHANT_SESSION_SECONDS,
        httponly=True,
        secure=core.COOKIE_SECURE,
        samesite="lax",
        path="/merchant",
    )
    return response


@core.app.get("/merchant/onboarding", response_class=HTMLResponse)
def merchant_onboarding_page(request: Request, db: Session = Depends(core.get_db)):
    merchant = portal._merchant_from_request(request, db)
    if merchant is None:
        return RedirectResponse("/merchant/register", status_code=303)
    return HTMLResponse(_onboarding_page(db, merchant))


@core.app.post("/merchant/onboarding/profile", response_class=HTMLResponse)
async def merchant_onboarding_profile(request: Request, db: Session = Depends(core.get_db)):
    merchant = portal._merchant_from_request(request, db)
    if merchant is None:
        return RedirectResponse("/merchant/register", status_code=303)
    form = await request.form()
    try:
        save_onboarding_profile(
            db,
            merchant,
            display_name=_form_value(form, "display_name"),
            legal_name=_form_value(form, "legal_name"),
            commercial_registration=_form_value(form, "commercial_registration"),
            activity=_form_value(form, "activity"),
            tax_number=_form_value(form, "tax_number"),
            bank_name=_form_value(form, "bank_name"),
            iban=_form_value(form, "iban"),
            national_address=_form_value(form, "national_address"),
            contact_email=_form_value(form, "contact_email"),
            website=_form_value(form, "website"),
            representative_name=_form_value(form, "representative_name"),
            representative_title=_form_value(form, "representative_title"),
        )
    except ValueError as exc:
        return HTMLResponse(_onboarding_page(db, merchant, str(exc)), status_code=422)
    return RedirectResponse("/merchant/onboarding", status_code=303)


@core.app.post("/merchant/onboarding/documents", response_class=HTMLResponse)
async def merchant_onboarding_documents(
    request: Request,
    documents: list[UploadFile] = File(...),
    db: Session = Depends(core.get_db),
):
    merchant = portal._merchant_from_request(request, db)
    if merchant is None:
        return RedirectResponse("/merchant/register", status_code=303)
    try:
        for upload in documents:
            payload = await upload.read(MAX_DOCUMENT_BYTES + 1)
            store_onboarding_document(
                db,
                merchant,
                filename=upload.filename or "document",
                content_type=upload.content_type or "",
                content=payload,
            )
    except ValueError as exc:
        return HTMLResponse(_onboarding_page(db, merchant, str(exc)), status_code=422)
    return RedirectResponse("/merchant/onboarding", status_code=303)


@core.app.post("/merchant/onboarding/submit", response_class=HTMLResponse)
async def merchant_onboarding_submit(request: Request, db: Session = Depends(core.get_db)):
    merchant = portal._merchant_from_request(request, db)
    if merchant is None:
        return RedirectResponse("/merchant/register", status_code=303)
    form = await request.form()
    accepted = _form_value(form, "declaration") == "1"
    try:
        application, _contract = submit_onboarding(db, merchant, declaration_accepted=accepted)
    except ValueError as exc:
        return HTMLResponse(_onboarding_page(db, merchant, str(exc)), status_code=422)
    # Sadq outbound is intentionally fail-closed until the authenticated API client
    # and document generation are configured. Never pretend a signing request exists.
    if application.status == "ready_for_sadq":
        return HTMLResponse(
            _onboarding_page(
                db,
                merchant,
                "تم حفظ الطلب وهو جاهز لصادق. سيتم فتح رحلة التوقيع فور اكتمال إعداد تكامل صادق.",
            ),
            status_code=202,
        )
    return RedirectResponse("/merchant/onboarding", status_code=303)


__all__ = [
    "MerchantRegistrationOtpChallenge",
    "MerchantOnboardingApplication",
    "MerchantOnboardingDocument",
    "ensure_merchant_onboarding_schema",
    "request_registration_otp",
    "verify_registration_otp",
    "save_onboarding_profile",
    "store_onboarding_document",
    "submit_onboarding",
    "mark_sadq_signed_for_review",
    "approve_signed_onboarding",
    "request_onboarding_changes",
    "reject_onboarding",
]
