import os
import json
import secrets
import hashlib
import hmac
import html
import io
import smtplib
from email.message import EmailMessage
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import parse_qs, quote

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
import qrcode
from sqlalchemy import DateTime, Integer, String, create_engine, select, update, or_, func
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


database_url = os.environ["DATABASE_URL"]
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
elif database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


class Voucher(Base):
    __tablename__ = "vouchers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    verification_token: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    order_id: Mapped[str] = mapped_column(String(100), index=True)
    product_id: Mapped[str] = mapped_column(String(100), index=True)
    product_name: Mapped[str] = mapped_column(String(255))
    merchant_name: Mapped[str] = mapped_column(String(255))
    customer_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    customer_phone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    option_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    redeemed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "voucher_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    voucher_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(60), index=True)
    details: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)


class VoucherCreate(BaseModel):
    order_id: str = Field(min_length=1, max_length=100)
    product_id: str = Field(min_length=1, max_length=100)
    product_name: str = Field(min_length=1, max_length=255)
    merchant_name: str = Field(min_length=1, max_length=255)
    customer_name: Optional[str] = Field(default=None, max_length=255)
    customer_phone: Optional[str] = Field(default=None, max_length=30)
    option_name: Optional[str] = Field(default=None, max_length=255)
    validity_days: int = Field(default=7, ge=1, le=365)


class VoucherResponse(BaseModel):
    code: str
    verification_token: str
    verification_url: str
    qr_url: str
    status: str
    expires_at: datetime


def get_db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def fmt_dt(value: Optional[datetime]) -> str:
    if not value:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone(timedelta(hours=3))).strftime("%Y-%m-%d %H:%M")


def esc(value) -> str:
    return html.escape(str(value or ""), quote=True)


def generate_voucher_code() -> str:
    return "PKG-" + secrets.token_hex(4).upper()


def generate_verification_token() -> str:
    return secrets.token_urlsafe(32)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    # Populate the audit table for vouchers created before audit logging was added.
    # The operation is idempotent, so every deployment can run it safely.
    with SessionLocal() as db:
        backfill_audit_logs(db)
    yield


app = FastAPI(title="Pakgat Voucher System", version="3.0", lifespan=lifespan)

BASE_URL = env("PUBLIC_BASE_URL", "https://pakgat-voucher-system.onrender.com").rstrip("/")
SALLA_WEBHOOK_SECRET = env("SALLA_WEBHOOK_SECRET")
ADMIN_USERNAME = env("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = env("ADMIN_PASSWORD")
ADMIN_SECRET = env("ADMIN_SECRET", SALLA_WEBHOOK_SECRET or "change-this-admin-secret")
COOKIE_SECURE = env("COOKIE_SECURE", "true").lower() != "false"

try:
    MERCHANT_CODES = json.loads(env("MERCHANT_CODES", "{}"))
except json.JSONDecodeError:
    MERCHANT_CODES = {}

VOUCHER_PRODUCT_IDS = {v.strip() for v in env("VOUCHER_PRODUCT_IDS", "").split(",") if v.strip()}


BASE_CSS = """
*{box-sizing:border-box}body{margin:0;font-family:Arial,Tahoma,sans-serif;background:#f5f8ff;color:#10233f}a{text-decoration:none;color:inherit}.wrap{width:min(1120px,calc(100% - 28px));margin:auto}.topbar{background:#2446ba;color:white;padding:15px 0}.topbar .wrap{display:flex;align-items:center;justify-content:space-between;gap:16px}.brand{font-size:24px;font-weight:900}.brand small{font-size:13px;display:block;opacity:.85}.btn{display:inline-flex;align-items:center;justify-content:center;border:0;border-radius:12px;padding:11px 17px;font-weight:800;cursor:pointer}.btn-primary{background:#14b8d4;color:#fff}.btn-blue{background:#2446ba;color:#fff}.btn-danger{background:#dc2626;color:#fff}.btn-muted{background:#e8eefc;color:#2446ba}.card{background:#fff;border:1px solid #e1e8f5;border-radius:18px;box-shadow:0 14px 40px rgba(27,54,124,.08)}.input,.select{width:100%;padding:12px 14px;border:1px solid #cfd8ea;border-radius:11px;background:#fff;font-size:15px;outline:none}.input:focus,.select:focus{border-color:#14b8d4;box-shadow:0 0 0 3px rgba(20,184,212,.15)}label{display:block;margin:0 0 7px;font-weight:800}.grid{display:grid;gap:16px}.muted{color:#6b7894}.badge{display:inline-flex;align-items:center;border-radius:999px;padding:6px 10px;font-size:12px;font-weight:900}.badge-active{background:#dcfce7;color:#15803d}.badge-redeemed{background:#fee2e2;color:#b91c1c}.badge-expired{background:#fef3c7;color:#a16207}.alert{padding:13px 15px;border-radius:12px;margin-bottom:16px}.alert-error{background:#fef2f2;color:#991b1b;border:1px solid #fecaca}.alert-ok{background:#ecfdf5;color:#166534;border:1px solid #bbf7d0}table{width:100%;border-collapse:collapse}th,td{text-align:right;padding:13px 12px;border-bottom:1px solid #e8edf6;vertical-align:middle}th{font-size:13px;color:#64748b;background:#f8faff}.table-wrap{overflow:auto;border:1px solid #e1e8f5;border-radius:14px}@media(max-width:720px){.desktop-only{display:none}.topbar .wrap{align-items:flex-start}.grid-mobile-1{grid-template-columns:1fr!important}th,td{white-space:nowrap}}
"""


def page_shell(title: str, body: str, admin: bool = False) -> str:
    nav = ""
    if admin:
        nav = f'<div style="display:flex;gap:8px;flex-wrap:wrap"><a class="btn btn-muted" href="/admin">لوحة الإدارة</a><a class="btn btn-muted" href="/admin/vouchers/new">قسيمة جديدة</a><a class="btn btn-muted" href="/admin/audit">سجل العمليات</a><a class="btn btn-muted" href="/admin/integrations">تكامل سلة</a><form method="post" action="/admin/logout" style="margin:0"><button class="btn btn-danger" type="submit">تسجيل الخروج</button></form></div>'
    return f"""<!doctype html><html lang='ar' dir='rtl'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{esc(title)} | Pakgat</title><style>{BASE_CSS}</style></head><body><header class='topbar'><div class='wrap'><a href='/' class='brand'>بكجات <small>Pakgat Voucher System</small></a>{nav}</div></header>{body}</body></html>"""


def admin_token(username: str, expires: int) -> str:
    payload = f"{username}:{expires}"
    sig = hmac.new(ADMIN_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{sig}"


def valid_admin_token(token: str) -> bool:
    try:
        username, expires_str, sig = token.split(":", 2)
        expires = int(expires_str)
    except (ValueError, AttributeError):
        return False
    if username != ADMIN_USERNAME or expires < int(now_utc().timestamp()):
        return False
    expected = hmac.new(ADMIN_SECRET.encode(), f"{username}:{expires}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


def require_admin(request: Request):
    if not valid_admin_token(request.cookies.get("pakgat_admin", "")):
        raise HTTPException(status_code=401, detail="Admin authentication required")
    return True


def verify_salla_signature(raw_body: bytes, received_signature: str) -> bool:
    if not SALLA_WEBHOOK_SECRET:
        return False
    expected = hmac.new(SALLA_WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, received_signature or "")


def first_value(mapping: dict, *paths: str):
    for path in paths:
        current = mapping
        found = True
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                found = False
                break
            current = current[part]
        if found and current not in (None, ""):
            return current
    return None


def normalize_items(data: dict) -> list[dict]:
    items = data.get("items") or data.get("products") or []
    return items if isinstance(items, list) else []


def item_product_id(item: dict) -> str:
    return str(first_value(item, "product.id", "product_id", "id") or "")


def item_product_name(item: dict) -> str:
    return str(first_value(item, "product.name", "name", "product_name") or "عرض بكجات")


def item_option_name(item: dict) -> Optional[str]:
    options = item.get("options")
    if isinstance(options, list):
        labels = []
        for option in options:
            if isinstance(option, dict):
                label = first_value(option, "value.name", "value", "name") or ""
                if label:
                    labels.append(str(label))
        return "، ".join(labels) or None
    return str(options) if options else None


def item_quantity(item: dict) -> int:
    try:
        return max(1, int(first_value(item, "quantity", "qty") or 1))
    except (TypeError, ValueError):
        return 1


def generate_qr_png(url: str) -> bytes:
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    image = qr.make_image(fill_color="#10233f", back_color="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def send_voucher_email(customer_email: str, customer_name: str, product_name: str, voucher_code: str, verification_url: str, expires_at: datetime) -> None:
    smtp_host, smtp_user, smtp_password = env("SMTP_HOST"), env("SMTP_USER"), env("SMTP_PASSWORD")
    smtp_from = env("SMTP_FROM", smtp_user)
    smtp_port = int(env("SMTP_PORT", "587"))
    if not all([smtp_host, smtp_user, smtp_password, smtp_from, customer_email]):
        return
    message = EmailMessage()
    message["Subject"] = f"قسيمتك من بكجات — {product_name}"
    message["From"] = smtp_from
    message["To"] = customer_email
    message.set_content(f"مرحبًا {customer_name or 'عميل بكجات'}،\n\nاستمتع بعرضك الخاص من بكجات.\nالعرض: {product_name}\nالكود: {voucher_code}\nتاريخ الانتهاء: {fmt_dt(expires_at)}\n\nافتح القسيمة: {verification_url}\n\nيجب استخدام القسيمة قبل انتهاء الصلاحية الموضح، ولا يمكن استخدامها بعد اعتمادها من التاجر.")
    html_body = f"""<html lang='ar' dir='rtl'><body style='font-family:Arial;line-height:1.9;color:#10233f'><h2 style='color:#2446ba'>بكجات Pakgat</h2><p>مرحبًا {esc(customer_name or 'عميل بكجات')}،</p><p><strong>استمتع بعرضك الخاص من موقع بكجات.</strong></p><p>العرض: {esc(product_name)}<br>الكود: {esc(voucher_code)}<br>تاريخ الانتهاء: {fmt_dt(expires_at)}</p><p><img src='cid:voucher-qr' width='230'></p><p><a href='{esc(verification_url)}' style='background:#14b8d4;color:white;padding:13px 24px;border-radius:10px;text-decoration:none'>فتح القسيمة</a></p><p>يجب استخدام القسيمة قبل انتهاء الصلاحية الموضح. لا تعرضها للتاجر إلا عند استلام الخدمة.</p></body></html>"""
    message.add_alternative(html_body, subtype="html")
    message.get_payload()[-1].add_related(generate_qr_png(verification_url), maintype="image", subtype="png", cid="<voucher-qr>", filename="pakgat-voucher-qr.png")
    if smtp_port == 465:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=20) as smtp:
            smtp.login(smtp_user, smtp_password); smtp.send_message(message)
    else:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as smtp:
            smtp.starttls(); smtp.login(smtp_user, smtp_password); smtp.send_message(message)


def create_voucher_record(db: Session, order_id: str, product_id: str, product_name: str, merchant_name: str, customer_name: Optional[str], customer_phone: Optional[str], option_name: Optional[str], validity_days: int = 7) -> Voucher:
    existing = db.scalar(select(Voucher).where(Voucher.order_id == order_id, Voucher.product_id == product_id))
    if existing:
        return existing
    for _ in range(5):
        voucher = Voucher(code=generate_voucher_code(), verification_token=generate_verification_token(), order_id=order_id, product_id=product_id, product_name=product_name, merchant_name=merchant_name, customer_name=customer_name, customer_phone=customer_phone, option_name=option_name, status="active", expires_at=now_utc() + timedelta(days=validity_days))
        db.add(voucher)
        try:
            db.commit(); db.refresh(voucher); return voucher
        except Exception:
            db.rollback()
    raise HTTPException(status_code=500, detail="Unable to generate a unique voucher")


def log_event(
    db: Session,
    action: str,
    voucher_id: Optional[int] = None,
    details: Optional[str] = None,
    created_at: Optional[datetime] = None,
) -> None:
    db.add(
        AuditLog(
            voucher_id=voucher_id,
            action=action,
            details=(details or "")[:500] or None,
            created_at=created_at or now_utc(),
        )
    )
    db.commit()


def backfill_audit_logs(db: Session) -> int:
    """Create missing historical audit entries without duplicating existing logs."""
    vouchers = list(db.scalars(select(Voucher).order_by(Voucher.id)).all())
    if not vouchers:
        return 0

    existing = set(
        db.execute(
            select(AuditLog.voucher_id, AuditLog.action).where(AuditLog.voucher_id.is_not(None))
        ).all()
    )
    added = 0
    for voucher in vouchers:
        created_key = (voucher.id, "voucher_created")
        if created_key not in existing:
            db.add(
                AuditLog(
                    voucher_id=voucher.id,
                    action="voucher_created",
                    details="Historical voucher imported into audit log",
                    created_at=voucher.created_at or now_utc(),
                )
            )
            added += 1

        if voucher.status == "redeemed" and voucher.redeemed_at:
            redeemed_key = (voucher.id, "voucher_redeemed")
            if redeemed_key not in existing:
                db.add(
                    AuditLog(
                        voucher_id=voucher.id,
                        action="voucher_redeemed",
                        details="Historical redemption imported into audit log",
                        created_at=voucher.redeemed_at,
                    )
                )
                added += 1

        if voucher.status == "expired":
            expired_key = (voucher.id, "voucher_expired")
            if expired_key not in existing:
                db.add(
                    AuditLog(
                        voucher_id=voucher.id,
                        action="voucher_expired",
                        details="Historical expiration imported into audit log",
                        created_at=voucher.expires_at or now_utc(),
                    )
                )
                added += 1

    if added:
        db.commit()
    return added


def update_voucher_status(voucher: Voucher, db: Session) -> str:
    expires = voucher.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if voucher.status == "active" and expires < now_utc():
        voucher.status = "expired"
        db.commit()
        db.refresh(voucher)
        # Write the expiration only after the voucher update succeeds.
        existing = db.scalar(
            select(AuditLog.id).where(
                AuditLog.voucher_id == voucher.id,
                AuditLog.action == "voucher_expired",
            )
        )
        if not existing:
            log_event(db, "voucher_expired", voucher.id, "Voucher expired automatically", expires)
    return voucher.status


def status_badge(value: str) -> str:
    labels = {"active": "صالحة", "redeemed": "مستخدمة", "expired": "منتهية"}
    return f"<span class='badge badge-{esc(value)}'>{labels.get(value, esc(value))}</span>"


@app.get("/")
def home():
    return {"status": "running", "service": "Pakgat Voucher System", "version": "3.0.2", "admin": BASE_URL + "/admin/login", "database": "connected"}


@app.get("/health")
def health():
    with engine.connect():
        pass
    return {"ok": True, "database": "connected"}


@app.post("/api/vouchers", response_model=VoucherResponse, status_code=status.HTTP_201_CREATED)
def create_voucher(payload: VoucherCreate, db: Session = Depends(get_db)):
    existing = db.scalar(select(Voucher).where(Voucher.order_id == payload.order_id, Voucher.product_id == payload.product_id))
    if existing:
        raise HTTPException(status_code=409, detail="A voucher already exists for this order and product.")
    voucher = create_voucher_record(db, payload.order_id, payload.product_id, payload.product_name, payload.merchant_name, payload.customer_name, payload.customer_phone, payload.option_name, payload.validity_days)
    log_event(db, "voucher_created", voucher.id, "Created through API")
    url = BASE_URL + "/v/" + voucher.verification_token
    return VoucherResponse(code=voucher.code, verification_token=voucher.verification_token, verification_url=url, qr_url=url + "/qr.png", status=voucher.status, expires_at=voucher.expires_at)


def build_verification_page(voucher: Voucher, error_message: Optional[str] = None) -> str:
    states = {
        "active": ("القسيمة صالحة", "#15803d", "#dcfce7", "✓"),
        "redeemed": ("تم استخدام القسيمة", "#b91c1c", "#fee2e2", "✓"),
        "expired": ("القسيمة منتهية", "#a16207", "#fef3c7", "!"),
    }
    title, color, bg, icon = states.get(voucher.status, ("حالة غير معروفة", "#475569", "#e2e8f0", "?"))
    redeem = ""
    if voucher.status == "active":
        err = f"<div class='alert alert-error'>{esc(error_message)}</div>" if error_message else ""
        redeem = f"""{err}<details style='margin-top:18px'><summary style='cursor:pointer;font-weight:900;color:#2446ba'>خاص بالتاجر: اعتماد القسيمة</summary><form method='post' action='/v/{esc(voucher.verification_token)}/redeem' onsubmit="return confirm('هل تم تقديم الخدمة فعلًا للعميل؟ لا يمكن التراجع بعد الاعتماد.');" style='margin-top:14px'><label>رمز التاجر</label><input class='input' name='merchant_code' type='password' inputmode='numeric' maxlength='30' required placeholder='أدخل رمز التاجر'><button class='btn btn-blue' style='width:100%;margin-top:12px' type='submit'>تأكيد تقديم الخدمة</button></form><div style='background:#f8fafc;padding:14px;border-radius:12px;margin-top:12px;line-height:1.8'><strong>شروط التاجر</strong><div>• تحقق من اسم العرض والخيار وتاريخ الصلاحية.</div><div>• لا تعتمد القسيمة إلا بعد تقديم الخدمة كاملة.</div><div>• بعد الاعتماد تصبح القسيمة مستخدمة ولا يمكن استخدامها مرة أخرى.</div></div></details>"""
    used = f"<div class='alert alert-error' style='margin-top:16px'>تم الاستخدام بتاريخ <strong>{fmt_dt(voucher.redeemed_at)}</strong></div>" if voucher.status == "redeemed" else ""
    body = f"""<main class='wrap' style='padding:28px 0 44px'><section class='card' style='max-width:620px;margin:auto;padding:26px'><div style='text-align:center'><div style='font-size:36px;font-weight:900;color:#2446ba'>بكجات</div><div class='muted'>Pakgat</div></div><div style='margin:20px 0;padding:18px;border-radius:16px;text-align:center;background:{bg};color:{color}'><div style='width:52px;height:52px;border-radius:50%;background:{color};color:white;display:grid;place-items:center;margin:0 auto 8px;font-size:28px;font-weight:900'>{icon}</div><h2 style='margin:0'>{title}</h2></div><div style='text-align:center;margin-bottom:20px'><h1 style='font-size:24px;margin:0 0 7px'>{esc(voucher.product_name)}</h1><div class='muted'>{esc(voucher.merchant_name)}</div></div><img src='/v/{esc(voucher.verification_token)}/qr.png' alt='QR' width='210' height='210' style='display:block;margin:0 auto 18px;border:8px solid white;box-shadow:0 8px 28px rgba(20,40,90,.12);border-radius:16px'><div class='table-wrap'><table><tr><th>كود القسيمة</th><td dir='ltr' style='font-weight:900;color:#2446ba'>{esc(voucher.code)}</td></tr><tr><th>الخيار</th><td>{esc(voucher.option_name or 'غير محدد')}</td></tr><tr><th>اسم العميل</th><td>{esc(voucher.customer_name or 'عميل بكجات')}</td></tr><tr><th>تاريخ الانتهاء</th><td>{fmt_dt(voucher.expires_at)}</td></tr></table></div><div style='background:#eefcff;border:1px solid #bdeff7;padding:16px;border-radius:14px;margin-top:18px;line-height:1.9'><strong>مرحبًا بك في بكجات 👋</strong><div>نتمنى لك تجربة ممتعة والاستمتاع بعرضك الخاص من موقع بكجات.</div></div><div style='background:#f8fafc;padding:16px;border-radius:14px;margin-top:14px;line-height:1.9'><strong>شروط استخدام العميل</strong><div>• يجب استخدام القسيمة قبل تاريخ انتهاء الصلاحية الموضح.</div><div>• القسيمة صالحة للخدمة والخيار المذكورين فقط.</div><div>• لا تشارك رابط القسيمة أو رمز QR مع أي شخص.</div><div>• لا تعرض القسيمة للتاجر إلا عند استلام الخدمة.</div><div>• القسيمة لا تستبدل نقدًا، وبعد اعتمادها لا يمكن استخدامها مرة أخرى.</div></div>{redeem}{used}<div class='muted' style='text-align:center;margin-top:20px;font-size:13px'>نظام التحقق من القسائم — Pakgat</div></section></main>"""
    return page_shell("قسيمة بكجات", body)


@app.get("/v/{verification_token}", response_class=HTMLResponse)
def verify_voucher(verification_token: str, db: Session = Depends(get_db)):
    voucher = db.scalar(select(Voucher).where(Voucher.verification_token == verification_token))
    if not voucher:
        return HTMLResponse(page_shell("القسيمة غير موجودة", "<main class='wrap' style='padding:50px 0'><div class='card' style='padding:30px;text-align:center'><h1 style='color:#b91c1c'>القسيمة غير موجودة</h1><p>تأكد من صحة الرابط أو تواصل مع إدارة بكجات.</p></div></main>"), status_code=404)
    update_voucher_status(voucher, db)
    return HTMLResponse(build_verification_page(voucher))


@app.post("/v/{verification_token}/redeem", response_class=HTMLResponse)
async def redeem_voucher(verification_token: str, request: Request, db: Session = Depends(get_db)):
    voucher = db.scalar(select(Voucher).where(Voucher.verification_token == verification_token))
    if not voucher:
        raise HTTPException(status_code=404, detail="Voucher not found")
    update_voucher_status(voucher, db)
    if voucher.status != "active":
        return HTMLResponse(build_verification_page(voucher), status_code=409)
    form = parse_qs((await request.body()).decode("utf-8", errors="ignore"))
    entered = form.get("merchant_code", [""])[0].strip()
    expected = str(MERCHANT_CODES.get(voucher.merchant_name) or MERCHANT_CODES.get("*") or "").strip()
    if not expected:
        return HTMLResponse(build_verification_page(voucher, "لم يتم إعداد رمز لهذا التاجر. تواصل مع إدارة بكجات."), status_code=503)
    if not hmac.compare_digest(entered, expected):
        return HTMLResponse(build_verification_page(voucher, "رمز التاجر غير صحيح."), status_code=403)
    result = db.execute(update(Voucher).where(Voucher.id == voucher.id, Voucher.status == "active", Voucher.expires_at >= now_utc()).values(status="redeemed", redeemed_at=now_utc()).execution_options(synchronize_session=False))
    db.commit()
    db.refresh(voucher)
    if result.rowcount != 1:
        log_event(db, "redeem_conflict", voucher.id, "Concurrent or invalid redemption attempt")
        update_voucher_status(voucher, db)
        return HTMLResponse(build_verification_page(voucher, "تعذر اعتماد القسيمة؛ ربما تم استخدامها في نفس اللحظة."), status_code=409)
    log_event(db, "voucher_redeemed", voucher.id, "Redeemed by merchant QR page")
    return HTMLResponse(build_verification_page(voucher))


@app.get("/v/{verification_token}/qr.png", response_class=Response)
def voucher_qr(verification_token: str, db: Session = Depends(get_db)):
    voucher = db.scalar(select(Voucher).where(Voucher.verification_token == verification_token))
    if not voucher:
        raise HTTPException(status_code=404, detail="Voucher not found.")
    return Response(generate_qr_png(BASE_URL + "/v/" + verification_token), media_type="image/png", headers={"Cache-Control": "private, max-age=300"})


@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_page(request: Request):
    if valid_admin_token(request.cookies.get("pakgat_admin", "")):
        return RedirectResponse("/admin", status_code=303)
    body = """<main class='wrap' style='padding:55px 0'><section class='card' style='max-width:430px;margin:auto;padding:28px'><h1 style='margin-top:0'>دخول إدارة القسائم</h1><p class='muted'>أدخل بيانات الإدارة المضافة في Render.</p><form method='post' action='/admin/login'><label>اسم المستخدم</label><input class='input' name='username' autocomplete='username' required><label style='margin-top:14px'>كلمة المرور</label><input class='input' name='password' type='password' autocomplete='current-password' required><button class='btn btn-blue' style='width:100%;margin-top:18px' type='submit'>تسجيل الدخول</button></form></section></main>"""
    return HTMLResponse(page_shell("تسجيل دخول الإدارة", body))


@app.post("/admin/login")
async def admin_login(request: Request):
    form = parse_qs((await request.body()).decode("utf-8", errors="ignore"))
    username = form.get("username", [""])[0].strip()
    password = form.get("password", [""])[0]
    if not ADMIN_PASSWORD:
        return HTMLResponse(page_shell("خطأ إعداد", "<main class='wrap' style='padding:50px 0'><div class='alert alert-error'>يجب إضافة ADMIN_PASSWORD في Environment على Render أولًا.</div></main>"), status_code=503)
    if not (hmac.compare_digest(username, ADMIN_USERNAME) and hmac.compare_digest(password, ADMIN_PASSWORD)):
        return HTMLResponse(page_shell("فشل الدخول", "<main class='wrap' style='padding:50px 0'><div class='card' style='max-width:500px;margin:auto;padding:25px'><div class='alert alert-error'>بيانات الدخول غير صحيحة.</div><a class='btn btn-blue' href='/admin/login'>المحاولة مرة أخرى</a></div></main>"), status_code=403)
    expires = int((now_utc() + timedelta(hours=12)).timestamp())
    response = RedirectResponse("/admin", status_code=303)
    response.set_cookie("pakgat_admin", admin_token(username, expires), max_age=43200, httponly=True, secure=COOKIE_SECURE, samesite="lax")
    return response


@app.post("/admin/logout")
def admin_logout():
    response = RedirectResponse("/admin/login", status_code=303)
    response.delete_cookie("pakgat_admin")
    return response


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request, q: str = "", voucher_status: str = "", page: int = 1, db: Session = Depends(get_db)):
    try:
        require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)
    # lazily mark expired vouchers
    db.execute(update(Voucher).where(Voucher.status == "active", Voucher.expires_at < now_utc()).values(status="expired").execution_options(synchronize_session=False)); db.commit()
    page = max(1, page)
    page_size = 25
    filters = []
    if q.strip():
        term = f"%{q.strip()}%"
        filters.append(or_(Voucher.code.ilike(term), Voucher.customer_name.ilike(term), Voucher.order_id.ilike(term), Voucher.product_name.ilike(term)))
    if voucher_status in {"active", "redeemed", "expired"}:
        filters.append(Voucher.status == voucher_status)
    total_filtered = db.scalar(select(func.count(Voucher.id)).where(*filters)) or 0
    total_pages = max(1, (total_filtered + page_size - 1) // page_size)
    page = min(page, total_pages)
    statement = select(Voucher).where(*filters).order_by(Voucher.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    vouchers = list(db.scalars(statement).all())
    counts = dict(db.execute(select(Voucher.status, func.count(Voucher.id)).group_by(Voucher.status)).all())
    rows = "".join(f"<tr><td><a style='color:#2446ba;font-weight:900' href='/admin/vouchers/{v.id}'>{esc(v.code)}</a></td><td>{esc(v.customer_name or '—')}</td><td>{esc(v.product_name)}</td><td>{status_badge(v.status)}</td><td>{fmt_dt(v.expires_at)}</td><td><a class='btn btn-muted' href='/admin/vouchers/{v.id}'>عرض</a></td></tr>" for v in vouchers) or "<tr><td colspan='6' style='text-align:center;padding:30px'>لا توجد نتائج.</td></tr>"
    prev_link = f"/admin?q={quote(q)}&voucher_status={quote(voucher_status)}&page={page-1}" if page > 1 else ""
    next_link = f"/admin?q={quote(q)}&voucher_status={quote(voucher_status)}&page={page+1}" if page < total_pages else ""
    pagination = f"<div style='display:flex;align-items:center;justify-content:center;gap:10px;margin-top:18px'>{f'<a class=\"btn btn-muted\" href=\"{prev_link}\">السابق</a>' if prev_link else ''}<strong>صفحة {page} من {total_pages}</strong>{f'<a class=\"btn btn-muted\" href=\"{next_link}\">التالي</a>' if next_link else ''}</div>"
    body = f"""<main class='wrap' style='padding:28px 0 48px'><h1>لوحة إدارة القسائم</h1><div class='grid grid-mobile-1' style='grid-template-columns:repeat(4,1fr);margin-bottom:18px'><div class='card' style='padding:18px'><div class='muted'>الإجمالي</div><strong style='font-size:29px'>{sum(counts.values())}</strong></div><div class='card' style='padding:18px'><div class='muted'>صالحة</div><strong style='font-size:29px;color:#15803d'>{counts.get('active',0)}</strong></div><div class='card' style='padding:18px'><div class='muted'>مستخدمة</div><strong style='font-size:29px;color:#b91c1c'>{counts.get('redeemed',0)}</strong></div><div class='card' style='padding:18px'><div class='muted'>منتهية</div><strong style='font-size:29px;color:#a16207'>{counts.get('expired',0)}</strong></div></div><section class='card' style='padding:18px'><form method='get' action='/admin' class='grid grid-mobile-1' style='grid-template-columns:2fr 1fr auto;align-items:end'><div><label>البحث</label><input class='input' name='q' value='{esc(q)}' placeholder='كود القسيمة، العميل، الطلب أو العرض'></div><div><label>الحالة</label><select class='select' name='voucher_status'><option value=''>الكل</option><option value='active' {'selected' if voucher_status=='active' else ''}>صالحة</option><option value='redeemed' {'selected' if voucher_status=='redeemed' else ''}>مستخدمة</option><option value='expired' {'selected' if voucher_status=='expired' else ''}>منتهية</option></select></div><button class='btn btn-blue' type='submit'>بحث</button></form><div class='table-wrap' style='margin-top:18px'><table><thead><tr><th>الكود</th><th>العميل</th><th>العرض</th><th>الحالة</th><th>الانتهاء</th><th></th></tr></thead><tbody>{rows}</tbody></table></div>{pagination}</section></main>"""
    return HTMLResponse(page_shell("لوحة الإدارة", body, admin=True))


@app.get("/admin/vouchers/new", response_class=HTMLResponse)
def admin_new_voucher(request: Request):
    try:
        require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)
    body = """<main class='wrap' style='padding:28px 0 48px'><section class='card' style='max-width:800px;margin:auto;padding:24px'><h1>إنشاء قسيمة جديدة</h1><form method='post' action='/admin/vouchers/new' class='grid grid-mobile-1' style='grid-template-columns:1fr 1fr'><div><label>رقم الطلب</label><input class='input' name='order_id' required></div><div><label>رقم المنتج</label><input class='input' name='product_id' required></div><div><label>اسم العرض / الخدمة</label><input class='input' name='product_name' required></div><div><label>اسم التاجر</label><input class='input' name='merchant_name' value='Pakgat' required></div><div><label>اسم العميل</label><input class='input' name='customer_name'></div><div><label>جوال العميل</label><input class='input' name='customer_phone'></div><div><label>الخيار</label><input class='input' name='option_name'></div><div><label>مدة الصلاحية بالأيام</label><input class='input' name='validity_days' type='number' value='7' min='1' max='365' required></div><button class='btn btn-blue' style='grid-column:1/-1' type='submit'>إنشاء القسيمة</button></form></section></main>"""
    return HTMLResponse(page_shell("قسيمة جديدة", body, admin=True))


@app.post("/admin/vouchers/new")
async def admin_create_voucher(request: Request, db: Session = Depends(get_db)):
    try:
        require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)
    f = parse_qs((await request.body()).decode("utf-8", errors="ignore"))
    get = lambda k, d="": f.get(k, [d])[0].strip()
    try:
        validity = max(1, min(365, int(get("validity_days", "7"))))
        voucher = create_voucher_record(db, get("order_id"), get("product_id"), get("product_name"), get("merchant_name"), get("customer_name") or None, get("customer_phone") or None, get("option_name") or None, validity)
        log_event(db, "voucher_created", voucher.id, "Created from admin dashboard")
    except Exception as exc:
        return HTMLResponse(page_shell("تعذر الإنشاء", f"<main class='wrap' style='padding:40px 0'><div class='alert alert-error'>تعذر إنشاء القسيمة: {esc(exc)}</div></main>", admin=True), status_code=400)
    return RedirectResponse(f"/admin/vouchers/{voucher.id}?created=1", status_code=303)


@app.get("/admin/vouchers/{voucher_id}", response_class=HTMLResponse)
def admin_voucher_detail(voucher_id: int, request: Request, created: int = 0, db: Session = Depends(get_db)):
    try:
        require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)
    voucher = db.get(Voucher, voucher_id)
    if not voucher:
        raise HTTPException(status_code=404, detail="Voucher not found")
    update_voucher_status(voucher, db)
    verify_url = BASE_URL + "/v/" + voucher.verification_token
    created_box = "<div class='alert alert-ok'>تم إنشاء القسيمة بنجاح.</div>" if created else ""
    action = ""
    if voucher.status == "active":
        action = f"""<form method='post' action='/admin/vouchers/{voucher.id}/redeem' onsubmit="return confirm('هل تم تقديم الخدمة؟ لا يمكن التراجع بعد اعتماد القسيمة.');"><button class='btn btn-danger' type='submit'>اعتماد القسيمة كمستخدمة</button></form>"""
    body = f"""<main class='wrap' style='padding:28px 0 48px'>{created_box}<section class='card' style='padding:24px'><div style='display:flex;justify-content:space-between;gap:15px;align-items:flex-start;flex-wrap:wrap'><div><h1 style='margin:0 0 8px'>{esc(voucher.code)}</h1>{status_badge(voucher.status)}</div><div style='display:flex;gap:8px;flex-wrap:wrap'><a class='btn btn-primary' target='_blank' href='{esc(verify_url)}'>فتح القسيمة</a>{action}</div></div><div class='grid grid-mobile-1' style='grid-template-columns:260px 1fr;margin-top:24px'><div><img src='/v/{esc(voucher.verification_token)}/qr.png' width='250' style='max-width:100%;border-radius:16px;border:1px solid #e1e8f5'></div><div class='table-wrap'><table><tr><th>اسم العرض</th><td>{esc(voucher.product_name)}</td></tr><tr><th>التاجر</th><td>{esc(voucher.merchant_name)}</td></tr><tr><th>العميل</th><td>{esc(voucher.customer_name or '—')}</td></tr><tr><th>الجوال</th><td dir='ltr'>{esc(voucher.customer_phone or '—')}</td></tr><tr><th>الخيار</th><td>{esc(voucher.option_name or '—')}</td></tr><tr><th>رقم الطلب</th><td>{esc(voucher.order_id)}</td></tr><tr><th>رقم المنتج</th><td>{esc(voucher.product_id)}</td></tr><tr><th>الإنشاء</th><td>{fmt_dt(voucher.created_at)}</td></tr><tr><th>الانتهاء</th><td>{fmt_dt(voucher.expires_at)}</td></tr><tr><th>الاستخدام</th><td>{fmt_dt(voucher.redeemed_at)}</td></tr><tr><th>رابط العميل</th><td><input class='input' dir='ltr' readonly value='{esc(verify_url)}' onclick='this.select()'></td></tr></table></div></div></section></main>"""
    return HTMLResponse(page_shell("تفاصيل القسيمة", body, admin=True))


@app.post("/admin/vouchers/{voucher_id}/redeem")
def admin_redeem_voucher(voucher_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)
    result = db.execute(update(Voucher).where(Voucher.id == voucher_id, Voucher.status == "active", Voucher.expires_at >= now_utc()).values(status="redeemed", redeemed_at=now_utc()).execution_options(synchronize_session=False))
    db.commit()
    if result.rowcount != 1:
        log_event(db, "admin_redeem_failed", voucher_id, "Voucher was not active")
        raise HTTPException(status_code=409, detail="Voucher is not active")
    log_event(db, "voucher_redeemed", voucher_id, "Redeemed from admin dashboard")
    return RedirectResponse(f"/admin/vouchers/{voucher_id}", status_code=303)


@app.get("/admin/audit", response_class=HTMLResponse)
def admin_audit(request: Request, db: Session = Depends(get_db)):
    try:
        require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)
    logs = db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(200)).all()
    voucher_ids = {item.voucher_id for item in logs if item.voucher_id is not None}
    voucher_codes = {}
    if voucher_ids:
        voucher_codes = dict(
            db.execute(select(Voucher.id, Voucher.code).where(Voucher.id.in_(voucher_ids))).all()
        )
    action_labels = {
        "voucher_created": "إنشاء قسيمة",
        "voucher_redeemed": "استخدام القسيمة",
        "voucher_expired": "انتهاء القسيمة",
        "admin_redeem_failed": "محاولة استخدام مرفوضة",
        "salla_webhook_rejected": "Webhook مرفوض",
        "salla_webhook_ignored": "Webhook متجاهل",
        "salla_webhook_received": "استقبال Webhook من سلة",
        "salla_webhook_processed": "معالجة طلب سلة",
    }
    rows = "".join(
        f"<tr><td>{fmt_dt(item.created_at)}</td><td>{esc(action_labels.get(item.action, item.action))}</td><td>{esc(voucher_codes.get(item.voucher_id, item.voucher_id or '—'))}</td><td>{esc(item.details or '—')}</td></tr>"
        for item in logs
    ) or "<tr><td colspan='4' class='muted'>لا توجد عمليات مسجلة حتى الآن.</td></tr>"
    body = f"""<main class='wrap' style='padding:28px 0 48px'><section class='card' style='padding:20px'><h1>سجل العمليات</h1><p class='muted'>آخر 200 عملية على نظام القسائم.</p><div class='table-wrap'><table><thead><tr><th>التاريخ</th><th>العملية</th><th>رقم القسيمة</th><th>التفاصيل</th></tr></thead><tbody>{rows}</tbody></table></div></section></main>"""
    return HTMLResponse(page_shell("سجل العمليات", body, admin=True))


@app.get("/admin/integrations", response_class=HTMLResponse)
def admin_integrations(request: Request):
    try:
        require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)
    webhook_ready = bool(SALLA_WEBHOOK_SECRET)
    products_ready = bool(VOUCHER_PRODUCT_IDS)
    smtp_ready = all(env(k) for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM"))
    def state(ok: bool) -> str:
        return "<span class='badge badge-active'>جاهز</span>" if ok else "<span class='badge badge-expired'>يحتاج إعداد</span>"
    webhook_url = BASE_URL + "/webhooks/salla"
    body = f"""<main class='wrap' style='padding:28px 0 48px'><h1>تكامل سلة</h1><div class='grid grid-mobile-1' style='grid-template-columns:repeat(3,1fr);margin-bottom:18px'><div class='card' style='padding:20px'><h3>توقيع Webhook</h3>{state(webhook_ready)}<p class='muted'>SALLA_WEBHOOK_SECRET</p></div><div class='card' style='padding:20px'><h3>منتجات القسائم</h3>{state(products_ready)}<p class='muted'>{esc(', '.join(sorted(VOUCHER_PRODUCT_IDS)) or 'غير محدد')}</p></div><div class='card' style='padding:20px'><h3>البريد الإلكتروني</h3>{state(smtp_ready)}<p class='muted'>إرسال رابط القسيمة للعميل</p></div></div><section class='card' style='padding:22px'><h2>رابط Webhook</h2><input class='input' dir='ltr' readonly onclick='this.select()' value='{esc(webhook_url)}'><h2 style='margin-top:24px'>الأحداث المدعومة</h2><p><code>order.payment.updated</code> عند تحول حالة الدفع إلى paid/completed/success.</p><h2 style='margin-top:24px'>المسار التشغيلي</h2><p>طلب مدفوع في سلة ← التحقق من التوقيع ← مطابقة المنتج ← إنشاء القسيمة وQR ← إرسال الرابط بالبريد عند اكتمال SMTP.</p></section></main>"""
    return HTMLResponse(page_shell("تكامل سلة", body, admin=True))


@app.post("/webhooks/salla")
async def salla_webhook(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    raw_body = await request.body()
    if not verify_salla_signature(raw_body, request.headers.get("x-salla-signature", "")):
        log_event(db, "salla_webhook_rejected", details="Invalid signature")
        return JSONResponse(status_code=401, content={"ok": False, "detail": "Invalid Salla signature."})
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        log_event(db, "salla_webhook_rejected", details="Invalid JSON payload")
        return JSONResponse(status_code=400, content={"ok": False, "detail": "Invalid JSON."})
    event = str(payload.get("event") or "")
    data = payload.get("data") or {}
    log_event(db, "salla_webhook_received", details=f"Event: {event or 'unknown'}")
    if event != "order.payment.updated":
        log_event(db, "salla_webhook_ignored", details=f"Unsupported event: {event}")
        return {"ok": True, "ignored": True, "reason": "Unsupported event."}
    payment_status = str(first_value(data, "payment.status.slug", "payment.status", "payment_status", "status.slug") or "").lower()
    if payment_status not in {"paid", "completed", "success", "successful"}:
        log_event(db, "salla_webhook_ignored", details=f"Payment status: {payment_status}")
        return {"ok": True, "ignored": True, "reason": "Order payment is not paid.", "payment_status": payment_status}
    base_order_id = str(first_value(data, "id", "order.id", "reference_id") or "")
    if not base_order_id:
        log_event(db, "salla_webhook_rejected", details="Order ID is missing")
        return JSONResponse(status_code=422, content={"ok": False, "detail": "Order ID is missing."})
    customer_name = str(first_value(data, "customer.name", "customer.first_name") or "عميل بكجات")
    customer_email = str(first_value(data, "customer.email", "email") or "")
    customer_phone = str(first_value(data, "customer.mobile", "customer.phone", "mobile") or "")
    merchant_name = str(first_value(payload, "merchant.name", "merchant.store_name") or "Pakgat")
    created = []
    for item in normalize_items(data):
        product_id = item_product_id(item)
        if product_id not in VOUCHER_PRODUCT_IDS:
            continue
        for index in range(1, item_quantity(item) + 1):
            voucher = create_voucher_record(db, f"{base_order_id}:{product_id}:{index}", product_id, item_product_name(item), merchant_name, customer_name, customer_phone, item_option_name(item), int(env("DEFAULT_VALIDITY_DAYS", "7")))
            verification_url = BASE_URL + "/v/" + voucher.verification_token
            created.append({"code": voucher.code, "verification_url": verification_url})
            log_event(db, "voucher_created", voucher.id, f"Created from Salla order {base_order_id}")
            if customer_email:
                background_tasks.add_task(send_voucher_email, customer_email, customer_name, voucher.product_name, voucher.code, verification_url, voucher.expires_at)
    log_event(db, "salla_webhook_processed", details=f"Order {base_order_id}; created {len(created)} voucher(s)")
    return {"ok": True, "event": event, "created_count": len(created), "email_queued": bool(created and customer_email), "vouchers": created}
