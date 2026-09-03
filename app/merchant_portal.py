"""Public Pakgat merchant portal with WhatsApp OTP authentication.

The portal deliberately shares the existing Merchant records while remaining
separate from internal `/admin` routes and controls.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import parse_qs

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import DateTime, Integer, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app import application as core
from app import merchant_finance as finance
from app.jood_outbound import _send_whatsloop_text


OTP_TTL = timedelta(minutes=5)
OTP_RESEND_COOLDOWN = timedelta(seconds=60)
OTP_MAX_ATTEMPTS = 5
MERCHANT_SESSION_SECONDS = 14 * 24 * 60 * 60
MERCHANT_PORTAL_SECRET = os.getenv("MERCHANT_PORTAL_SECRET", "").strip()
ALLOWED_MERCHANT_STATUSES = {"pending", "active"}


class MerchantPortalOtpChallenge(core.Base):
    __tablename__ = "merchant_portal_otp_challenges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    challenge_token: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    merchant_id: Mapped[int] = mapped_column(Integer, index=True)
    destination: Mapped[str] = mapped_column(String(40))
    otp_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=core.now_utc, index=True)


def ensure_merchant_portal_schema() -> None:
    MerchantPortalOtpChallenge.__table__.create(core.engine, checkfirst=True)


def _portal_secret() -> str:
    # Read the environment at call time so test/deployment processes may inject the
    # secret before using auth even if this module was imported during app startup.
    value = os.getenv("MERCHANT_PORTAL_SECRET", MERCHANT_PORTAL_SECRET).strip()
    if not value:
        raise HTTPException(status_code=503, detail="Merchant portal authentication is not configured")
    return value


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _otp_digest(challenge_token: str, otp: str) -> str:
    secret = _portal_secret()
    payload = f"{challenge_token}:{otp}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def merchant_session_token(merchant_id: int, expires: int) -> str:
    secret = _portal_secret()
    payload = f"{int(merchant_id)}:{int(expires)}"
    signature = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}:{signature}"


def valid_merchant_session(token: str) -> Optional[int]:
    try:
        secret = _portal_secret()
        merchant_id_raw, expires_raw, signature = str(token or "").split(":", 2)
        merchant_id = int(merchant_id_raw)
        expires = int(expires_raw)
    except (HTTPException, TypeError, ValueError):
        return None
    if expires < int(core.now_utc().timestamp()):
        return None
    payload = f"{merchant_id}:{expires}"
    expected = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return None
    return merchant_id


def _find_merchant_by_phone(db: Session, phone: str) -> Optional[finance.Merchant]:
    normalized = core.normalize_saudi_phone(phone or "")
    if not normalized:
        return None
    merchants = db.scalars(
        select(finance.Merchant).where(finance.Merchant.contact_phone.is_not(None))
    ).all()
    for merchant in merchants:
        if merchant.status not in ALLOWED_MERCHANT_STATUSES:
            continue
        if core.normalize_saudi_phone(merchant.contact_phone or "") == normalized:
            return merchant
    return None


def _otp_message(code: str) -> str:
    return (
        f"رمز الدخول إلى بوابة Pakgat للتجار: {code}\n"
        "الرمز صالح لمدة 5 دقائق.\n"
        "لا تشارك الرمز مع أي شخص."
    )


def request_merchant_otp(db: Session, phone: str) -> tuple[Optional[str], bool]:
    """Create and send a login challenge without leaking whether a phone exists."""
    _portal_secret()
    merchant = _find_merchant_by_phone(db, phone)
    if merchant is None:
        return None, False

    destination = core.normalize_saudi_phone(merchant.contact_phone or "")
    if not destination:
        return None, False

    now = core.now_utc()
    latest = db.scalar(
        select(MerchantPortalOtpChallenge)
        .where(MerchantPortalOtpChallenge.merchant_id == merchant.id)
        .order_by(MerchantPortalOtpChallenge.created_at.desc())
        .limit(1)
    )
    if latest is not None:
        latest_created = _as_utc(latest.created_at)
        if latest_created and now - latest_created < OTP_RESEND_COOLDOWN:
            return latest.challenge_token, False

    previous = db.scalars(
        select(MerchantPortalOtpChallenge).where(
            MerchantPortalOtpChallenge.merchant_id == merchant.id,
            MerchantPortalOtpChallenge.status == "pending",
        )
    ).all()
    for old in previous:
        old.status = "expired"

    challenge_token = secrets.token_urlsafe(32)
    code = f"{secrets.randbelow(1_000_000):06d}"
    challenge = MerchantPortalOtpChallenge(
        challenge_token=challenge_token,
        merchant_id=merchant.id,
        destination=destination,
        otp_hash=_otp_digest(challenge_token, code),
        status="pending",
        attempt_count=0,
        expires_at=now + OTP_TTL,
        created_at=now,
    )
    db.add(challenge)
    db.commit()

    delivered, _summary = _send_whatsloop_text(destination, _otp_message(code))
    if delivered:
        challenge.sent_at = core.now_utc()
    else:
        challenge.status = "failed"
    db.commit()
    db.refresh(challenge)
    return challenge_token, bool(delivered)


def verify_merchant_otp(db: Session, challenge_token: str, otp: str) -> Optional[int]:
    """Verify one challenge, enforcing expiry and a five-attempt ceiling."""
    _portal_secret()
    challenge = db.scalar(
        select(MerchantPortalOtpChallenge)
        .where(MerchantPortalOtpChallenge.challenge_token == str(challenge_token or "").strip())
        .limit(1)
    )
    if challenge is None or challenge.status != "pending":
        return None

    now = core.now_utc()
    expires_at = _as_utc(challenge.expires_at)
    if expires_at is None or expires_at <= now:
        challenge.status = "expired"
        db.commit()
        return None

    if int(challenge.attempt_count or 0) >= OTP_MAX_ATTEMPTS:
        challenge.status = "failed"
        db.commit()
        return None

    supplied = str(otp or "").strip()
    expected = _otp_digest(challenge.challenge_token, supplied)
    if not hmac.compare_digest(expected, challenge.otp_hash):
        challenge.attempt_count = int(challenge.attempt_count or 0) + 1
        if challenge.attempt_count >= OTP_MAX_ATTEMPTS:
            challenge.status = "failed"
        db.commit()
        return None

    merchant = db.get(finance.Merchant, challenge.merchant_id)
    if merchant is None or merchant.status not in ALLOWED_MERCHANT_STATUSES:
        challenge.status = "failed"
        db.commit()
        return None

    challenge.status = "used"
    challenge.used_at = now
    db.commit()
    return merchant.id


def _merchant_from_request(request: Request, db: Session) -> Optional[finance.Merchant]:
    merchant_id = valid_merchant_session(request.cookies.get("pakgat_merchant", ""))
    if merchant_id is None:
        return None
    merchant = db.get(finance.Merchant, merchant_id)
    if merchant is None or merchant.status not in ALLOWED_MERCHANT_STATUSES:
        return None
    return merchant


def _portal_shell(title: str, body: str) -> str:
    css = """
    *{box-sizing:border-box}body{margin:0;font-family:Cairo,Arial,Tahoma,sans-serif;background:#f5f7fb;color:#0f1d35}
    a{text-decoration:none;color:inherit}.portal-wrap{width:min(1040px,calc(100% - 28px));margin:auto}
    .portal-top{background:#0d1526;color:#fff;padding:17px 0}.portal-brand{font-size:24px;font-weight:900;letter-spacing:.2px}
    .portal-brand small{display:block;font-size:12px;font-weight:600;opacity:.72}.portal-card{background:#fff;border:1px solid #e5e9f1;border-radius:18px;box-shadow:0 12px 35px rgba(13,21,38,.07)}
    .portal-input{width:100%;border:1px solid #d7deea;border-radius:12px;padding:13px 14px;font-size:16px;outline:none;background:#fff}
    .portal-input:focus{border-color:#2446ba;box-shadow:0 0 0 3px rgba(36,70,186,.12)}
    .portal-btn{border:0;border-radius:12px;padding:12px 18px;font-weight:800;cursor:pointer;background:#2446ba;color:#fff;display:inline-flex;align-items:center;justify-content:center}
    .portal-btn-muted{background:#edf1f8;color:#24334c}.muted{color:#718096}.grid{display:grid;gap:14px}.pill{display:inline-flex;padding:6px 10px;border-radius:999px;background:#eef2ff;color:#2446ba;font-weight:800;font-size:13px}
    table{width:100%;border-collapse:collapse}th,td{text-align:right;padding:12px;border-bottom:1px solid #edf0f5}th{color:#667085;font-size:13px;background:#fafbfc}.table-wrap{overflow:auto;border:1px solid #edf0f5;border-radius:13px}
    @media(max-width:720px){.grid-two{grid-template-columns:1fr!important}th,td{white-space:nowrap}}
    """
    return (
        "<!doctype html><html lang='ar' dir='rtl'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{core.esc(title)} | Pakgat</title><style>{css}</style></head><body>"
        "<header class='portal-top'><div class='portal-wrap'><div class='portal-brand'>Pakgat"
        "<small>بوابة التجار</small></div></div></header>"
        f"{body}</body></html>"
    )


def _login_form(message: str = "") -> str:
    notice = f"<p class='muted'>{core.esc(message)}</p>" if message else ""
    return _portal_shell(
        "دخول التاجر",
        f"""
        <main class='portal-wrap' style='padding:48px 0'>
          <section class='portal-card' style='max-width:520px;margin:auto;padding:26px'>
            <h1 style='margin-top:0'>دخول التاجر</h1>
            <p class='muted'>أدخل رقم الجوال المسجل لدى Pakgat وسنرسل رمز الدخول عبر واتساب.</p>
            {notice}
            <form method='post' action='/merchant/login/request'>
              <label for='phone' style='display:block;font-weight:800;margin-bottom:7px'>رقم الجوال</label>
              <input id='phone' class='portal-input' name='phone' dir='ltr' inputmode='tel' autocomplete='tel' required>
              <button class='portal-btn' type='submit' style='width:100%;margin-top:14px'>إرسال رمز الدخول</button>
            </form>
          </section>
        </main>
        """,
    )


def _verify_form(challenge_token: str, message: str = "") -> str:
    notice = f"<p class='muted'>{core.esc(message)}</p>" if message else ""
    return _portal_shell(
        "تحقق من الرمز",
        f"""
        <main class='portal-wrap' style='padding:48px 0'>
          <section class='portal-card' style='max-width:520px;margin:auto;padding:26px'>
            <h1 style='margin-top:0'>أدخل رمز الدخول</h1>
            <p class='muted'>إذا كان الرقم مسجلاً لدينا، أرسلنا رمزًا من 6 أرقام عبر واتساب.</p>
            {notice}
            <form method='post' action='/merchant/login/verify'>
              <input type='hidden' name='challenge_token' value='{core.esc(challenge_token)}'>
              <label for='otp' style='display:block;font-weight:800;margin-bottom:7px'>رمز الدخول</label>
              <input id='otp' class='portal-input' name='otp' dir='ltr' inputmode='numeric' autocomplete='one-time-code' minlength='6' maxlength='6' required>
              <button class='portal-btn' type='submit' style='width:100%;margin-top:14px'>دخول</button>
            </form>
            <a href='/merchant' class='portal-btn portal-btn-muted' style='width:100%;margin-top:9px'>العودة</a>
          </section>
        </main>
        """,
    )


@core.app.get("/merchant", response_class=HTMLResponse)
def merchant_portal_home(request: Request, db: Session = Depends(core.get_db)):
    if _merchant_from_request(request, db) is not None:
        return RedirectResponse("/merchant/dashboard", status_code=303)
    return HTMLResponse(_login_form())


@core.app.post("/merchant/login/request", response_class=HTMLResponse)
async def merchant_portal_request_login(request: Request, db: Session = Depends(core.get_db)):
    form = parse_qs((await request.body()).decode("utf-8", errors="replace"))
    phone = str((form.get("phone") or [""])[0]).strip()
    try:
        challenge_token, _delivered = request_merchant_otp(db, phone)
    except HTTPException as exc:
        if exc.status_code == 503:
            return HTMLResponse(_login_form("خدمة الدخول غير متاحة مؤقتًا."), status_code=503)
        raise
    generic_token = challenge_token or secrets.token_urlsafe(32)
    return HTMLResponse(
        _verify_form(
            generic_token,
            "إذا كان الرقم مسجلاً لدينا، تم إرسال رمز الدخول عبر واتساب.",
        )
    )


@core.app.post("/merchant/login/verify")
async def merchant_portal_verify_login(request: Request, db: Session = Depends(core.get_db)):
    form = parse_qs((await request.body()).decode("utf-8", errors="replace"))
    challenge_token = str((form.get("challenge_token") or [""])[0]).strip()
    otp = str((form.get("otp") or [""])[0]).strip()
    try:
        merchant_id = verify_merchant_otp(db, challenge_token, otp)
    except HTTPException as exc:
        if exc.status_code == 503:
            return HTMLResponse(_verify_form(challenge_token, "خدمة الدخول غير متاحة مؤقتًا."), status_code=503)
        raise
    if merchant_id is None:
        return HTMLResponse(
            _verify_form(challenge_token, "الرمز غير صحيح أو انتهت صلاحيته. اطلب رمزًا جديدًا إذا لزم."),
            status_code=401,
        )

    expires = int(core.now_utc().timestamp()) + MERCHANT_SESSION_SECONDS
    response = RedirectResponse("/merchant/dashboard", status_code=303)
    response.set_cookie(
        "pakgat_merchant",
        merchant_session_token(merchant_id, expires),
        max_age=MERCHANT_SESSION_SECONDS,
        httponly=True,
        secure=core.COOKIE_SECURE,
        samesite="lax",
        path="/merchant",
    )
    return response


@core.app.get("/merchant/dashboard", response_class=HTMLResponse)
def merchant_portal_dashboard(request: Request, db: Session = Depends(core.get_db)):
    merchant = _merchant_from_request(request, db)
    if merchant is None:
        return RedirectResponse("/merchant", status_code=303)

    contract = db.scalar(
        select(finance.MerchantContract)
        .where(finance.MerchantContract.merchant_id == merchant.id)
        .order_by(finance.MerchantContract.created_at.desc())
        .limit(1)
    )
    products = db.scalars(
        select(finance.MerchantProductLink)
        .where(finance.MerchantProductLink.merchant_id == merchant.id)
        .order_by(finance.MerchantProductLink.created_at.desc())
    ).all()

    status_label = {"pending": "قيد المراجعة", "active": "نشط"}.get(merchant.status, merchant.status)
    contract_number = contract.agreement_number if contract else "—"
    contract_status = contract.status if contract else "لا توجد اتفاقية"
    contract_signed_at = core.fmt_dt(contract.signed_at) if contract else "—"
    product_rows = "".join(
        f"<tr><td>{core.esc(item.product_name_snapshot or '—')}</td>"
        f"<td dir='ltr'>{core.esc(item.sku or '—')}</td>"
        f"<td>{core.esc(item.product_status)}</td></tr>"
        for item in products
    ) or "<tr><td colspan='3'>لا توجد عروض مرتبطة بالحساب حتى الآن.</td></tr>"

    body = f"""
    <main class='portal-wrap' style='padding:30px 0 50px'>
      <div style='display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:18px'>
        <div><h1 style='margin:0 0 4px'>{core.esc(merchant.display_name)}</h1><div class='muted' dir='ltr'>{core.esc(merchant.code)}</div></div>
        <form method='post' action='/merchant/logout'><button class='portal-btn portal-btn-muted' type='submit'>تسجيل الخروج</button></form>
      </div>

      <div class='grid grid-two' style='grid-template-columns:1fr 1fr;margin-bottom:16px'>
        <section class='portal-card' style='padding:20px'>
          <h2 style='margin-top:0'>بيانات الشراكة</h2>
          <p><strong>الاسم القانوني:</strong> {core.esc(merchant.legal_name or '—')}</p>
          <p><strong>حالة الحساب:</strong> <span class='pill'>{core.esc(status_label)}</span></p>
          <p><strong>الجوال المسجل:</strong> <span dir='ltr'>{core.esc(merchant.contact_phone or '—')}</span></p>
        </section>
        <section class='portal-card' style='padding:20px'>
          <h2 style='margin-top:0'>اتفاقية الشراكة</h2>
          <p><strong>رقم الاتفاقية:</strong> <span dir='ltr'>{core.esc(contract_number)}</span></p>
          <p><strong>الحالة:</strong> {core.esc(contract_status)}</p>
          <p><strong>تاريخ التوقيع:</strong> {core.esc(contract_signed_at)}</p>
        </section>
      </div>

      <section class='portal-card' style='padding:20px;margin-bottom:16px'>
        <h2 style='margin-top:0'>العروض المرتبطة</h2>
        <div class='table-wrap'><table><thead><tr><th>العرض</th><th>SKU</th><th>الحالة</th></tr></thead><tbody>{product_rows}</tbody></table></div>
      </section>

      <section class='portal-card' style='padding:20px'>
        <h2 style='margin-top:0'>ملاحق العروض</h2>
        <p class='muted' style='margin-bottom:0'>ستظهر هنا ملاحق العروض الخاصة باتفاقيتك عند تفعيل هذه الخدمة. لا يوجد أي ملحق منشأ تلقائيًا.</p>
      </section>
    </main>
    """
    return HTMLResponse(_portal_shell("لوحة التاجر", body))


@core.app.post("/merchant/logout")
def merchant_portal_logout(request: Request):
    _ = request
    response = RedirectResponse("/merchant", status_code=303)
    response.delete_cookie(
        "pakgat_merchant",
        path="/merchant",
        secure=core.COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )
    return response


__all__ = [
    "MerchantPortalOtpChallenge",
    "ensure_merchant_portal_schema",
    "request_merchant_otp",
    "verify_merchant_otp",
    "merchant_session_token",
    "valid_merchant_session",
    "merchant_portal_home",
    "merchant_portal_request_login",
    "merchant_portal_verify_login",
    "merchant_portal_dashboard",
    "merchant_portal_logout",
]
