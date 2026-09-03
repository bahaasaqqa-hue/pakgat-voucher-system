"""Pakgat Corporate Benefits.

Prepared B2B employee-verification bridge for the existing Google-hosted Pakgat
stack. Salla remains the customer/order source of truth; this module stores only
corporate membership data and email-verification state.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import smtplib
import ssl
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode
from urllib.request import Request as UrlRequest, urlopen

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app import application as core


class CorporateCompany(core.Base):
    __tablename__ = "corporate_companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    primary_domain: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    salla_group_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    salla_special_offer_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    discount_percent: Mapped[float] = mapped_column(Float, default=0.0)
    membership_days: Mapped[int] = mapped_column(Integer, default=365)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class CorporateCompanyDomain(core.Base):
    __tablename__ = "corporate_company_domains"
    __table_args__ = (UniqueConstraint("domain", name="uq_corporate_company_domain"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(Integer, index=True)
    domain: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class CorporateMember(core.Base):
    __tablename__ = "corporate_members"
    __table_args__ = (
        UniqueConstraint("salla_customer_id", "company_id", name="uq_corporate_member_customer_company"),
        UniqueConstraint("corporate_email", "company_id", name="uq_corporate_member_email_company"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    salla_customer_id: Mapped[str] = mapped_column(String(100), index=True)
    mobile: Mapped[str] = mapped_column(String(40), index=True)
    company_id: Mapped[int] = mapped_column(Integer, index=True)
    corporate_email: Mapped[str] = mapped_column(String(320), index=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    salla_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="pending_email", index=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class CorporateOtpChallenge(core.Base):
    __tablename__ = "corporate_otp_challenges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    member_id: Mapped[int] = mapped_column(Integer, index=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    salt: Mapped[str] = mapped_column(String(80))
    otp_hash: Mapped[str] = mapped_column(String(128))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)


class CorporateAudit(core.Base):
    __tablename__ = "corporate_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    company_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    member_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    details: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)


CORPORATE_LIVE = core.env("CORPORATE_LIVE", "false").lower() == "true"
CORPORATE_SECRET = core.env("CORPORATE_SECRET") or core.ADMIN_SECRET
CORPORATE_OTP_MINUTES = max(3, min(20, int(core.env("CORPORATE_OTP_MINUTES", "10") or "10")))
CORPORATE_PUBLIC_URL = core.env("CORPORATE_PUBLIC_URL", f"{core.BASE_URL}/corporate").rstrip("/")
SMTP_HOST = core.env("CORPORATE_SMTP_HOST")
SMTP_PORT = int(core.env("CORPORATE_SMTP_PORT", "587") or "587")
SMTP_USERNAME = core.env("CORPORATE_SMTP_USERNAME")
SMTP_PASSWORD = core.env("CORPORATE_SMTP_PASSWORD")
SMTP_FROM = core.env("CORPORATE_SMTP_FROM")
SMTP_SSL = core.env("CORPORATE_SMTP_SSL", "false").lower() == "true"
SMTP_STARTTLS = core.env("CORPORATE_SMTP_STARTTLS", "true").lower() != "false"
SALLA_API_BASE = core.env("SALLA_API_BASE_URL", "https://api.salla.dev/admin/v2").rstrip("/")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean_domain(value: str) -> str:
    return str(value or "").strip().lower().lstrip("@").rstrip(".")


def _email_domain(email: str) -> str:
    value = str(email or "").strip().lower()
    if value.count("@") != 1:
        return ""
    local, domain = value.rsplit("@", 1)
    if not local or "." not in domain:
        return ""
    return _clean_domain(domain)


def _audit(db: Session, action: str, *, company_id: int | None = None, member_id: int | None = None, details: str = "") -> None:
    db.add(CorporateAudit(action=action, company_id=company_id, member_id=member_id, details=(details or "")[:1000] or None))
    db.commit()


def _token(payload: dict, ttl_seconds: int = 900) -> str:
    data = dict(payload)
    data["exp"] = int(time.time()) + ttl_seconds
    raw = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    body = raw.hex()
    sig = hmac.new(CORPORATE_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def _untoken(value: str) -> dict:
    try:
        body, sig = value.split(".", 1)
        expected = hmac.new(CORPORATE_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            raise ValueError("bad signature")
        data = json.loads(bytes.fromhex(body).decode("utf-8"))
        if int(data.get("exp") or 0) < int(time.time()):
            raise ValueError("expired")
        return data
    except Exception as exc:
        raise HTTPException(status_code=400, detail="رابط التحقق غير صالح أو منتهي") from exc


def _otp_hash(code: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", code.encode(), salt.encode(), 180_000).hex()


def _new_otp() -> tuple[str, str, str]:
    code = f"{secrets.randbelow(1_000_000):06d}"
    salt = secrets.token_hex(16)
    return code, salt, _otp_hash(code, salt)


def _salla_access_token(db: Session) -> str:
    if core.SALLA_ACCESS_TOKEN:
        return core.SALLA_ACCESS_TOKEN
    row = db.scalar(select(core.SallaOAuthCredential).order_by(core.SallaOAuthCredential.updated_at.desc()).limit(1))
    return row.access_token if row and row.access_token else ""


def _salla_request(db: Session, method: str, path: str, *, params: dict | None = None, payload: dict | None = None) -> tuple[bool, dict | str, int]:
    token = _salla_access_token(db)
    if not token:
        return False, "Salla OAuth is not connected", 0
    url = f"{SALLA_API_BASE}{path}"
    if params:
        url += "?" + urlencode(params)
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = UrlRequest(url, data=data, method=method, headers={"Authorization": f"Bearer {token}", "Accept": "application/json", "Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=20) as response:
            status = int(getattr(response, "status", response.getcode()))
            text = response.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = text
        return 200 <= status < 300, parsed, status
    except HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = text
        return False, parsed, int(exc.code)
    except (URLError, TimeoutError, OSError) as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:300]}", 0


def _digits(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _mobile_matches(left: str, right: str) -> bool:
    a, b = _digits(left), _digits(right)
    if not a or not b:
        return False
    return a == b or a[-9:] == b[-9:]


def salla_find_customer_by_mobile(db: Session, mobile: str) -> tuple[bool, dict | str]:
    normalized = core.normalize_saudi_phone(mobile)
    if not normalized:
        return False, "رقم الجوال السعودي غير صحيح"
    ok, result, status = _salla_request(db, "GET", "/customers", params={"keyword": normalized, "per_page": 30})
    if not ok:
        return False, f"تعذر قراءة عميل سلة ({status or 'connection'}): {str(result)[:220]}"
    rows = result.get("data", []) if isinstance(result, dict) else []
    for row in rows if isinstance(rows, list) else []:
        if _mobile_matches(row.get("mobile") or row.get("phone") or "", normalized):
            customer_id = row.get("id")
            if customer_id:
                return True, {"id": str(customer_id), "mobile": normalized, "name": row.get("first_name") or row.get("name") or ""}
    return False, "لم نجد حساب Pakgat مطابقًا لهذا الجوال في سلة"


def salla_add_customer_to_group(db: Session, customer_id: str, group_id: str) -> tuple[bool, str]:
    ok, result, status = _salla_request(db, "POST", "/customers/groups/add_customers", payload={"group_id": int(group_id), "customers": [int(customer_id)]})
    if ok:
        return True, "تمت إضافة الموظف إلى مجموعة الشركة في سلة"
    return False, f"Salla HTTP {status or 'connection'}: {str(result)[:300]}"


def salla_create_company_group(db: Session, company: CorporateCompany) -> tuple[bool, str]:
    ok, result, status = _salla_request(db, "POST", "/customers/groups", payload={"name": f"{company.name} Employees"})
    if not ok or not isinstance(result, dict):
        return False, f"Salla HTTP {status or 'connection'}: {str(result)[:300]}"
    data = result.get("data") or {}
    group_id = data.get("id") if isinstance(data, dict) else None
    if not group_id:
        return False, "سلة لم تُرجع رقم المجموعة"
    company.salla_group_id = str(group_id)
    company.updated_at = _now()
    db.commit()
    return True, str(group_id)


def _send_otp_email(email: str, code: str, company_name: str) -> tuple[bool, str]:
    if not SMTP_HOST or not SMTP_FROM:
        return False, "إعداد إرسال البريد غير مربوط بعد"
    msg = EmailMessage()
    msg["Subject"] = "رمز تفعيل مزايا شركتك في بكجات"
    msg["From"] = SMTP_FROM
    msg["To"] = email
    msg.set_content(
        f"رمز التحقق لتفعيل مزايا {company_name} في بكجات هو: {code}\n\n"
        f"الرمز صالح لمدة {CORPORATE_OTP_MINUTES} دقائق. لا تشاركه مع أي شخص."
    )
    try:
        if SMTP_SSL:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20, context=ssl.create_default_context()) as server:
                if SMTP_USERNAME:
                    server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.send_message(msg)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
                server.ehlo()
                if SMTP_STARTTLS:
                    server.starttls(context=ssl.create_default_context())
                    server.ehlo()
                if SMTP_USERNAME:
                    server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.send_message(msg)
        return True, "sent"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:250]}"


def corporate_readiness(db: Session) -> dict:
    token_ready = bool(_salla_access_token(db))
    active_companies = int(db.scalar(select(func.count(CorporateCompany.id)).where(CorporateCompany.status == "active")) or 0)
    companies_with_group = int(db.scalar(select(func.count(CorporateCompany.id)).where(CorporateCompany.status == "active", CorporateCompany.salla_group_id.is_not(None))) or 0)
    return {
        "live": CORPORATE_LIVE,
        "salla_oauth": token_ready,
        "smtp": bool(SMTP_HOST and SMTP_FROM),
        "companies": active_companies,
        "companies_with_group": companies_with_group,
        "public_url": CORPORATE_PUBLIC_URL,
    }


def _public_shell(title: str, inner: str) -> str:
    css = """
    *{box-sizing:border-box}body{margin:0;background:#f4f8ff;color:#10233f;font-family:Arial,Tahoma,sans-serif}.c-wrap{width:min(720px,calc(100% - 28px));margin:0 auto;padding:28px 0 50px}.c-brand{color:#0d47d9;font-size:28px;font-weight:950;margin-bottom:22px}.c-card{background:#fff;border:1px solid #dce6f7;border-radius:20px;padding:26px;box-shadow:0 16px 50px rgba(13,71,217,.08)}h1{margin:0 0 8px;color:#0a3caf}.muted{color:#6b7894;line-height:1.7}.input{width:100%;padding:14px;border:1px solid #cfd8ea;border-radius:12px;font-size:16px;margin-top:7px}.btn{width:100%;border:0;border-radius:12px;background:#0d47d9;color:#fff;padding:14px 18px;font-weight:900;font-size:16px;cursor:pointer;margin-top:14px}.ok{background:#ecfdf5;border:1px solid #bbf7d0;color:#166534;padding:12px;border-radius:11px}.warn{background:#fff7ed;border:1px solid #fed7aa;color:#9a3412;padding:12px;border-radius:11px}.steps{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:20px 0}.step{background:#edf4ff;border-radius:12px;padding:11px;text-align:center;font-size:12px;font-weight:900;color:#1749b5}@media(max-width:620px){.steps{grid-template-columns:1fr}.c-card{padding:20px}}
    """
    return f"<!doctype html><html lang='ar' dir='rtl'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{core.esc(title)} | بكجات</title><style>{css}</style></head><body><main class='c-wrap'><div class='c-brand'>بكجات · مزايا الشركات</div>{inner}</main></body></html>"


def _company_shell(title: str, body: str, request: Request) -> HTMLResponse:
    html = core.page_shell(title, body, admin=True)
    try:
        from app import ai_company_dashboard_v2 as v2
        html = v2._layout_wrap(html, request.url.path)
    except Exception:
        pass
    return HTMLResponse(html)


def _admin_redirect(request: Request):
    try:
        core.require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)
    return None


def _form(body: bytes) -> dict:
    return parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)


def _fv(data: dict, key: str, default: str = "") -> str:
    return str((data.get(key) or [default])[0]).strip()


@core.app.get("/corporate", response_class=HTMLResponse)
def corporate_home():
    live_note = "" if CORPORATE_LIVE else "<div class='warn'>النظام جاهز تقنيًا لكنه غير مفتوح للتفعيل العام حتى يكتمل ربط سلة والبريد.</div>"
    return HTMLResponse(_public_shell("تفعيل مزايا شركتك", f"""
    <section class='c-card'><h1>فعّل مزايا شركتك</h1><p class='muted'>تحقق من حسابك في بكجات ثم من بريدك الوظيفي، وبعدها يتم ربط عضويتك بمزايا جهة عملك.</p>{live_note}
    <div class='steps'><div class='step'>1 · رقم الجوال</div><div class='step'>2 · البريد الوظيفي</div><div class='step'>3 · رمز التحقق</div></div>
    <form method='post' action='/corporate/start'><label>رقم الجوال المسجل في بكجات</label><input class='input' name='mobile' inputmode='tel' placeholder='05xxxxxxxx' required><button class='btn'>متابعة</button></form></section>"""))


@core.app.post("/corporate/start", response_class=HTMLResponse)
async def corporate_start(request: Request, db: Session = Depends(core.get_db)):
    if not CORPORATE_LIVE:
        return HTMLResponse(_public_shell("قريبًا", "<section class='c-card'><div class='warn'>التفعيل العام غير مفتوح بعد. البنية جاهزة وننتظر اكتمال اتصال سلة والبريد.</div></section>"), status_code=503)
    data = _form(await request.body())
    mobile = _fv(data, "mobile")
    ok, customer = salla_find_customer_by_mobile(db, mobile)
    if not ok:
        return HTMLResponse(_public_shell("التحقق من الجوال", f"<section class='c-card'><h1>تعذر المتابعة</h1><div class='warn'>{core.esc(customer)}</div><a href='/corporate'>العودة</a></section>"), status_code=400)
    flow = _token({"customer_id": customer["id"], "mobile": customer["mobile"]}, 15 * 60)
    return HTMLResponse(_public_shell("البريد الوظيفي", f"""
    <section class='c-card'><h1>أدخل بريدك الوظيفي</h1><p class='muted'>يجب أن يكون النطاق مسجلاً لدينا ضمن جهة عمل مشاركة في مزايا بكجات.</p>
    <form method='post' action='/corporate/request-otp'><input type='hidden' name='flow' value='{core.esc(flow)}'><label>البريد الوظيفي</label><input class='input' type='email' name='email' placeholder='name@company.com' required><button class='btn'>إرسال رمز التحقق</button></form></section>"""))


@core.app.post("/corporate/request-otp", response_class=HTMLResponse)
async def corporate_request_otp(request: Request, db: Session = Depends(core.get_db)):
    data = _form(await request.body())
    flow = _untoken(_fv(data, "flow"))
    email = _fv(data, "email").lower()
    domain = _email_domain(email)
    if not domain:
        raise HTTPException(status_code=400, detail="البريد الوظيفي غير صحيح")
    domain_row = db.scalar(select(CorporateCompanyDomain).where(CorporateCompanyDomain.domain == domain, CorporateCompanyDomain.status == "active"))
    if not domain_row:
        return HTMLResponse(_public_shell("البريد غير مسجل", "<section class='c-card'><div class='warn'>جهة العمل غير مضافة حاليًا إلى برنامج مزايا بكجات.</div></section>"), status_code=400)
    company = db.get(CorporateCompany, domain_row.company_id)
    if not company or company.status != "active":
        raise HTTPException(status_code=400, detail="الشركة غير مفعلة")

    member = db.scalar(select(CorporateMember).where(CorporateMember.salla_customer_id == str(flow["customer_id"]), CorporateMember.company_id == company.id))
    if member is None:
        member = CorporateMember(salla_customer_id=str(flow["customer_id"]), mobile=str(flow["mobile"]), company_id=company.id, corporate_email=email, status="pending_email")
        db.add(member)
        db.commit(); db.refresh(member)
    else:
        member.mobile = str(flow["mobile"]); member.corporate_email = email; member.email_verified = False; member.status = "pending_email"; member.updated_at = _now(); db.commit()

    recent = db.scalar(select(CorporateOtpChallenge).where(CorporateOtpChallenge.member_id == member.id).order_by(CorporateOtpChallenge.created_at.desc()).limit(1))
    if recent and recent.created_at > _now() - timedelta(seconds=60) and recent.consumed_at is None:
        return HTMLResponse(_public_shell("انتظر", "<section class='c-card'><div class='warn'>تم إرسال رمز مؤخرًا. انتظر دقيقة قبل طلب رمز جديد.</div></section>"), status_code=429)

    code, salt, hashed = _new_otp()
    challenge = CorporateOtpChallenge(member_id=member.id, email=email, salt=salt, otp_hash=hashed, expires_at=_now() + timedelta(minutes=CORPORATE_OTP_MINUTES))
    db.add(challenge); db.commit(); db.refresh(challenge)
    sent, reason = _send_otp_email(email, code, company.name)
    if not sent:
        challenge.consumed_at = _now(); member.last_error = reason; db.commit(); _audit(db, "otp_send_failed", company_id=company.id, member_id=member.id, details=reason)
        return HTMLResponse(_public_shell("إرسال الرمز", f"<section class='c-card'><div class='warn'>{core.esc(reason)}</div></section>"), status_code=503)
    _audit(db, "otp_sent", company_id=company.id, member_id=member.id, details=f"domain={domain}")
    verify_token = _token({"challenge_id": challenge.id, "member_id": member.id}, (CORPORATE_OTP_MINUTES + 2) * 60)
    return HTMLResponse(_public_shell("رمز التحقق", f"""
    <section class='c-card'><h1>تحقق من بريدك</h1><p class='muted'>أرسلنا رمزًا من 6 أرقام إلى {core.esc(email)}.</p>
    <form method='post' action='/corporate/verify'><input type='hidden' name='verify_token' value='{core.esc(verify_token)}'><label>رمز التحقق</label><input class='input' name='otp' inputmode='numeric' pattern='[0-9]{{6}}' maxlength='6' required><button class='btn'>تفعيل المزايا</button></form></section>"""))


@core.app.post("/corporate/verify", response_class=HTMLResponse)
async def corporate_verify(request: Request, db: Session = Depends(core.get_db)):
    data = _form(await request.body())
    token_data = _untoken(_fv(data, "verify_token"))
    otp = _fv(data, "otp")
    challenge = db.get(CorporateOtpChallenge, int(token_data["challenge_id"]))
    member = db.get(CorporateMember, int(token_data["member_id"]))
    if not challenge or not member or challenge.member_id != member.id or challenge.consumed_at is not None:
        raise HTTPException(status_code=400, detail="جلسة التحقق غير صالحة")
    if challenge.expires_at < _now():
        challenge.consumed_at = _now(); db.commit(); raise HTTPException(status_code=400, detail="انتهت صلاحية رمز التحقق")
    if challenge.attempts >= challenge.max_attempts:
        raise HTTPException(status_code=429, detail="تم تجاوز عدد المحاولات")
    challenge.attempts += 1
    if not hmac.compare_digest(challenge.otp_hash, _otp_hash(otp, challenge.salt)):
        db.commit(); return HTMLResponse(_public_shell("رمز غير صحيح", "<section class='c-card'><div class='warn'>رمز التحقق غير صحيح.</div></section>"), status_code=400)

    company = db.get(CorporateCompany, member.company_id)
    challenge.consumed_at = _now(); member.email_verified = True; member.verified_at = _now(); member.expires_at = _now() + timedelta(days=int(company.membership_days or 365)); member.status = "verified_pending_sync"; member.updated_at = _now(); db.commit()
    sync_ok, sync_msg = (False, "مجموعة الشركة في سلة غير مجهزة بعد")
    if company.salla_group_id:
        sync_ok, sync_msg = salla_add_customer_to_group(db, member.salla_customer_id, company.salla_group_id)
    if sync_ok:
        member.status = "active"; member.salla_synced_at = _now(); member.last_error = None
    else:
        member.last_error = sync_msg
    db.commit(); _audit(db, "member_verified", company_id=company.id, member_id=member.id, details=f"salla_sync={sync_ok}")
    note = "<div class='ok'>تم تفعيل مزايا شركتك وربط عضويتك في بكجات ✅</div>" if sync_ok else "<div class='ok'>تم التحقق من بريدك بنجاح ✅</div><div class='warn' style='margin-top:10px'>العضوية بانتظار المزامنة مع سلة وستُستكمل تلقائيًا بعد اكتمال الربط.</div>"
    return HTMLResponse(_public_shell("تم التحقق", f"<section class='c-card'><h1>أهلًا بك في مزايا الشركات</h1>{note}</section>"))


@core.app.get("/admin/company/corporate", response_class=HTMLResponse)
def corporate_admin(request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect: return redirect
    ready = corporate_readiness(db)
    companies = list(db.scalars(select(CorporateCompany).order_by(CorporateCompany.name)).all())
    members = list(db.scalars(select(CorporateMember).order_by(CorporateMember.created_at.desc()).limit(100)).all())
    active_members = _count_member(db, "active")
    pending_sync = _count_member(db, "verified_pending_sync")
    company_rows = "".join(f"<tr><td>{core.esc(c.name)}</td><td>{core.esc(c.primary_domain)}</td><td>{core.esc(c.discount_percent)}%</td><td>{core.esc(c.salla_group_id or 'بانتظار الربط')}</td><td>{core.esc(c.status)}</td><td><form method='post' action='/admin/company/corporate/companies/{c.id}/sync-salla' style='margin:0'><button class='btn btn-muted'>مزامنة سلة</button></form></td></tr>" for c in companies) or "<tr><td colspan='6' class='muted'>لم تتم إضافة شركات بعد.</td></tr>"
    member_rows = "".join(f"<tr><td>{core.esc(m.corporate_email)}</td><td>{core.esc(m.mobile)}</td><td>{core.esc(m.salla_customer_id)}</td><td>{core.esc(m.status)}</td><td>{core.esc(core.fmt_dt(m.expires_at))}</td></tr>" for m in members) or "<tr><td colspan='5' class='muted'>لا يوجد موظفون مسجلون بعد.</td></tr>"
    body = f"""
    <main class='wrap' style='padding:26px 0 48px'><div style='display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap'><div><h1 style='margin:0'>مزايا الشركات والموظفين</h1><p class='muted'>الجوال → البريد الوظيفي → OTP → مجموعة سلة</p></div><a class='btn btn-blue' href='/admin/company/corporate/companies/new'>إضافة شركة</a></div>
    <div class='grid grid-mobile-1' style='grid-template-columns:repeat(5,1fr);margin:18px 0'><section class='card' style='padding:16px'><div class='muted'>الحالة العامة</div><strong>{'جاهز للتفعيل' if ready['live'] else 'وضع التحضير'}</strong></section><section class='card' style='padding:16px'><div class='muted'>سلة OAuth</div><strong>{'متصل' if ready['salla_oauth'] else 'بانتظار الربط'}</strong></section><section class='card' style='padding:16px'><div class='muted'>بريد OTP</div><strong>{'جاهز' if ready['smtp'] else 'بانتظار الإعداد'}</strong></section><section class='card' style='padding:16px'><div class='muted'>أعضاء نشطون</div><strong>{active_members}</strong></section><section class='card' style='padding:16px'><div class='muted'>بانتظار المزامنة</div><strong>{pending_sync}</strong></section></div>
    <section class='card' style='padding:20px;margin-bottom:18px'><h2>الشركات</h2><div class='table-wrap'><table><thead><tr><th>الشركة</th><th>النطاق</th><th>الميزة</th><th>مجموعة سلة</th><th>الحالة</th><th>إجراء</th></tr></thead><tbody>{company_rows}</tbody></table></div></section>
    <section class='card' style='padding:20px'><h2>الموظفون</h2><div class='table-wrap'><table><thead><tr><th>البريد الوظيفي</th><th>الجوال</th><th>Customer ID</th><th>الحالة</th><th>تنتهي</th></tr></thead><tbody>{member_rows}</tbody></table></div></section></main>"""
    return _company_shell("مزايا الشركات", body, request)


def _count_member(db: Session, status: str) -> int:
    return int(db.scalar(select(func.count(CorporateMember.id)).where(CorporateMember.status == status)) or 0)


@core.app.get("/admin/company/corporate/companies/new", response_class=HTMLResponse)
def corporate_company_new(request: Request):
    redirect = _admin_redirect(request)
    if redirect: return redirect
    body = """<main class='wrap' style='padding:28px 0'><section class='card' style='padding:24px;max-width:720px;margin:auto'><h1>إضافة شركة</h1><form method='post' action='/admin/company/corporate/companies'><label>اسم الشركة</label><input class='input' name='name' required><label style='margin-top:12px'>نطاق البريد</label><input class='input' name='domain' placeholder='company.com' required><label style='margin-top:12px'>نسبة الميزة / الخصم</label><input class='input' name='discount_percent' type='number' min='0' max='100' step='0.01' value='0'><label style='margin-top:12px'>مدة العضوية بالأيام</label><input class='input' name='membership_days' type='number' min='30' max='730' value='365'><label style='margin-top:12px'>Salla Group ID (اختياري الآن)</label><input class='input' name='salla_group_id'><button class='btn btn-blue' style='margin-top:16px'>حفظ الشركة</button></form></section></main>"""
    return _company_shell("إضافة شركة", body, request)


@core.app.post("/admin/company/corporate/companies")
async def corporate_company_create(request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect: return redirect
    data = _form(await request.body())
    name, domain = _fv(data, "name"), _clean_domain(_fv(data, "domain"))
    if not name or not domain or "." not in domain:
        raise HTTPException(status_code=400, detail="بيانات الشركة غير صحيحة")
    if db.scalar(select(CorporateCompany).where((CorporateCompany.name == name) | (CorporateCompany.primary_domain == domain))):
        raise HTTPException(status_code=409, detail="الشركة أو النطاق موجود مسبقًا")
    try: discount = float(_fv(data, "discount_percent", "0") or 0)
    except ValueError: discount = 0.0
    try: days = int(_fv(data, "membership_days", "365") or 365)
    except ValueError: days = 365
    row = CorporateCompany(name=name, primary_domain=domain, salla_group_id=_fv(data, "salla_group_id") or None, discount_percent=max(0, min(100, discount)), membership_days=max(30, min(730, days)), status="active")
    db.add(row); db.commit(); db.refresh(row)
    db.add(CorporateCompanyDomain(company_id=row.id, domain=domain, status="active")); db.commit(); _audit(db, "company_created", company_id=row.id, details=f"domain={domain}")
    return RedirectResponse("/admin/company/corporate", status_code=303)


@core.app.post("/admin/company/corporate/companies/{company_id}/sync-salla")
def corporate_company_sync_salla(company_id: int, request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect: return redirect
    company = db.get(CorporateCompany, company_id)
    if not company: raise HTTPException(status_code=404, detail="الشركة غير موجودة")
    if not company.salla_group_id:
        ok, message = salla_create_company_group(db, company)
        if not ok:
            company.updated_at = _now(); db.commit(); _audit(db, "company_salla_group_failed", company_id=company.id, details=message)
            return RedirectResponse("/admin/company/corporate?sync=failed", status_code=303)
    pending = list(db.scalars(select(CorporateMember).where(CorporateMember.company_id == company.id, CorporateMember.email_verified.is_(True), CorporateMember.status == "verified_pending_sync")).all())
    for member in pending:
        ok, msg = salla_add_customer_to_group(db, member.salla_customer_id, company.salla_group_id)
        if ok:
            member.status = "active"; member.salla_synced_at = _now(); member.last_error = None
        else:
            member.last_error = msg
        member.updated_at = _now()
    db.commit(); _audit(db, "company_salla_sync", company_id=company.id, details=f"pending_members={len(pending)}")
    return RedirectResponse("/admin/company/corporate", status_code=303)


@core.app.get("/admin/company/corporate/readiness")
def corporate_readiness_api(request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect: return redirect
    return corporate_readiness(db)
