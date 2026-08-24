Warning: truncated output (original token count: 36295)
Total output lines: 2953

# PAKGAT_BUILD: 2026-08-11-CUSTOMER-PARTNER-DETAILS-v9.1
import os
import json
import secrets
import hashlib
import hmac
import html
import io
import smtplib
import re
from email.message import EmailMessage
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import parse_qs, quote, urlencode
from urllib.request import Request as UrlRequest, urlopen
from urllib.error import HTTPError, URLError

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
import qrcode
from sqlalchemy import DateTime, Integer, String, UniqueConstraint, create_engine, select, update, or_, func
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.exc import IntegrityError


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


BUILD_VERSION = "2026-08-11-CUSTOMER-PARTNER-DETAILS-v9.1"


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


class MerchantNotification(Base):
    __tablename__ = "merchant_sale_notifications"
    __table_args__ = (
        UniqueConstraint(
            "order_id",
            "product_id",
            "merchant_phone",
            name="uq_merchant_sale_notification",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String(100), index=True)
    product_id: Mapped[str] = mapped_column(String(100), index=True)
    merchant_phone: Mapped[str] = mapped_column(String(30), index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)


class MerchantRedemptionNotification(Base):
    __tablename__ = "merchant_redemption_notifications"
    __table_args__ = (
        UniqueConstraint(
            "voucher_id",
            "merchant_phone",
            name="uq_merchant_redemption_notification",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    voucher_id: Mapped[int] = mapped_column(Integer, index=True)
    merchant_phone: Mapped[str] = mapped_column(String(30), index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)


class CustomerNotification(Base):
    __tablename__ = "customer_notifications"
    __table_args__ = (
        UniqueConstraint("voucher_id", "notification_type", name="uq_customer_notification_voucher_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    voucher_id: Mapped[int] = mapped_column(Integer, index=True)
    notification_type: Mapped[str] = mapped_column(String(40), index=True)
    customer_phone: Mapped[str] = mapped_column(String(30), index=True)
    message_body: Mapped[str] = mapped_column(String(5000))
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_error: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    response_value: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    responded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class SallaOAuthCredential(Base):
    __tablename__ = "salla_oauth_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    merchant_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    access_token: Mapped[str] = mapped_column(String(2048))
    refresh_token: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    scope: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    token_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


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
    from app.jood_whatsapp_context import ensure_jood_whatsapp_context_schema

    ensure_jood_whatsapp_context_schema()
    # Populate the audit table for vouchers created before audit logging was added.
    # The operation is idempotent, so every deployment can run it safely.
    with SessionLocal() as db:
        backfill_audit_logs(db)
    yield


app = FastAPI(title="Pakgat Voucher System", version="3.0", lifespan=lifespan)

BASE_URL = env("PUBLIC_BASE_URL", "https://pakgat-voucher-system.onrender.com").rstrip("/")
SALLA_WEBHOOK_SECRET = env("SALLA_WEBHOOK_SECRET")
SALLA_ACCESS_TOKEN = env("SALLA_ACCESS_TOKEN")
SALLA_CLIENT_ID = env("SALLA_CLIENT_ID")
SALLA_CLIENT_SECRET = env("SALLA_CLIENT_SECRET")
SALLA_OAUTH_TOKEN_URL = env("SALLA_OAUTH_TOKEN_URL", "https://accounts.salla.sa/oauth2/token")
SALLA_API_BASE_URL = env("SALLA_API_BASE_URL", "https://api.salla.dev/admin/v2").rstrip("/")
ADMIN_USERNAME = env("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = env("ADMIN_PASSWORD")
ADMIN_SECRET = env("ADMIN_SECRET", SALLA_WEBHOOK_SECRET or "change-this-admin-secret")
COOKIE_SECURE = env("COOKIE_SECURE", "true").lower() != "false"

try:
    MERCHANT_CODES = json.loads(env("MERCHANT_CODES", "{}"))
except json.JSONDecodeError:
    MERCHANT_CODES = {}

VOUCHER_SKU_PREFIX = env("VOUCHER_SKU_PREFIX", "PKG-QR").upper()
WHATSLOOP_API_BASE_URL = env("WHATSLOOP_API_BASE_URL").rstrip("/")
WHATSLOOP_API_TOKEN = env("WHATSLOOP_API_TOKEN")

MERCHANT_PHONE_FIELD_LABELS = {
    "رقم جوال استقبال القسائم",
    "رقم جوال استلام القسائم",
    "جوال استقبال القسائم",
    "merchant voucher phone",
}
PARTNER_NAME_FIELD_LABELS = {
    "اسم الشريك",
    "اسم التاجر",
    "partner name",
}
PARTNER_HOURS_FIELD_LABELS = {
    "ساعات العمل",
    "اوقات العمل",
    "أوقات العمل",
    "مواعيد العمل",
    "working hours",
    "business hours",
}
PARTNER_CONTACT_FIELD_LABELS = {
    "رقم التواصل",
    "رقم الاتصال",
    "جوال التواصل",
    "هاتف التواصل",
    "contact number",
    "contact phone",
}
PARTNER_ADDRESS_FIELD_LABELS = {
    "العنوان",
    "عنوان الشريك",
    "عنوان التاجر",
    "عنوان الفرع",
    "العنوان المختصر",
    "address",
    "partner address",
    "branch address",
}
PARTNER_MAP_FIELD_LABELS = {
    "رابط خرائط Google",
    "رابط خرائط جوجل",
    "رابط الموقع",
    "رابط اللوكيشن",
    "موقع خرائط جوجل",
    "google maps link",
    "google map link",
}
MERCHANT_NOTIFICATION_PIN = (
    env("MERCHANT_NOTIFICATION_PIN")
    or str(MERCHANT_CODES.get("Pakgat") or MERCHANT_CODES.get("*") or "")
).strip()


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
    items = first_value(
        data,
        "items",
        "products",
        "order.items",
        "order.products",
    ) or []
    return items if isinstance(items, list) else []


def item_product_id(item: dict) -> str:
    return str(first_value(item, "product.id", "product_id", "id") or "")


def item_product_name(item: dict) -> str:
    return str(first_value(item, "product.name", "name", "product_name") or "عرض بكجات")


def item_sku(item: dict) -> str:
    """Read the product SKU from the common Salla webhook item shapes."""
    return str(
        first_value(
            item,
            "sku",
            "product.sku",
            "product.sku_code",
            "variant.sku",
            "product.variant.sku",
            "code",
        )
        or ""
    ).strip()


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


def normalize_metadata_label(value) -> str:
    text = str(value or "").strip().lower()
    for old, new in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ى", "ي"), ("ة", "ه")):
        text = text.replace(old, new)
    return "".join(ch for ch in text if ch.isalnum())


def scalar_text(value) -> Optional[str]:
    if value in (None, ""):
        return None
    if isinstance(value, (str, int, float)):
        return str(value).strip() or None
    if isinstance(value, dict):
        for key in ("value", "text", "content", "name", "label", "title"):
            candidate = value.get(key)
            if isinstance(candidate, (str, int, float)) and str(candidate).strip():
                return str(candidate).strip()
    return None


def find_labeled_metadata_value(obj, target_labels: set[str]) -> Optional[str]:
    """Find a product custom-field value across common Salla metadata shapes."""
    targets = {normalize_metadata_label(label) for label in target_labels}

    def walk(node) -> Optional[str]:
        if isinstance(node, dict):
            # Shape 1: {"رقم جوال استقبال القسائم": "05..."}
            for key, value in node.items():
                if normalize_metadata_label(key) in targets:
                    candidate = scalar_text(value)
                    if candidate:
                        return candidate

            # Shape 2: {"label"/"name"/"title": "...", "value": "..."}
            label = None
            for label_key in ("label", "name", "title", "key", "field_name"):
                candidate = node.get(label_key)
                if isinstance(candidate, str) and candidate.strip():
                    label = candidate
                    break
            if label and normalize_metadata_label(label) in targets:
                for value_key in ("value", "field_value", "content", "text", "display_value"):
                    candidate = scalar_text(node.get(value_key))
                    if candidate:
                        return candidate

            for value in node.values():
                found = walk(value)
                if found:
                    return found
        elif isinstance(node, list):
            for value in node:
                found = walk(value)
                if found:
                    return found
        return None

    return walk(obj)


def merchant_phone_candidates(raw_value: Optional[str]) -> list[str]:
    if not raw_value:
        return []
    # Accept one or two Saudi phone numbers even if the merchant enters spaces,
    # commas, Arabic commas, plus signs, or line breaks in the custom field.
    chunks = re.findall(r"(?:\+?966|00966|0)?5\d{8}", str(raw_value).replace(" ", ""))
    phones: list[str] = []
    for chunk in chunks:
        phone = normalize_saudi_phone(chunk)
        if phone and phone not in phones:
            phones.append(phone)
        if len(phones) >= 2:
            break
    return phones


def masked_phone(phone: str) -> str:
    value = str(phone or "")
    if len(value) <= 4:
        return "****"
    return "*" * max(0, len(value) - 4) + value[-4:]


def metadata_debug_paths(obj) -> list[str]:
    """Return only metadata-like key paths; never log customer payload values."""
    results: list[str] = []
    keywords = ("metadata", "custom", "field", "section", "attribute", "detail")

    def walk(node, path: str = "item") -> None:
        if len(results) >= 12:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                child = f"{path}.{key}"
                low = str(key).lower()
                if any(word in low for word in keywords):
                    results.append(child)
                walk(value, child)
        elif isinstance(node, list):
            for index, value in enumerate(node[:8]):
                walk(value, f"{path}[{index}]")

    walk(obj)
    return results[:12]


def parse_salla_expiry(value) -> Optional[datetime]:
    """Normalize Salla token expiry values.

    app.store.authorize documents `expires` as a Unix timestamp. Token refresh
    responses can also use relative seconds, so both shapes are accepted.
    """
    if value in (None, ""):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric > 1_000_000_000:
        return datetime.fromtimestamp(numeric, tz=timezone.utc)
    if numeric > 0:
        return now_utc() + timedelta(seconds=numeric)
    return None


def payload_merchant_id(payload: dict) -> str:
    merchant = payload.get("merchant")
    if isinstance(merchant, dict):
        merchant = merchant.get("id") or merchant.get("merchant_id") or merchant.get("store_id")
    if merchant in (None, ""):
        merchant = first_value(
            payload,
            "data.merchant.id",
            "data.merchant_id",
            "data.store.id",
            "data.store_id",
        )
    return str(merchant or "").strip()


def store_salla_authorization(db: Session, payload: dict) -> tuple[bool, str]:
    """Persist Easy Mode OAuth credentials without ever logging token values."""
    merchant_id = payload_merchant_id(payload)
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        return False, "authorization payload data is invalid"

    access_token = str(data.get("access_token") or "").strip()
    refresh_token = str(data.get("refresh_token") or "").strip() or None
    scope = str(data.get("scope") or "").strip() or None
    token_type = str(data.get("token_type") or "bearer").strip() or "bearer"
    expires_at = parse_salla_expiry(data.get("expires") or data.get("expires_in"))

    if not merchant_id:
        return False, "merchant id is missing"
    if not access_token:
        return False, "access token is missing"

    credential = db.scalar(
        select(SallaOAuthCredential).where(SallaOAuthCredential.merchant_id == merchant_id)
    )
    if credential:
        credential.access_token = access_token
        credential.refresh_token = refresh_token or credential.refresh_token
        credential.scope = scope
        credential.token_type = token_type
        credential.expires_at = expires_at
        credential.updated_at = now_utc()
    else:
        credential = SallaOAuthCredential(
            merchant_id=merchant_id,
            access_token=access_token,
            refresh_token=refresh_token,
            scope=scope,
            token_type=token_type,
            expires_at=expires_at,
            created_at=now_utc(),
            updated_at=now_utc(),
        )
        db.add(credential)
    db.commit()
    return True, merchant_id


def latest_salla_credential(db: Session, merchant_id: str = "") -> Optional[SallaOAuthCredential]:
    if merchant_id:
        row = db.scalar(
            select(SallaOAuthCredential).where(SallaOAuthCredential.merchant_id == merchant_id)
        )
        if row:
            return row
    return db.scalar(
        select(SallaOAuthCredential).order_by(SallaOAuthCredential.updated_at.desc()).limit(1)
    )


def refresh_salla_credential(merchant_id: str) -> tuple[Optional[str], Optional[str]]:
    """Refresh one merchant token under a database row lock.

    Salla refresh tokens are single-use. `FOR UPDATE` prevents two workers from
    consuming the same refresh token in parallel.
    """
    if not SALLA_CLIENT_ID or not SALLA_CLIENT_SECRET:
        return None, "SALLA_CLIENT_ID/SALLA_CLIENT_SECRET are not configured"

    with SessionLocal() as refresh_db:
        stmt = select(SallaOAuthCredential)
        if merchant_id:
            stmt = stmt.where(SallaOAuthCredential.merchant_id == merchant_id)
        stmt = stmt.order_by(SallaOAuthCredential.updated_at.desc()).with_for_update()
        credential = refresh_db.scalar(stmt)
        if not credential:
            return None, "stored Salla authorization was not found"

        # Another worker may have refreshed while this worker waited for the lock.
        if credential.expires_at and credential.expires_at > now_utc() + timedelta(minutes=5):
            return credential.access_token, None
        if not credential.refresh_token:
            return None, "stored Salla refresh token is missing"

        body = urlencode(
            {
                "grant_type": "refresh_token",
                "refresh_token": credential.refresh_token,
                "client_id": SALLA_CLIENT_ID,
                "client_secret": SALLA_CLIENT_SECRET,
            }
        ).encode("utf-8")
        req = UrlRequest(
            SALLA_OAUTH_TOKEN_URL,
            data=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                "X-Pakgat-App": "530632947",
            },
            method="POST",
        )
        try:
            with urlopen(req, timeout=12) as response:
                raw = response.read().decode("utf-8", errors="replace")
            payload = json.loads(raw)
        except HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace")
            return None, f"OAuth refresh HTTP {exc.code}: {response_body[:180]}"
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            return None, f"OAuth refresh {type(exc).__name__}: {exc}"

        new_access = str(payload.get("access_token") or "").strip()
        new_refresh = str(payload.get("refresh_token") or "").strip()
        if not new_access:
            return None, "OAuth refresh response did not contain access_token"

        credential.access_token = new_access
        if new_refresh:
            credential.refresh_token = new_refresh
        credential.scope = str(payload.get("scope") or credential.scope or "").strip() or None
        credential.token_type = str(payload.get("token_type") or credential.token_type or "bearer")
        credential.expires_at = parse_salla_expiry(
            payload.get("expires") or payload.get("expires_in")
        )
        credential.updated_at = now_utc()
        refresh_db.commit()
        return new_access, None


def salla_access_token_for(db: Session, merchant_id: str = "") -> tuple[Optional[str], Optional[str], str]:
    credential = latest_salla_credential(db, merchant_id)
    if credential:
        if credential.expires_at and credential.expires_at <= now_utc() + timedelta(minutes=5):
            token, error = refresh_salla_credential(credential.merchant_id)
            if token:
                return token, None, "database_refreshed"
            return None, error, "database"
        return credential.access_token, None, "database"
    if SALLA_ACCESS_TOKEN:
        return SALLA_ACCESS_TOKEN, None, "environment"
    return None, "Salla access token is not available", "none"


def fetch_salla_json_endpoint(
    db: Session,
    path: str,
    merchant_id: str = "",
) -> tuple[Optional[object], Optional[str]]:
    """GET a Salla Merchant API endpoint using stored OAuth credentials."""
    token, token_error, token_source = salla_access_token_for(db, merchant_id)
    if not token:
        return None, token_error or "Salla access token is unavailable"

    url = f"{SALLA_API_BASE_URL}{path}"

    def request_with(active_token: str):
        req = UrlRequest(
            url,
            headers={
                "Authorization": f"Bearer {active_token}",
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                "X-Pakgat-App": "530632947",
            },
            method="GET",
        )
        with urlopen(req, timeout=10) as response:
            raw = response.read().decode("utf-8", errors="replace")
        return json.loads(raw)

    try:
        return request_with(token), None
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if exc.code == 401 and token_source.startswith("database"):
            refreshed, refresh_error = refresh_salla_credential(merchant_id)
            if refreshed:
                try:
                    return request_with(refreshed), None
                except HTTPError as retry_exc:
                    retry_body = retry_exc.read().decode("utf-8", errors="replace")
                    return None, f"HTTP {retry_exc.code} after refresh: {retry_body[:180]}"
                except (URLError, TimeoutError, OSError, ValueError) as retry_exc:
                    return None, f"retry {type(retry_exc).__name__}: {retry_exc}"
            return None, refresh_error or f"HTTP 401: {body[:180]}"
        return None, f"HTTP {exc.code}: {body[:180]}"
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def metadata_definition_summary(payload: object) -> list[dict]:
    """Return non-secret product metadata definitions for diagnostics."""
    data = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(data, list):
        return []
    out = []
    for group in data:
        if not isinstance(group, dict):
            continue
        fields = []
        for field in group.get("fields") or []:
            if isinstance(field, dict):
                fields.append({
                    "id": str(field.get("id") or ""),
                    "name": str(field.get("name") or ""),
                    "type": str(field.get("type") or ""),
                })
        out.append({
            "id": str(group.get("id") or ""),
            "name": str(group.get("name") or ""),
            "visible": group.get("visible"),
            "owner": str(group.get("owner") or ""),
            "fields": fields,
        })
    return out


def diagnostic_key_paths(obj: object, limit: int = 80) -> list[str]:
    """List object key paths only (never values/tokens) for safe diagnostics."""
    paths: list[str] = []
    def walk(value, path=""):
        if len(paths) >= limit:
            return
        if isinstance(value, dict):
            for key, child in value.items():
                current = f"{path}.{key}" if path else str(key)
                paths.append(current)
                walk(child, current)
                if len(paths) >= limit:
                    return
        elif isinstance(value, list):
            for i, child in enumerate(value[:3]):
                walk(child, f"{path}[{i}]")
                if len(paths) >= limit:
                    return
    walk(obj)
    return paths[:limit]


def fetch_salla_product_metadata(
    db: Session,
    product_id: str,
    merchant_id: str = "",
) -> tuple[Optional[object], Optional[str]]:
    """Read hidden Salla product metadata using the stored Easy Mode token."""
    if not product_id:
        return None, "product_id is missing"

    token, token_error, token_source = salla_access_token_for(db, merchant_id)
    if not token:
        return None, token_error or "Salla access token is unavailable"

    url = f"{SALLA_API_BASE_URL}/metadata/values/product/{quote(str(product_id), safe='')}"

    def request_with(active_token: str):
        req = UrlRequest(
            url,
            headers={
                "Authorization": f"Bearer {active_token}",
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                "X-Pakgat-App": "530632947",
            },
            method="GET",
        )
        with urlopen(req, timeout=10) as response:
            raw = response.read().decode("utf-8", errors="replace")
        payload = json.loads(raw)
        if isinstance(payload, dict) and "data" in payload:
            return payload.get("data")
        return payload

    try:
        return request_with(token), None
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        # If a stored OAuth access token was revoked/expired unexpectedly, refresh
        # exactly once and retry. Environment-only tokens cannot be refreshed.
        if exc.code == 401 and token_source.startswith("database"):
            refreshed, refresh_error = refresh_salla_credential(merchant_id)
            if refreshed:
                try:
                    return request_with(refreshed), None
                except HTTPError as retry_exc:
                    retry_body = retry_exc.read().decode("utf-8", errors="replace")
                    return None, f"HTTP {retry_exc.code} after refresh: {retry_body[:180]}"
                except (URLError, TimeoutError, OSError, ValueError) as retry_exc:
                    return None, f"retry {type(retry_exc).__name__}: {retry_exc}"
            return None, refresh_error or f"HTTP 401: {body[:180]}"
        return None, f"HTTP {exc.code}: {body[:180]}"
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


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



def normalize_saudi_phone(phone: str) -> str:
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    if digits.startswith("00966"):
        digits = digits[2:]
    elif digits.startswith("05") and len(digits) == 10:
        digits = "966" + digits[1:]
    elif digits.startswith("5") and len(digits) == 9:
        digits = "966" + digits
    return digits


def build_voucher_whatsapp_message(
    customer_name: str,
    product_name: str,
    voucher_code: str,
    order_id: str,
    verification_url: str,
    partner_name: Optional[str] = None,
    partner_hours: Optional[str] = None,
    partner_contact: Optional[str] = None,
    partner_address: Optional[str] = None,
    partner_map_url: Optional[str] = None,
) -> str:
    """Build the single customer purchase message used by production and admin tests."""
    name = (customer_name or "عميل بكجات").strip()

    partner_lines: list[str] = []
    if partner_name and str(partner_name).strip():
        partner_lines.append(f"مقدم الخدمة: {str(partner_name).strip()}")
    if partner_hours and str(partner_hours).strip():
        partner_lines.append(f"ساعات العمل: {str(partner_hours).strip()}")
    if partner_contact and str(partner_contact).strip():
        partner_lines.append(f"التواصل: {str(partner_contact).strip()}")
    if partner_address and str(partner_address).strip():
        partner_lines.append(f"العنوان: {str(partner_address).strip()}")
    if partner_map_url and str(partner_map_url).strip():
        partner_lines.append(f"الموقع: {str(partner_map_url).strip()}")
    partner_block = ("\n".join(partner_lines) + "\n\n") if partner_lines else ""

    return (
        "✅ قسيمتك جاهزة\n\n"
        f"مرحباً {name}\n"
        "تم إصدار قسيمتك بنجاح.\n"
        "كود VIP: خصم 5% على طلبك القادم.\n\n"
        f"العرض: {product_name}\n"
        f"القسيمة: {voucher_code}\n"
        f"الطلب: {order_id}\n\n"
        "افتح قسيمتك واعرضها للتاجر عند استلام الخدمة:\n"
        f"{verification_url}\n\n"
        + partner_block
        + "🔒 قسيمتك مسؤوليتك — اعرضها للتاجر فقط.\n\n"
        "https://pakgat.com\n"
        "بدون قروشة.. بكجات تضبطك\n\n"
        "للتأكد أن القسيمة وصلتك، رد برقم واحد فقط:\n"
        "1 — وصلتني القسيمة\n"
        "2 — أحتاج مساعدة من خدمة العملاء"
    )


def ensure_customer_notification(
    db: Session,
    voucher: Voucher,
    notification_type: str,
    message_body: str,
    *,
    commit: bool = True,
) -> Optional[CustomerNotification]:
    phone = normalize_saudi_phone(voucher.customer_phone or "")
    if not phone:
        return None
    existing = db.scalar(
        select(CustomerNotification).where(
            CustomerNotification.voucher_id == voucher.id,
            CustomerNotification.notification_type == notification_type,
        )
    )
    if existing:
        return existing
    notification = CustomerNotification(
        voucher_id=voucher.id,
        notification_type=notification_type,
        customer_phone=phone,
        message_body=message_body,
        status="queued",
    )
    db.add(notification)
    try:
        if commit:
            db.commit()
            db.refresh(notification)
        else:
            db.flush()
        return notification
    except IntegrityError:
        db.rollback()
        return db.scalar(
            select(CustomerNotification).where(
                CustomerNotification.voucher_id == voucher.id,
                CustomerNotification.notification_type == notification_type,
            )
        )


def send_voucher_whatsapp(
    voucher_id: int,
    customer_phone: str,
    customer_name: str,
    product_name: str,
    voucher_code: str,
    order_id: str,
    verification_url: str,
    partner_name: Optional[str] = None,
    partner_hours: Optional[str] = None,
    partner_contact: Optional[str] = None,
    partner_address: Optional[str] = None,
    partner_map_url: Optional[str] = None,
) -> None:
    phone = normalize_saudi_phone(customer_phone)

    if not phone:
        with SessionLocal() as db:
            log_event(db, "whatsapp_skipped", voucher_id, "Customer phone is missing.")
        return

    if not WHATSLOOP_API_BASE_URL or not WHATSLOOP_API_TOKEN:
        with SessionLocal() as db:
            log_event(db, "whatsapp_skipped", voucher_id, "WhatsLoop environment variables are missing.")
        return

    message = build_voucher_whatsapp_message(
        customer_name=customer_name,
        product_name=product_name,
        voucher_code=voucher_code,
        order_id=order_id,
        verification_url=verification_url,
        partner_name=partner_name,
        partner_hours=partner_hours,
        partner_contact=partner_contact,
        partner_address=partner_address,
        partner_map_url=partner_map_url,
    )

    body = json.dumps(
        {"to": phone, "message": message},
        ensure_ascii=False,
    ).encode("utf-8")

    req = UrlRequest(
        f"{WHATSLOOP_API_BASE_URL}/messages/send-text",
        data=body,
        headers={
            "Authorization": f"Bearer {WHATSLOOP_API_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(req, timeout=25) as response:
            response_text = response.read().decode("utf-8", errors="replace")
            status_code = getattr(response, "status", response.getcode())

        with SessionLocal() as db:
            log_event(
                db,
                "whatsapp_sent",
                voucher_id,
                f"phone={phone}; http_status={status_code}; response={response_text[:260]}",
            )
    except HTTPError as exc:
        error_text = exc.read().decode("utf-8", errors="replace")
        with SessionLocal() as db:
            log_event(
                db,
                "whatsapp_failed",
                voucher_id,
                f"phone={phone}; http_status={exc.code}; response={error_text[:260]}",
            )
    except (URLError, TimeoutError, OSError) as exc:
        with SessionLocal() as db:
            log_event(
                db,
                "whatsapp_failed",
                voucher_id,
                f"phone={phone}; error={type(exc).__name__}: {exc}",
            )

def build_redemption_whatsapp_message(
    customer_name: str,
    product_name: str,
    voucher_code: str,
    order_id: str,
    merchant_name: str,
    redeemed_at: datetime,
) -> str:
    name = (customer_name or "عميل بكجات").strip()
    display_order_id = str(order_id or "").split(":", 1)[0]
    used_at = fmt_dt(redeemed_at)
    return (
        "✅ تم استبدال قسيمتك بنجاح\n\n"
        f"مرحباً {name} 🎁\n\n"
        f"تم تأكيد استلامك للخدمة لدى {merchant_name}.\n\n"
        f"🎟️ العرض: {product_name}\n"
        f"🔖 رقم القسيمة: {voucher_code}\n"
        f"📦 رقم الطلب: {display_order_id}\n"
        f"🕒 وقت الاستخدام: {used_at}\n\n"
        "⭐ وبما أنك أصبحت من عملاء Pakgat، فأنت الآن VIP عندنا.\n\n"
        "🎁 استمتع بخصم 5% على طلبك القادم باستخدام الكود: VIP\n\n"
        "اكتشف عرضك القادم:\n"
        "https://pakgat.com\n\n"
        "نتمنى أن تكون تجربتك ناجحة، ونسعد بخدمتك مرة أخرى 💙\n\n"
        "كيف كانت تجربتك؟ قيّمها من 1 إلى 5، حيث 5 ممتازة.\n\n"
        "شكراً لاختيارك Pakgat\n"
        "بدون قروشة.. بكجات تضبطك ✨"
    )


def send_redemption_whatsapp(
    voucher_id: int,
    customer_phone: str,
    customer_name: str,
    product_name: str,
    voucher_code: str,
    order_id: str,
    merchant_name: str,
    redeemed_at: datetime,
) -> None:
    """Legacy direct sender retained for compatibility; outbox code does not schedule it."""
    phone = normalize_saudi_phone(customer_phone)
    if not phone or not WHATSLOOP_API_BASE_URL or not WHATSLOOP_API_TOKEN:
        return
    message = build_redemption_whatsapp_message(
        customer_name, product_name, voucher_code, order_id, merchant_name, redeemed_at
    )

    body = json.dumps(
        {"to": phone, "message": message},
        ensure_ascii=False,
    ).encode("utf-8")

    req = UrlRequest(
        f"{WHATSLOOP_API_BASE_URL}/messages/send-text",
        data=body,
        headers={
            "Authorization": f"Bearer {WHATSLOOP_API_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(req, timeout=25) as response:
            response_text = response.read().decode("utf-8", errors="replace")
            status_code = getattr(response, "status", response.getcode())

        with SessionLocal() as db:
            log_event(
                db,
                "redemption_whatsapp_sent",
                voucher_id,
                f"phone={phone}; http_status={status_code}; response={response_text[:260]}",
            )
    except HTTPError as exc:
        error_text = exc.read().decode("utf-8", errors="replace")
        with SessionLocal() as db:
            log_event(
                db,
                "redemption_whatsapp_failed",
                voucher_id,
                f"phone={phone}; http_status={exc.code}; response={error_text[:260]}",
            )
    except (URLError, TimeoutError, OSError) as exc:
        with SessionLocal() as db:
            log_event(
                db,
                "redemption_whatsapp_failed",
                voucher_id,
                f"phone={phone}; error={type(exc).__name__}: {exc}",
            )



def reserve_merchant_notification(
    db: Session,
    order_id: str,
    product_id: str,
    merchant_phone: str,
) -> Optional[int]:
    existing = db.scalar(
        select(MerchantNotification).where(
            MerchantNotification.order_id == order_id,
            MerchantNotification.product_id == product_id,
            MerchantNotification.merchant_phone == merchant_phone,
        )
    )
    if existing:
        if existing.status == "failed":
            existing.status = "queued"
            existing.last_error = None
            db.commit()
            return existing.id
        return None

    notification = MerchantNotification(
        order_id=order_id,
        product_id=product_id,
        merchant_phone=merchant_phone,
        status="queued",
    )
    db.add(notification)
    try:
        db.commit()
        db.refresh(notification)
        return notification.id
    except IntegrityError:
        db.rollback()
        return None


def send_merchant_sale_whatsapp(
    notification_id: int,
    merchant_phone: str,
    merchant_name: str,
    product_name: str,
    order_id: str,
    quantity: int,
    voucher_count: int,
    test_mode: bool = False,
) -> None:
    phone = normalize_saudi_phone(merchant_phone)
    partner = (merchant_name or "شريك Pakgat").strip()
    sent_action = "merchant_whatsapp_test_sent" if test_mode else "merchant_whatsapp_sent"
    failed_action = "merchant_whatsapp_test_failed" if test_mode else "merchant_whatsapp_failed"

    if not phone:
        with SessionLocal() as db:
            row = db.get(MerchantNotification, notification_id)
            if row:
                row.status = "failed"
                row.last_error = "Merchant phone is invalid."
                db.commit()
            log_event(db, failed_action, details=f"order={order_id}; invalid merchant phone")
        return

    if not WHATSLOOP_API_BASE_URL or not WHATSLOOP_API_TOKEN:
        with SessionLocal() as db:
            row = db.get(MerchantNotification, notification_id)
            if row:
                row.status = "failed"
                row.last_error = "WhatsLoop environment variables are missing."
                db.commit()
            log_event(db, failed_action, details=f"order={order_id}; WhatsLoop config missing")
        return

    if not MERCHANT_NOTIFICATION_PIN:
        with SessionLocal() as db:
            row = db.get(MerchantNotification, notification_id)
            if row:
                row.status = "failed"
                row.last_error = "Merchant PIN is not configured."
                db.commit()
            log_event(db, failed_action, details=f"order={order_id}; merchant PIN config missing")
        return

    test_prefix = "🧪 رسالة اختبار من Pakgat — لا يوجد طلب حقيقي\n\n" if test_mode else ""
    message = (
        test_prefix
        + f"🎉 تم بيع *{product_name}* عبر Pakgat\n\n"
        f"مرحباً {partner}\n\n"
        f"تم شراء *{product_name}* بنجاح عبر *Pakgat*.\n\n"
        f"📦 رقم الطلب: {order_id}\n"
        f"🔢 الكمية: {quantity}\n"
        f"🎫 عدد القسائم: {voucher_count}\n\n"
        "القسيمة أصبحت جاهزة لدى العميل، وسيقوم بعرض رمز QR *قبل استلام الخدمة*.\n\n"
        f"🔐 *الرقم السري لتأكيد استلام الخدمة: {MERCHANT_NOTIFICATION_PIN}*\n\n"
        "يتم تأكيد استلام الخدمة عند حضور العميل وعرض رمز QR الخاص بالقسيمة.\n\n"
        "شكراً لشراكتكم مع *Pakgat* 💙"
    )

    body = json.dumps({"to": phone, "message": message}, ensure_ascii=False).encode("utf-8")
    req = UrlRequest(
        f"{WHATSLOOP_API_BASE_URL}/messages/send-text",
        data=body,
        headers={
            "Authorization": f"Bearer {WHATSLOOP_API_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(req, timeout=25) as response:
            response_text = response.read().decode("utf-8", errors="replace")
            status_code = getattr(response, "status", response.getcode())
        with SessionLocal() as db:
            row = db.get(MerchantNotification, notification_id)
            if row:
                row.status = "sent"
                row.sent_at = now_utc()
                row.last_error = None
                db.commit()
            log_event(
                db,
                sent_action,
                details=(
                    f"order={order_id}; phone={masked_phone(phone)}; "
                    f"http_status={status_code}; response={response_text[:180]}"
                ),
            )
    except HTTPError as exc:
        error_text = exc.read().decode("utf-8", errors="replace")
        with SessionLocal() as db:
            row = db.get(MerchantNotification, notification_id)
            if row:
                row.status = "failed"
                row.last_error = f"HTTP {exc.code}: {error_text[:350]}"
                db.commit()
            log_event(
                db,
                failed_action,
                details=f"order={order_id}; phone={masked_phone(phone)}; http_status={exc.code}",
            )
    except (URLError, TimeoutError, OSError) as exc:
        with SessionLocal() as db:
            row = db.get(MerchantNotification, notification_id)
            if row:
                row.status = "failed"
                row.last_error = f"{type(exc).__name__}: {exc}"[:500]
                db.commit()
            log_event(
                db,
                failed_action,
                details=f"order={order_id}; phone={masked_phone(phone)}; error={type(exc).__name__}",
            )


def reserve_merchant_redemption_notification(
    db: Session,
    voucher_id: int,
    merchant_phone: str,
) -> Optional[int]:
    existing = db.scalar(
        select(MerchantRedemptionNotification).where(
            MerchantRedemptionNotification.voucher_id == voucher_id,
            MerchantRedemptionNotification.merchant_phone == merchant_phone,
        )
    )
    if existing:
        if existing.status == "failed":
            existing.status = "queued"
            existing.last_error = None
            db.commit()
            return existing.id
        return None

    notification = MerchantRedemptionNotification(
        voucher_id=voucher_id,
        merchant_phone=merchant_phone,
        status="queued",
    )
    db.add(notification)
    try:
        db.commit()
        db.refresh(notification)
        return notification.id
    except IntegrityError:
        db.rollback()
        return None


def merchant_redemption_context(db: Session, voucher: Voucher) -> tuple[list[str], str, str]:
    """Resolve merchant phones/name after a successful redemption.

    Prefer the already-known phone(s) from the sale notification rows. Then use
    Salla product metadata as a fallback and to resolve the partner display name.
    """
    base_order_id = str(voucher.order_id or "").split(":", 1)[0]
    phones: list[str] = []

    sale_rows = db.scalars(
        select(MerchantNotification).where(
            MerchantNotification.order_id == base_order_id,
            MerchantNotification.product_id == str(voucher.product_id or ""),
        )
    ).all()
    for row in sale_rows:
        phone = normalize_saudi_phone(row.merchant_phone)
        if phone and phone not in phones:
            phones.append(phone)

    partner_name = ""
    metadata_payload = None
    metadata_error = None
    product_id = str(voucher.product_id or "").strip()
    if product_id:
        metadata_payload, metadata_error = fetch_salla_json_endpoint(
            db, f"/metadata/values/product/{quote(product_id, safe='')}"
        )
        if metadata_payload is not None:
            partner_name = (
                find_labeled_metadata_value(metadata_payload, PARTNER_NAME_FIELD_LABELS)
                or ""
            ).strip()
            if not phones:
                metadata_phone = find_labeled_metadata_value(
                    metadata_payload, MERCHANT_PHONE_FIELD_LABELS
                )
                for phone in merchant_phone_candidates(metadata_phone):
                    if phone not in phones:
                        phones.append(phone)

    if not phones:
        log_event(
            db,
            "merchant_redemption_phone_not_found",
            voucher.id,
            (
                f"order={base_order_id}; product_id={product_id or 'unknown'}; "
                f"metadata={metadata_error or 'no_phone'}"
            ),
        )

    return phones[:2], partner_name or "شريك Pakgat", base_order_id


def send_merchant_redemption_whatsapp(
    notification_id: Optional[int],
    voucher_id: Optional[int],
    merchant_phone: str,
    merchant_name: str,
    product_name: str,
    voucher_code: str,
    order_id: str,
    redeemed_at: datetime,
    test_mode: bool = False,
) -> bool:
    phone = normalize_saudi_phone(merchant_phone)
    partner = (merchant_name or "شريك Pakgat").strip()
    sent_action = (
        "merchant_redemption_whatsapp_test_sent"
        if test_mode
        else "merchant_redemption_whatsapp_sent"
    )
    failed_action = (
        "merchant_redemption_whatsapp_test_failed"
        if test_mode
        else "merchant_redemption_whatsapp_failed"
    )

    def mark_failed(error: str) -> None:
        with SessionLocal() as log_db:
            if notification_id:
                row = log_db.get(MerchantRedemptionNotification, notification_id)
                if row:
                    row.status = "failed"
                    row.last_error = error[:500]
                    log_db.commit()
            log_event(
                log_db,
                failed_action,
                voucher_id,
                f"order={order_id}; phone={masked_phone(phone)}; {error[:280]}",
            )

    if not phone:
        mark_failed("invalid merchant phone")
        return False
    if not WHATSLOOP_API_BASE_URL or not WHATSLOOP_API_TOKEN:
        mark_failed("WhatsLoop environment variables are missing")
        return False

    used_at = fmt_dt(redeemed_at)
    test_prefix = "🧪 رسالة اختبار من Pakgat — لا يوجد استبدال حقيقي\n\n" if test_mode else ""
    message = (
        test_prefix
        + "✅ تم تأكيد استبدال القسيمة\n\n"
        f"مرحباً {partner}\n\n"
        "تم تأكيد استلام الخدمة بنجاح عبر *Pakgat*.\n\n"
        f"🎟️ العرض: {product_name}\n"
        f"🔖 رقم القسيمة: {voucher_code}\n"
        f"📦 رقم الطلب: {order_id}\n"
        f"🕒 وقت الاستبدال: {used_at}\n\n"
        "أصبحت القسيمة الآن *مستخدمة* ولا يمكن استخدامها مرة أخرى.\n\n"
        "شكراً لشراكتكم مع *Pakgat* 💙\n"
        "بدون قروشة.. بكجات تضبطك ✨"
    )

    body = json.dumps({"to": phone, "message": message}, ensure_ascii=False).encode("utf-8")
    req = UrlRequest(
        f"{WHATSLOOP_API_BASE_URL}/messages/send-text",
        data=body,
        headers={
            "Authorization": f"Bearer {WHATSLOOP_API_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(req, timeout=25) as response:
            response_text = response.read().decode("utf-8", errors="replace")
            status_code = getattr(response, "status", response.getcode())
        with SessionLocal() as log_db:
            if notification_id:
                row = log_db.get(MerchantRedemptionNotification, notification_id)
                if row:
                    row.status = "sent"
                    row.sent_at = now_utc()
   …6295 tokens truncated…pt HTTPException:
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
def admin_redeem_voucher(voucher_id: int, request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    try:
        require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)
    voucher = db.get(Voucher, voucher_id)
    if not voucher:
        raise HTTPException(status_code=404, detail="Voucher not found")
    redeemed_at = now_utc()
    result = db.execute(update(Voucher).where(Voucher.id == voucher_id, Voucher.status == "active", Voucher.expires_at >= redeemed_at).values(status="redeemed", redeemed_at=redeemed_at).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        db.rollback()
        log_event(db, "admin_redeem_failed", voucher_id, "Voucher was not active")
        raise HTTPException(status_code=409, detail="Voucher is not active")
    voucher.status = "redeemed"
    voucher.redeemed_at = redeemed_at
    ensure_customer_notification(
        db,
        voucher,
        "voucher_redeemed",
        build_redemption_whatsapp_message(
        voucher.customer_name or "",
        voucher.product_name,
        voucher.code,
        voucher.order_id,
        voucher.merchant_name,
        redeemed_at,
        ),
        commit=False,
    )
    db.commit()
    db.refresh(voucher)
    log_event(db, "voucher_redeemed", voucher_id, "Redeemed from admin dashboard")
    background_tasks.add_task(notify_merchant_after_redemption, voucher.id)
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
        "salla_order_processed": "معالجة طلب سلة",
        "salla_webhook_received": "استلام Webhook",
        "salla_product_matched": "منتج مؤهل للقسيمة",
        "salla_product_ignored": "منتج غير مؤهل",
        "voucher_already_exists": "قسيمة موجودة مسبقًا",
        "whatsapp_sent": "إرسال القسيمة عبر واتساب",
        "whatsapp_failed": "فشل إرسال واتساب",
        "whatsapp_skipped": "تجاوز إرسال واتساب",
        "redemption_whatsapp_sent": "إرسال تأكيد الاستخدام عبر واتساب",
        "redemption_whatsapp_failed": "فشل إرسال تأكيد الاستخدام",
        "redemption_whatsapp_skipped": "تجاوز تأكيد الاستخدام عبر واتساب",
        "merchant_phone_found": "تم العثور على جوال الشريك",
        "merchant_phone_not_found": "لم يتم العثور على جوال الشريك",
        "merchant_whatsapp_sent": "إرسال إشعار البيع للشريك",
        "merchant_whatsapp_failed": "فشل إرسال إشعار البيع للشريك",
        "merchant_whatsapp_test_sent": "اختبار إرسال واتساب للشريك",
        "merchant_whatsapp_test_failed": "فشل اختبار واتساب للشريك",
        "merchant_whatsapp_duplicate_skipped": "تجاوز إشعار شريك مكرر",
        "merchant_redemption_whatsapp_sent": "إرسال تأكيد الاستبدال للشريك",
        "merchant_redemption_whatsapp_failed": "فشل تأكيد الاستبدال للشريك",
        "merchant_redemption_whatsapp_test_sent": "اختبار تأكيد الاستبدال للشريك",
        "merchant_redemption_whatsapp_test_failed": "فشل اختبار تأكيد الاستبدال للشريك",
        "merchant_redemption_duplicate_skipped": "تجاوز تأكيد استبدال مكرر",
        "merchant_redemption_phone_not_found": "تعذر تحديد جوال الشريك بعد الاستبدال",
        "salla_oauth_authorized": "حفظ تفويض سلة",
        "salla_oauth_failed": "فشل حفظ تفويض سلة",
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
    products_ready = bool(VOUCHER_SKU_PREFIX)
    smtp_ready = all(env(k) for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM"))
    def state(ok: bool) -> str:
        return "<span class='badge badge-active'>جاهز</span>" if ok else "<span class='badge badge-expired'>يحتاج إعداد</span>"
    webhook_url = BASE_URL + "/webhooks/salla"
    body = f"""<main class='wrap' style='padding:28px 0 48px'><h1>تكامل سلة</h1><div class='grid grid-mobile-1' style='grid-template-columns:repeat(3,1fr);margin-bottom:18px'><div class='card' style='padding:20px'><h3>توقيع Webhook</h3>{state(webhook_ready)}<p class='muted'>SALLA_WEBHOOK_SECRET</p></div><div class='card' style='padding:20px'><h3>منتجات القسائم</h3>{state(products_ready)}<p class='muted'>أي SKU يبدأ بـ {esc(VOUCHER_SKU_PREFIX)}</p></div><div class='card' style='padding:20px'><h3>البريد الإلكتروني</h3>{state(smtp_ready)}<p class='muted'>إرسال رابط القسيمة للعميل</p></div></div><section class='card' style='padding:22px'><h2>رابط Webhook</h2><input class='input' dir='ltr' readonly onclick='this.select()' value='{esc(webhook_url)}'><h2 style='margin-top:24px'>الحدث التشغيلي</h2><p><code>order.updated</code> هو الحدث الرئيسي المعتمد من إعدادات التطبيق، مع دعم <code>order.payment.updated</code> إن وصل. تُصدر القسيمة عند تأكيد الدفع صراحة، أو اكتمال المبلغ المدفوع، أو وصول الطلب إلى الحالة النهائية <code>closed/completed</code> في إعداد المتجر الإلكتروني الحالي.</p><h2 style='margin-top:24px'>تشخيص بيانات الشريك</h2><p><a class='btn btn-blue' href='/admin/merchant-test'>فتح تشخيص المنتج بدون شراء</a></p><h2 style='margin-top:24px'>المسار التشغيلي</h2><p>تحديث الطلب من سلة ← التحقق من الدفع الفعلي ← مطابقة SKU يبدأ بـ PKG-QR ← إنشاء القسيمة وQR مرة واحدة ← ظهورها في لوحة الإدارة وإرسال رابطها بالبريد عند اكتمال SMTP.</p></section></main>"""
    return HTMLResponse(page_shell("تكامل سلة", body, admin=True))


@app.get("/admin/merchant-test", response_class=HTMLResponse)
def admin_merchant_metadata_test(request: Request, product_id: str = "", sku: str = "", db: Session = Depends(get_db)):
    try:
        require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)

    product_id = (product_id or "").strip()
    sku = (sku or "").strip()
    result_box = ""
    if product_id or sku:
        by_id_payload = by_id_error = None
        by_sku_payload = by_sku_error = None
        values_payload = values_error = None

        if product_id:
            by_id_payload, by_id_error = fetch_salla_json_endpoint(
                db, f"/products/{quote(product_id, safe='')}"
            )
            values_payload, values_error = fetch_salla_json_endpoint(
                db, f"/metadata/values/product/{quote(product_id, safe='')}"
            )

        if sku:
            by_sku_payload, by_sku_error = fetch_salla_json_endpoint(
                db, f"/products/sku/{quote(sku, safe='')}"
            )

        # Search only read-only product-side responses for the configured labels.
        raw_phone = None
        partner_name = None
        partner_hours = None
        partner_contact = None
        partner_address = None
        partner_map_url = None
        source = None
        for label, payload in (
            ("product_by_id", by_id_payload),
            ("product_by_sku", by_sku_payload),
            ("metadata_values", values_payload),
        ):
            if payload is None:
                continue
            candidate = find_labeled_metadata_value(payload, MERCHANT_PHONE_FIELD_LABELS)
            if candidate and not raw_phone:
                raw_phone = candidate
                source = label
            if not partner_name:
                partner_name = find_labeled_metadata_value(payload, PARTNER_NAME_FIELD_LABELS)
            if not partner_hours:
                partner_hours = find_labeled_metadata_value(payload, PARTNER_HOURS_FIELD_LABELS)
            if not partner_contact:
                partner_contact = find_labeled_metadata_value(payload, PARTNER_CONTACT_FIELD_LABELS)
            if not partner_address:
                partner_address = find_labeled_metadata_value(payload, PARTNER_ADDRESS_FIELD_LABELS)
            if not partner_map_url:
                partner_map_url = find_labeled_metadata_value(payload, PARTNER_MAP_FIELD_LABELS)

        phones = merchant_phone_candidates(raw_phone)

        # Prefer product data returned by SKU, because it validates the installed store
        # independently from the manually copied admin product ID.
        product_payload = by_sku_payload or by_id_payload
        product_data = product_payload.get("data") if isinstance(product_payload, dict) else product_payload
        if not isinstance(product_data, dict):
            product_data = {}

        api_id = str(product_data.get("id") or "")
        api_name = str(product_data.get("name") or "")
        api_sku = str(product_data.get("sku") or "")
        product_paths = diagnostic_key_paths(product_payload or {})
        values_paths = diagnostic_key_paths(values_payload or {})
        interesting_paths = [
            p for p in product_paths
            if any(word in p.lower() for word in ("metadata", "custom", "field", "section", "detail", "attribute"))
        ]

        errors = []
        if by_id_error:
            errors.append(f"product by id: {by_id_error}")
        if by_sku_error:
            errors.append(f"product by sku: {by_sku_error}")
        if values_error:
            errors.append(f"metadata values: {values_error}")
        errors_html = ""
        if errors:
            errors_html = "<div class='alert alert-error' style='margin-top:14px' dir='ltr'>" + esc(" | ".join(errors)) + "</div>"

        identity_html = (
            "<div class='card' style='padding:20px;margin-top:14px'><h3>هوية المنتج التي أعادتها Salla API</h3>"
            f"<p><strong>Product ID من API:</strong> <span dir='ltr'>{esc(api_id or 'غير موجود')}</span></p>"
            f"<p><strong>SKU من API:</strong> <span dir='ltr'>{esc(api_sku or 'غير موجود')}</span></p>"
            f"<p><strong>اسم المنتج:</strong> {esc(api_name or 'غير موجود')}</p>"
            "</div>"
        )

        if phones:
            phone_rows = "".join(f"<li dir='ltr'><strong>{esc(p)}</strong></li>" for p in phones)
            result_box = (
                "<div class='alert alert-ok'><strong>تم العثور على رقم جوال استقبال القسائم ✅</strong></div>"
                + identity_html
                + "<div class='card' style='padding:20px;margin-top:14px'>"
                f"<p><strong>اسم الشريك:</strong> {esc(partner_name or 'غير موجود')}</p>"
                f"<p><strong>ساعات العمل:</strong> {esc(partner_hours or 'غير موجود')}</p>"
                f"<p><strong>رقم التواصل:</strong> <span dir='ltr'>{esc(partner_contact or 'غير موجود')}</span></p>"
                f"<p><strong>العنوان:</strong> {esc(partner_address or 'غير موجود')}</p>"
                f"<p><strong>رابط خرائط Google:</strong> <span dir='ltr'>{esc(partner_map_url or 'غير موجود')}</span></p>"
                "<p><strong>رقم جوال استقبال القسائم:</strong></p>"
                f"<ul>{phone_rows}</ul>"
                f"<p><strong>مصدر القراءة:</strong> <code>{esc(source or 'unknown')}</code></p>"
                "<p class='muted'>اختبار قراءة فقط؛ أي حقل غير موجود لن يظهر لاحقاً في رسالة العميل.</p>"
                "<form method='post' action='/admin/customer-voucher-notification-test' style='margin-top:18px;padding-top:16px;border-top:1px solid #e5e7eb'>"
                f"<input type='hidden' name='product_id' value='{esc(product_id)}'>"
                f"<input type='hidden' name='sku' value='{esc(sku)}'>"
                "<label><strong>اختبار رسالة العميل النهائية</strong></label>"
                "<input class='input' name='test_phone' dir='ltr' placeholder='05xxxxxxxx' required style='margin-top:8px'>"
                "<button class='btn btn-blue' type='submit' style='margin-top:10px' onclick='return confirm(&quot;سيتم إرسال رسالة واتساب اختبارية إلى الرقم الذي أدخلته. لا يوجد شراء أو قسيمة حقيقية. متابعة؟&quot;);'>إرسال اختبار رسالة العميل</button>"
                "</form>"
                "<form method='post' action='/admin/merchant-notification-test' style='margin-top:14px'>"
                f"<input type='hidden' name='product_id' value='{esc(product_id)}'>"
                f"<input type='hidden' name='sku' value='{esc(sku)}'>"
                "<button class='btn btn-primary' type='submit' onclick='return confirm(&quot;سيتم إرسال رسالة واتساب اختبارية إلى رقم الشريك المقروء من سلة. لا يوجد شراء أو قسيمة. متابعة؟&quot;);'>إرسال اختبار إشعار البيع</button>"
                "</form>"
                "<form method='post' action='/admin/merchant-redemption-notification-test' style='margin-top:10px'>"
                f"<input type='hidden' name='product_id' value='{esc(product_id)}'>"
                f"<input type='hidden' name='sku' value='{esc(sku)}'>"
                "<button class='btn btn-muted' type='submit' onclick='return confirm(&quot;سيتم إرسال رسالة اختبار لتأكيد استبدال القسيمة إلى الشريك. لا يوجد استبدال حقيقي. متابعة؟&quot;);'>إرسال اختبار تأكيد الاستبدال</button>"
                "</form>"
                "</div>" + errors_html
            )
            log_event(db, "merchant_product_test_ok", details=f"product_id={product_id}; sku={sku}; source={source}; phones={','.join(masked_phone(p) for p in phones)}")
        else:
            result_box = (
                "<div class='alert alert-error'><strong>تم فحص المنتج من Merchant API، لكن رقم جوال استقبال القسائم لم يظهر في استجابة المنتج.</strong>"
                "<div style='margin-top:8px'>هذا الاختبار يحدد هل الحقول المخصصة في لوحة سلة تظهر داخل Product API الحالي أم لا.</div></div>"
                + identity_html
                + "<div class='card' style='padding:20px;margin-top:14px'><h3>شكل استجابة المنتج (أسماء المفاتيح فقط)</h3>"
                f"<p><strong>مسارات مرتبطة بالحقول:</strong> <code>{esc(', '.join(interesting_paths[:40]) if interesting_paths else 'لا يوجد')}</code></p>"
                f"<p><strong>Metadata values:</strong> <code>{esc(', '.join(values_paths[:40]) if values_paths else 'لا يوجد')}</code></p>"
                "<p class='muted'>لا يتم عرض Access Token أو Refresh Token أو بيانات العملاء.</p></div>"
                + errors_html
            )
            log_event(db, "merchant_product_diagnostic", details=f"product_id={product_id}; sku={sku}; api_id={api_id}; api_sku={api_sku}; interesting_paths={','.join(interesting_paths[:20]) if interesting_paths else 'none'}")

    body = f"""<main class='wrap' style='padding:28px 0 48px'>
    <section class='card' style='max-width:920px;margin:auto;padding:24px'>
      <h1>تشخيص بيانات الشريك من سلة</h1>
      <p class='muted'>بدون شراء، بدون إنشاء قسيمة، وبدون إرسال واتساب. يستخدم Product Details الرسمي من Salla ويقارن القراءة بالـSKU والـProduct ID.</p>
      <p class='muted'>نصيحة: عند استخدام Product ID اترك SKU فارغاً حتى لا تختلط بيانات منتجين مختلفين.</p>
      <form method='get' action='/admin/merchant-test'>
        <label>رقم المنتج في سلة (Product ID)</label>
        <input class='input' name='product_id' dir='ltr' value='{esc(product_id)}' placeholder='مثال: 869677016'>
        <label style='display:block;margin-top:12px'>SKU</label>
        <input class='input' name='sku' dir='ltr' value='{esc(sku)}' placeholder='اختياري — اتركه فارغاً عند التشخيص بالـ Product ID'>
        <button class='btn btn-blue' style='margin-top:14px' type='submit'>تشخيص المنتج</button>
      </form>
      <div style='margin-top:20px'>{result_box}</div>
    </section></main>"""
    return HTMLResponse(page_shell("تشخيص بيانات الشريك", body, admin=True))


@app.post("/admin/customer-voucher-notification-test", response_class=HTMLResponse)
async def admin_customer_voucher_notification_test(request: Request, db: Session = Depends(get_db)):
    """Send the exact customer purchase-message layout as a safe admin test."""
    try:
        require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)

    raw = (await request.body()).decode("utf-8", errors="replace")
    form = parse_qs(raw)
    product_id = (form.get("product_id", [""])[0] or "").strip()
    sku = (form.get("sku", [""])[0] or "").strip()
    test_phone_raw = (form.get("test_phone", [""])[0] or "").strip()
    test_phone = normalize_saudi_phone(test_phone_raw)

    back_url = f"/admin/merchant-test?product_id={quote(product_id, safe='')}&sku={quote(sku, safe='')}"

    if not product_id:
        body = f"""<main class='wrap' style='padding:28px 0 48px'><section class='card' style='max-width:760px;margin:auto;padding:24px'><div class='alert alert-error'><strong>رقم المنتج غير موجود.</strong></div><a class='btn btn-muted' href='{esc(back_url)}'>العودة للتشخيص</a></section></main>"""
        return HTMLResponse(page_shell("اختبار رسالة العميل", body, admin=True), status_code=400)

    if not (test_phone.startswith("9665") and len(test_phone) == 12):
        body = f"""<main class='wrap' style='padding:28px 0 48px'><section class='card' style='max-width:760px;margin:auto;padding:24px'><div class='alert alert-error'><strong>رقم جوال الاختبار غير صحيح.</strong><div style='margin-top:8px'>استخدم رقم سعودي بصيغة 05xxxxxxxx أو 9665xxxxxxxx.</div></div><a class='btn btn-muted' href='{esc(back_url)}'>العودة للتشخيص</a></section></main>"""
        return HTMLResponse(page_shell("اختبار رسالة العميل", body, admin=True), status_code=400)

    metadata_payload, metadata_error = fetch_salla_json_endpoint(
        db, f"/metadata/values/product/{quote(product_id, safe='')}"
    )
    product_payload, product_error = fetch_salla_json_endpoint(
        db, f"/products/{quote(product_id, safe='')}"
    )

    partner_name = None
    partner_hours = None
    partner_contact = None
    partner_address = None
    partner_map_url = None
    for payload in (metadata_payload, product_payload):
        if payload is None:
            continue
        partner_name = partner_name or find_labeled_metadata_value(payload, PARTNER_NAME_FIELD_LABELS)
        partner_hours = partner_hours or find_labeled_metadata_value(payload, PARTNER_HOURS_FIELD_LABELS)
        partner_contact = partner_contact or find_labeled_metadata_value(payload, PARTNER_CONTACT_FIELD_LABELS)
        partner_address = partner_address or find_labeled_metadata_value(payload, PARTNER_ADDRESS_FIELD_LABELS)
        partner_map_url = partner_map_url or find_labeled_metadata_value(payload, PARTNER_MAP_FIELD_LABELS)

    product_data = product_payload.get("data") if isinstance(product_payload, dict) else product_payload
    if not isinstance(product_data, dict):
        product_data = {}
    product_name = str(product_data.get("name") or "عرض اختبار من Pakgat")

    customer_message = build_voucher_whatsapp_message(
        customer_name="عميل اختبار",
        product_name=product_name,
        voucher_code="PKG-TEST",
        order_id="TEST-0001",
        verification_url="https://pakgat.com",
        partner_name=partner_name,
        partner_hours=partner_hours,
        partner_contact=partner_contact,
        partner_address=partner_address,
        partner_map_url=partner_map_url,
    )
    message = "🧪 اختبار فقط — لا توجد عملية شراء حقيقية\n\n" + customer_message

    if not WHATSLOOP_API_BASE_URL or not WHATSLOOP_API_TOKEN:
        body = f"""<main class='wrap' style='padding:28px 0 48px'><section class='card' style='max-width:820px;margin:auto;padding:24px'><div class='alert alert-error'><strong>تعذر الإرسال: إعدادات WhatsLoop غير مكتملة.</strong></div><a class='btn btn-muted' href='{esc(back_url)}'>العودة للتشخيص</a></section></main>"""
        return HTMLResponse(page_shell("اختبار رسالة العميل", body, admin=True), status_code=500)

    request_body = json.dumps({"to": test_phone, "message": message}, ensure_ascii=False).encode("utf-8")
    req = UrlRequest(
        f"{WHATSLOOP_API_BASE_URL}/messages/send-text",
        data=request_body,
        headers={
            "Authorization": f"Bearer {WHATSLOOP_API_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    ok = False
    detail = ""
    try:
        with urlopen(req, timeout=25) as response:
            response_text = response.read().decode("utf-8", errors="replace")
            status_code = getattr(response, "status", response.getcode())
        ok = 200 <= int(status_code) < 300
        detail = f"HTTP {status_code}"
        log_event(db, "customer_voucher_test_sent", details=f"product_id={product_id}; phone={masked_phone(test_phone)}; status={status_code}")
    except HTTPError as exc:
        error_text = exc.read().decode("utf-8", errors="replace")
        detail = f"HTTP {exc.code}: {error_text[:260]}"
        log_event(db, "customer_voucher_test_failed", details=f"product_id={product_id}; phone={masked_phone(test_phone)}; status={exc.code}")
    except (URLError, TimeoutError, OSError) as exc:
        detail = f"{type(exc).__name__}: {exc}"
        log_event(db, "customer_voucher_test_failed", details=f"product_id={product_id}; phone={masked_phone(test_phone)}; error={type(exc).__name__}")

    status_html = (
        "<div class='alert alert-ok'><strong>تم إرسال رسالة اختبار العميل بنجاح ✅</strong></div>"
        if ok else
        "<div class='alert alert-error'><strong>فشل إرسال رسالة اختبار العميل.</strong></div>"
    )
    fields = (
        f"<p><strong>Product ID المستخدم:</strong> <span dir='ltr'>{esc(product_id)}</span></p><p><strong>SKU المستخدم:</strong> <span dir='ltr'>{esc(sku or 'فارغ')}</span></p><p><strong>اسم الشريك:</strong> {esc(partner_name or 'غير موجود')}</p>"
        f"<p><strong>ساعات العمل:</strong> {esc(partner_hours or 'غير موجود')}</p>"
        f"<p><strong>رقم التواصل:</strong> <span dir='ltr'>{esc(partner_contact or 'غير موجود')}</span></p>"
        f"<p><strong>العنوان:</strong> {esc(partner_address or 'غير موجود')}</p>"
        f"<p><strong>رابط خرائط Google:</strong> <span dir='ltr'>{esc(partner_map_url or 'غير موجود')}</span></p>"
    )
    source_errors = " | ".join(x for x in (metadata_error, product_error) if x)
    source_html = f"<p class='muted' dir='ltr'>{esc(source_errors)}</p>" if source_errors else ""
    body = f"""<main class='wrap' style='padding:28px 0 48px'><section class='card' style='max-width:860px;margin:auto;padding:24px'><h1>اختبار رسالة العميل</h1>{status_html}<p><strong>رقم الاختبار:</strong> <span dir='ltr'>{esc(masked_phone(test_phone))}</span></p>{fields}<p class='muted'>هذه رسالة اختبار فقط. تم استخدام نفس منشئ الرسالة الذي تستخدمه الطلبات الحقيقية، مع كود ورقم طلب تجريبيين ورابط pakgat.com بدلاً من قسيمة حقيقية.</p><p class='muted' dir='ltr'>{esc(detail)}</p>{source_html}<a class='btn btn-muted' href='{esc(back_url)}'>العودة لتكامل سلة</a></section></main>"""
    return HTMLResponse(page_shell("اختبار رسالة العميل", body, admin=True), status_code=200 if ok else 502)


@app.post("/admin/merchant-notification-test", response_class=HTMLResponse)
async def admin_merchant_notification_test(request: Request, db: Session = Depends(get_db)):
    try:
        require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)

    raw = (await request.body()).decode("utf-8", errors="replace")
    form = parse_qs(raw)
    product_id = (form.get("product_id", [""])[0] or "").strip()
    sku = (form.get("sku", [""])[0] or "").strip()

    if not product_id:
        body = "<main class='wrap' style='padding:28px 0 48px'><section class='card' style='max-width:760px;margin:auto;padding:24px'><div class='alert alert-error'><strong>رقم المنتج غير موجود.</strong></div><a class='btn btn-muted' href='/admin/merchant-test'>العودة للتشخيص</a></section></main>"
        return HTMLResponse(page_shell("اختبار واتساب الشريك", body, admin=True), status_code=400)

    product_payload, product_error = fetch_salla_json_endpoint(
        db, f"/products/{quote(product_id, safe='')}"
    )
    if (not product_payload or product_error) and sku:
        product_payload, product_error = fetch_salla_json_endpoint(
            db, f"/products/sku/{quote(sku, safe='')}"
        )

    metadata_payload, metadata_error = fetch_salla_json_endpoint(
        db, f"/metadata/values/product/{quote(product_id, safe='')}"
    )

    raw_phone = None
    partner_name = None
    for payload in (metadata_payload, product_payload):
        if payload is None:
            continue
        if not raw_phone:
            raw_phone = find_labeled_metadata_value(payload, MERCHANT_PHONE_FIELD_LABELS)
        if not partner_name:
            partner_name = find_labeled_metadata_value(payload, PARTNER_NAME_FIELD_LABELS)

    phones = merchant_phone_candidates(raw_phone)
    product_data = product_payload.get("data") if isinstance(product_payload, dict) else product_payload
    if not isinstance(product_data, dict):
        product_data = {}
    product_name = str(product_data.get("name") or "عرض Pakgat").strip()
    partner_name = partner_name or "شريك Pakgat"

    if not phones:
        error_detail = metadata_error or product_error or "لم يتم العثور على رقم جوال الشريك في بيانات المنتج."
        log_event(db, "merchant_whatsapp_test_failed", details=f"product_id={product_id}; reason=phone_not_found")
        body = f"""<main class='wrap' style='padding:28px 0 48px'><section class='card' style='max-width:760px;margin:auto;padding:24px'><div class='alert alert-error'><strong>لم يتم إرسال الرسالة.</strong><div style='margin-top:8px'>تعذر قراءة رقم جوال الشريك من سلة في هذه المحاولة.</div></div><p class='muted' dir='ltr'>{esc(error_detail)}</p><a class='btn btn-muted' href='/admin/merchant-test?product_id={esc(product_id)}&sku={esc(sku)}'>العودة للتشخيص</a></section></main>"""
        return HTMLResponse(page_shell("اختبار واتساب الشريك", body, admin=True), status_code=422)

    results = []
    for phone in phones:
        test_order_id = f"TEST-{int(now_utc().timestamp())}-{phone[-4:]}"
        notification_id = reserve_merchant_notification(db, test_order_id, product_id, phone)
        if not notification_id:
            results.append((phone, False, "تعذر حجز رسالة الاختبار."))
            continue

        send_merchant_sale_whatsapp(
            notification_id,
            phone,
            partner_name,
            product_name,
            test_order_id,
            1,
            1,
            test_mode=True,
        )
        db.expire_all()
        row = db.get(MerchantNotification, notification_id)
        ok = bool(row and row.status == "sent")
        detail = "تم قبول الرسالة من WhatsLoop." if ok else ((row.last_error if row else None) or "فشل الإرسال.")
        results.append((phone, ok, detail))

    all_ok = bool(results) and all(ok for _, ok, _ in results)
    rows = "".join(
        f"<tr><td dir='ltr'>{esc(phone)}</td><td>{'<span class=\'badge badge-active\'>تم الإرسال</span>' if ok else '<span class=\'badge badge-expired\'>فشل</span>'}</td><td>{esc(detail)}</td></tr>"
        for phone, ok, detail in results
    )
    alert = (
        "<div class='alert alert-ok'><strong>تم إرسال رسالة الاختبار للشريك ✅</strong><div style='margin-top:8px'>لا يوجد طلب حقيقي، ولم يتم إنشاء أي قسيمة.</div></div>"
        if all_ok
        else "<div class='alert alert-error'><strong>لم تنجح كل رسائل الاختبار.</strong><div style='margin-top:8px'>راجع التفاصيل أدناه وسجل العمليات.</div></div>"
    )
    body = f"""<main class='wrap' style='padding:28px 0 48px'><section class='card' style='max-width:860px;margin:auto;padding:24px'><h1>اختبار إشعار الشريك عبر واتساب</h1>{alert}<p><strong>المنتج:</strong> {esc(product_name)}</p><p><strong>اسم الشريك المستخدم:</strong> {esc(partner_name)}</p><div class='table-wrap'><table><thead><tr><th>رقم الشريك</th><th>الحالة</th><th>التفاصيل</th></tr></thead><tbody>{rows}</tbody></table></div><p class='muted' style='margin-top:14px'>رسالة الاختبار تبدأ بعبارة واضحة بأنها اختبار ولا يوجد طلب حقيقي. الإرسال الحقيقي يبقى بالنص المعتمد بدون عبارة الاختبار.</p><a class='btn btn-muted' style='margin-top:12px' href='/admin/merchant-test?product_id={esc(product_id)}&sku={esc(sku)}'>العودة لبيانات المنتج</a></section></main>"""
    return HTMLResponse(page_shell("اختبار واتساب الشريك", body, admin=True), status_code=200 if all_ok else 502)


@app.post("/admin/merchant-redemption-notification-test", response_class=HTMLResponse)
async def admin_merchant_redemption_notification_test(request: Request, db: Session = Depends(get_db)):
    try:
        require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)

    raw = (await request.body()).decode("utf-8", errors="replace")
    form = parse_qs(raw)
    product_id = (form.get("product_id", [""])[0] or "").strip()
    sku = (form.get("sku", [""])[0] or "").strip()

    if not product_id:
        body = "<main class='wrap' style='padding:28px 0 48px'><section class='card' style='max-width:760px;margin:auto;padding:24px'><div class='alert alert-error'><strong>رقم المنتج غير موجود.</strong></div><a class='btn btn-muted' href='/admin/merchant-test'>العودة للتشخيص</a></section></main>"
        return HTMLResponse(page_shell("اختبار تأكيد الاستبدال", body, admin=True), status_code=400)

    product_payload, product_error = fetch_salla_json_endpoint(
        db, f"/products/{quote(product_id, safe='')}"
    )
    if (not product_payload or product_error) and sku:
        product_payload, product_error = fetch_salla_json_endpoint(
            db, f"/products/sku/{quote(sku, safe='')}"
        )
    metadata_payload, metadata_error = fetch_salla_json_endpoint(
        db, f"/metadata/values/product/{quote(product_id, safe='')}"
    )

    raw_phone = None
    partner_name = None
    for payload in (metadata_payload, product_payload):
        if payload is None:
            continue
        if not raw_phone:
            raw_phone = find_labeled_metadata_value(payload, MERCHANT_PHONE_FIELD_LABELS)
        if not partner_name:
            partner_name = find_labeled_metadata_value(payload, PARTNER_NAME_FIELD_LABELS)

    phones = merchant_phone_candidates(raw_phone)
    product_data = product_payload.get("data") if isinstance(product_payload, dict) else product_payload
    if not isinstance(product_data, dict):
        product_data = {}
    product_name = str(product_data.get("name") or "عرض Pakgat").strip()
    partner_name = partner_name or "شريك Pakgat"

    if not phones:
        error_detail = metadata_error or product_error or "لم يتم العثور على رقم جوال الشريك."
        log_event(db, "merchant_redemption_whatsapp_test_failed", details=f"product_id={product_id}; reason=phone_not_found")
        body = f"""<main class='wrap' style='padding:28px 0 48px'><section class='card' style='max-width:760px;margin:auto;padding:24px'><div class='alert alert-error'><strong>لم يتم إرسال رسالة الاختبار.</strong></div><p class='muted' dir='ltr'>{esc(error_detail)}</p><a class='btn btn-muted' href='/admin/merchant-test?product_id={esc(product_id)}&sku={esc(sku)}'>العودة للتشخيص</a></section></main>"""
        return HTMLResponse(page_shell("اختبار تأكيد الاستبدال", body, admin=True), status_code=422)

    test_order_id = f"TEST-{int(now_utc().timestamp())}"
    test_voucher_code = "PKG-TEST-QR"
    results = []
    for phone in phones:
        ok = send_merchant_redemption_whatsapp(
            None,
            None,
            phone,
            partner_name,
            product_name,
            test_voucher_code,
            test_order_id,
            now_utc(),
            test_mode=True,
        )
        results.append((phone, ok))

    all_ok = bool(results) and all(ok for _, ok in results)
    rows = "".join(
        f"<tr><td dir='ltr'>{esc(phone)}</td><td>{'<span class=\'badge badge-active\'>تم الإرسال</span>' if ok else '<span class=\'badge badge-expired\'>فشل</span>'}</td></tr>"
        for phone, ok in results
    )
    alert = (
        "<div class='alert alert-ok'><strong>تم إرسال اختبار تأكيد الاستبدال للشريك ✅</strong><div style='margin-top:8px'>لم يتم استخدام أي قسيمة ولم يتغير أي طلب.</div></div>"
        if all_ok
        else "<div class='alert alert-error'><strong>لم تنجح كل رسائل الاختبار.</strong><div style='margin-top:8px'>راجع سجل العمليات.</div></div>"
    )
    body = f"""<main class='wrap' style='padding:28px 0 48px'><section class='card' style='max-width:860px;margin:auto;padding:24px'><h1>اختبار رسالة الشريك بعد استبدال QR</h1>{alert}<p><strong>المنتج:</strong> {esc(product_name)}</p><p><strong>اسم الشريك:</strong> {esc(partner_name)}</p><div class='table-wrap'><table><thead><tr><th>رقم الشريك</th><th>الحالة</th></tr></thead><tbody>{rows}</tbody></table></div><p class='muted' style='margin-top:14px'>رسالة الاختبار مميزة بوضوح بأنها لا تمثل استبدالاً حقيقياً.</p><a class='btn btn-muted' style='margin-top:12px' href='/admin/merchant-test?product_id={esc(product_id)}&sku={esc(sku)}'>العودة لبيانات المنتج</a></section></main>"""
    return HTMLResponse(page_shell("اختبار تأكيد الاستبدال", body, admin=True), status_code=200 if all_ok else 502)


@app.post("/webhooks/salla")
async def salla_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    raw_body = await request.body()

    if not verify_salla_signature(
        raw_body,
        request.headers.get("x-salla-signature", ""),
    ):
        log_event(db, "salla_webhook_rejected", details="Invalid signature")
        return JSONResponse(
            status_code=401,
            content={"ok": False, "detail": "Invalid Salla signature."},
        )

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        log_event(db, "salla_webhook_rejected", details="Invalid JSON payload")
        return JSONResponse(
            status_code=400,
            content={"ok": False, "detail": "Invalid JSON."},
        )

    event = str(payload.get("event") or "").strip()
    data = payload.get("data") or {}

    log_event(
        db,
        "salla_webhook_received",
        details=f"Event received: {event or 'unknown'}",
    )

    # Salla Easy Mode sends fresh OAuth credentials with app.store.authorize.
    # Handle this before order-event filtering. Tokens are stored in the database
    # and their raw values are never written to logs or responses.
    if event in {"app.store.authorize", "app.store.authorized"}:
        stored, result = store_salla_authorization(db, payload)
        if stored:
            credential = latest_salla_credential(db, result)
            log_event(
                db,
                "salla_oauth_authorized",
                details=(
                    f"merchant={result}; scope={credential.scope or 'unknown'}; "
                    f"expires_at={fmt_dt(credential.expires_at)}"
                ),
            )
            return {"ok": True, "event": event, "oauth": "stored"}
        log_event(db, "salla_oauth_failed", details=f"Event={event}; reason={result}")
        return JSONResponse(
            status_code=422,
            content={"ok": False, "event": event, "detail": result},
        )

    # Security rule: vouchers are issued only after Salla confirms payment.
    # Other order events are logged for visibility but never create a voucher.
    supported_events = {"order.updated", "order.payment.updated"}

    if event not in supported_events:
        log_event(
            db,
            "salla_webhook_ignored",
            details=f"Unsupported event: {event}",
        )
        return {
            "ok": True,
            "ignored": True,
            "reason": "Unsupported event.",
            "event": event,
        }

    payment_status_paths = [
        "payment.status.slug",
        "payment.status.name",
        "payment.status",
        "payment_status.slug",
        "payment_status.name",
        "payment_status",
        "order.payment.status.slug",
        "order.payment.status.name",
        "order.payment.status",
    ]
    if event == "order.payment.updated":
        # Some payment-event payloads expose the payment state directly here.
        payment_status_paths.extend(["status.slug", "status.name", "status"])

    payment_status = str(
        first_value(data, *payment_status_paths) or ""
    ).strip().lower()

    order_status = str(
        first_value(
            data,
            "status.slug",
            "status.name",
            "status",
            "order.status.slug",
            "order.status.name",
            "order.status",
        )
        or ""
    ).strip().lower()

    paid_statuses = {
        "paid",
        "completed",
        "success",
        "successful",
        "تم الدفع",
        "مدفوع",
    }

    def amount_value(*paths: str) -> float:
        value = first_value(data, *paths)
        if isinstance(value, dict):
            value = value.get("amount") or value.get("value")
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    paid_amount = amount_value(
        "amounts.paid.amount",
        "amounts.paid",
        "paid_amount.amount",
        "paid_amount",
        "order.amounts.paid.amount",
        "order.amounts.paid",
    )
    total_amount = amount_value(
        "amounts.total.amount",
        "amounts.total",
        "total.amount",
        "total",
        "order.amounts.total.amount",
        "order.amounts.total",
    )

    # Primary confirmation signals:
    # 1) an explicit successful payment status, or
    # 2) a paid amount that covers the order total.
    explicit_payment_confirmed = payment_status in paid_statuses
    amount_payment_confirmed = total_amount > 0 and paid_amount >= total_amount

    # In this Pakgat store, offline payment methods (bank transfer and COD) are
    # disabled. Salla's broad order.updated payload currently reports the final
    # order state as "closed" without including paid_amount/payment_status.
    # Therefore a final closed/completed state is accepted as the fallback
    # confirmation signal for order.updated only.
    final_online_order_statuses = {
        "closed",
        "completed",
        "fulfilled",
        "مكتمل",
        "مغلق",
        "تم التنفيذ",
    }
    final_order_confirmed = (
        event == "order.updated"
        and order_status in final_online_order_statuses
    )

    is_paid = (
        explicit_payment_confirmed
        or amount_payment_confirmed
        or final_order_confirmed
    )

    if not is_paid:
        log_event(
            db,
            "salla_webhook_ignored",
            details=(
                f"Event={event}; order_status={order_status or 'unknown'}; "
                f"payment_status={payment_status or 'unknown'}; "
                f"paid_amount={paid_amount}; total_amount={total_amount}; "
                f"final_order_confirmed={final_order_confirmed}"
            ),
        )
        return {
            "ok": True,
            "ignored": True,
            "reason": "Payment has not been confirmed as successful.",
            "event": event,
            "order_status": order_status,
            "payment_status": payment_status,
            "paid_amount": paid_amount,
            "total_amount": total_amount,
        }

    base_order_id = str(
        first_value(
            data,
            "id",
            "order.id",
            "reference_id",
            "order.reference_id",
        )
        or ""
    ).strip()

    if not base_order_id:
        log_event(
            db,
            "salla_webhook_rejected",
            details=f"Order ID missing for event={event}",
        )
        return JSONResponse(
            status_code=422,
            content={"ok": False, "detail": "Order ID is missing."},
        )

    customer_name = str(
        first_value(
            data,
            "customer.name",
            "customer.first_name",
            "order.customer.name",
            "order.customer.first_name",
        )
        or "عميل بكجات"
    )
    customer_email = str(
        first_value(data, "customer.email", "order.customer.email", "email")
        or ""
    )
    customer_phone = str(
        first_value(
            data,
            "customer.mobile",
            "customer.phone",
            "order.customer.mobile",
            "order.customer.phone",
            "mobile",
        )
        or ""
    )
    merchant_name = str(
        first_value(payload, "merchant.name", "merchant.store_name") or "Pakgat"
    )
    salla_merchant_id = payload_merchant_id(payload)

    items = normalize_items(data)
    if not items:
        log_event(
            db,
            "salla_webhook_ignored",
            details=f"Order {base_order_id} contains no product items in event {event}",
        )
        return {
            "ok": True,
            "ignored": True,
            "reason": "No order items were included in the webhook.",
            "order_id": base_order_id,
        }

    created = []
    matched_products = 0
    ignored_products = 0

    for item in items:
        product_id = item_product_id(item)
        product_name = item_product_name(item)
        sku = item_sku(item)
        normalized_sku = sku.upper()

        if not normalized_sku.startswith(VOUCHER_SKU_PREFIX):
            ignored_products += 1
            log_event(
                db,
                "salla_product_ignored",
                details=(
                    f"Order {base_order_id}; product_id={product_id or 'unknown'}; "
                    f"product={product_name}; sku={sku or 'missing'}; "
                    f"required_prefix={VOUCHER_SKU_PREFIX}"
                ),
            )
            continue

        matched_products += 1
        quantity = item_quantity(item)
        log_event(
            db,
            "salla_product_matched",
            details=(
                f"Order {base_order_id}; product_id={product_id or 'unknown'}; "
                f"product={product_name}; sku={sku}"
            ),
        )

        merchant_phone_raw = find_labeled_metadata_value(item, MERCHANT_PHONE_FIELD_LABELS)
        partner_name_raw = find_labeled_metadata_value(item, PARTNER_NAME_FIELD_LABELS)
        partner_hours = find_labeled_metadata_value(item, PARTNER_HOURS_FIELD_LABELS)
        partner_contact = find_labeled_metadata_value(item, PARTNER_CONTACT_FIELD_LABELS)
        partner_address = find_labeled_metadata_value(item, PARTNER_ADDRESS_FIELD_LABELS)
        partner_map_url = find_labeled_metadata_value(item, PARTNER_MAP_FIELD_LABELS)
        metadata_source = "webhook"
        metadata_error = None

        # Hidden product metadata may not be embedded in Salla order webhooks.
        # Fetch product metadata if any routing/customer-facing partner field is missing.
        if (
            not merchant_phone_raw
            or not partner_name_raw
            or not partner_hours
            or not partner_contact
            or not partner_address
            or not partner_map_url
        ):
            fetched_metadata, metadata_error = fetch_salla_product_metadata(
                db, product_id, salla_merchant_id
            )
            if fetched_metadata is not None:
                merchant_phone_raw = merchant_phone_raw or find_labeled_metadata_value(
                    fetched_metadata, MERCHANT_PHONE_FIELD_LABELS
                )
                partner_name_raw = partner_name_raw or find_labeled_metadata_value(
                    fetched_metadata, PARTNER_NAME_FIELD_LABELS
                )
                partner_hours = partner_hours or find_labeled_metadata_value(
                    fetched_metadata, PARTNER_HOURS_FIELD_LABELS
                )
                partner_contact = partner_contact or find_labeled_metadata_value(
                    fetched_metadata, PARTNER_CONTACT_FIELD_LABELS
                )
                partner_address = partner_address or find_labeled_metadata_value(
                    fetched_metadata, PARTNER_ADDRESS_FIELD_LABELS
                )
                partner_map_url = partner_map_url or find_labeled_metadata_value(
                    fetched_metadata, PARTNER_MAP_FIELD_LABELS
                )
                metadata_source = "salla_metadata_api"

        merchant_phones = merchant_phone_candidates(merchant_phone_raw)
        customer_partner_name = (partner_name_raw or "").strip()
        partner_name = customer_partner_name or "شريك Pakgat"

        if merchant_phones:
            log_event(
                db,
                "merchant_phone_found",
                details=(
                    f"Order {base_order_id}; product_id={product_id}; source={metadata_source}; "
                    f"phones={','.join(masked_phone(p) for p in merchant_phones)}"
                ),
            )
        else:
            debug_paths = metadata_debug_paths(item)
            log_event(
                db,
                "merchant_phone_not_found",
                details=(
                    f"Order {base_order_id}; product_id={product_id}; "
                    f"metadata_paths={','.join(debug_paths) if debug_paths else 'none'}; "
                    f"fallback={metadata_error or metadata_source}"
                ),
            )

        for index in range(1, quantity + 1):
            voucher_order_id = f"{base_order_id}:{product_id}:{index}"
            existing = db.scalar(
                select(Voucher).where(
                    Voucher.order_id == voucher_order_id,
                    Voucher.product_id == product_id,
                )
            )
            if existing:
                verification_url = BASE_URL + "/v/" + existing.verification_token
                ensure_customer_notification(
                    db,
                    existing,
                    "voucher_issued",
                    build_voucher_whatsapp_message(
                        customer_name=existing.customer_name or customer_name,
                        product_name=existing.product_name,
                        voucher_code=existing.code,
                        order_id=base_order_id,
                        verification_url=verification_url,
                        partner_name=customer_partner_name or None,
                        partner_hours=partner_hours,
                        partner_contact=partner_contact,
                        partner_address=partner_address,
                        partner_map_url=partner_map_url,
                    ),
                )
                log_event(
                    db,
                    "voucher_already_exists",
                    existing.id,
                    f"Repeated Salla event for order {base_order_id}; sku={sku}",
                )
                continue

            voucher = create_voucher_record(
                db=db,
                order_id=voucher_order_id,
                product_id=product_id,
                product_name=product_name,
                merchant_name=partner_name,
                customer_name=customer_name,
                customer_phone=customer_phone,
                option_name=item_option_name(item),
                validity_days=int(env("DEFAULT_VALIDITY_DAYS", "7")),
                commit=False,
            )
            verification_url = BASE_URL + "/v/" + voucher.verification_token
            ensure_customer_notification(
                db,
                voucher,
                "voucher_issued",
                build_voucher_whatsapp_message(
                    customer_name=customer_name,
                    product_name=voucher.product_name,
                    voucher_code=voucher.code,
                    order_id=base_order_id,
                    verification_url=verification_url,
                    partner_name=customer_partner_name or None,
                    partner_hours=partner_hours,
                    partner_contact=partner_contact,
                    partner_address=partner_address,
                    partner_map_url=partner_map_url,
                ),
                commit=False,
            )
            db.commit()
            db.refresh(voucher)
            created.append(
                {"code": voucher.code, "verification_url": verification_url}
            )
            log_event(
                db,
                "voucher_created",
                voucher.id,
                f"Created from Salla order {base_order_id}; sku={sku}",
            )
            if customer_email:
                background_tasks.add_task(
                    send_voucher_email,
                    customer_email,
                    customer_name,
                    voucher.product_name,
                    voucher.code,
                    verification_url,
                    voucher.expires_at,
                )
            if not customer_phone:
                log_event(
                    db,
                    "whatsapp_skipped",
                    voucher.id,
                    f"WhatsApp skipped for order {base_order_id}: customer phone is missing.",
                )

        # Merchant notification is intentionally outside voucher creation.
        # This lets us re-trigger the SAME paid Salla order after deployment:
        # existing vouchers are left untouched, while the merchant notification
        # can still be sent once if it has not already been delivered.
        for merchant_phone in merchant_phones:
            notification_id = reserve_merchant_notification(
                db,
                base_order_id,
                product_id,
                merchant_phone,
            )
            if notification_id:
                background_tasks.add_task(
                    send_merchant_sale_whatsapp,
                    notification_id,
                    merchant_phone,
                    partner_name,
                    product_name,
                    base_order_id,
                    quantity,
                    quantity,
                )
            else:
                log_event(
                    db,
                    "merchant_whatsapp_duplicate_skipped",
                    details=(
                        f"Order {base_order_id}; product_id={product_id}; "
                        f"phone={masked_phone(merchant_phone)}"
                    ),
                )

    log_event(
        db,
        "salla_order_processed",
        details=(
            f"Order {base_order_id}; event={event}; payment_status={payment_status or 'unknown'}; "
            f"matched_products={matched_products}; ignored_products={ignored_products}; "
            f"created={len(created)}"
        ),
    )
    return {
        "ok": True,
        "event": event,
        "order_id": base_order_id,
        "created_count": len(created),
        "matched_products": matched_products,
        "ignored_products": ignored_products,
        "email_queued": bool(created and customer_email),
        "whatsapp_queued": bool(created and customer_phone),
        "vouchers": created,
    }
