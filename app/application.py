# PAKGAT_BUILD: 2026-08-08-SALLA-METADATA-CF-FIX-v4
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


BUILD_VERSION = "2026-08-08-SALLA-METADATA-CF-FIX-v4"


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
MERCHANT_NOTIFICATION_PIN = (
    env("MERCHANT_NOTIFICATION_PIN")
    or str(MERCHANT_CODES.get("Pakgat") or MERCHANT_CODES.get("*") or "4826")
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


def send_voucher_whatsapp(
    voucher_id: int,
    customer_phone: str,
    customer_name: str,
    product_name: str,
    voucher_code: str,
    order_id: str,
    verification_url: str,
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

    name = (customer_name or "عميل بكجات").strip()
    message = (
        "✅ قسيمتك جاهزة للاستخدام\n\n"
        f"مرحباً {name} 🎁\n\n"
        "تم إصدار قسيمتك بنجاح.\n\n"
        f"🎟️ العرض: {product_name}\n"
        f"🔖 رقم القسيمة: {voucher_code}\n"
        f"📦 رقم الطلب: {order_id}\n\n"
        "افتح قسيمتك ورمز QR:\n"
        f"{verification_url}\n\n"
        "📲 عند استلام الخدمة، اعرض رمز QR للتاجر ليتم تأكيد الاستخدام.\n\n"
        "🔒 لا تشارك رابط القسيمة أو رمز QR مع أي شخص، "
        "ولا تعرضه إلا عند استلام الخدمة.\n\n"
        "⭐ وعندنا لك شيء إضافي!\n\n"
        "بما أنك أصبحت من عملاء Pakgat، فأنت الآن VIP عندنا 💙\n\n"
        "🎁 استخدم الكود VIP واحصل على خصم 5% على طلبك القادم.\n\n"
        "يمكن عرضك القادم موجود من الآن 👀\n"
        "https://pakgat.com\n\n"
        "شكراً لاختيارك Pakgat\n"
        "بدون قروشة.. بكجات تضبطك ✨"
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
    """Notify the customer only after a voucher redemption succeeds."""
    phone = normalize_saudi_phone(customer_phone)

    if not phone:
        with SessionLocal() as db:
            log_event(
                db,
                "redemption_whatsapp_skipped",
                voucher_id,
                "Customer phone is missing.",
            )
        return

    if not WHATSLOOP_API_BASE_URL or not WHATSLOOP_API_TOKEN:
        with SessionLocal() as db:
            log_event(
                db,
                "redemption_whatsapp_skipped",
                voucher_id,
                "WhatsLoop environment variables are missing.",
            )
        return

    name = (customer_name or "عميل بكجات").strip()
    display_order_id = str(order_id or "").split(":", 1)[0]
    used_at = fmt_dt(redeemed_at)
    message = (
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
        "شكراً لاختيارك Pakgat\n"
        "بدون قروشة.. بكجات تضبطك ✨"
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
) -> None:
    phone = normalize_saudi_phone(merchant_phone)
    partner = (merchant_name or "شريك Pakgat").strip()

    if not phone:
        with SessionLocal() as db:
            row = db.get(MerchantNotification, notification_id)
            if row:
                row.status = "failed"
                row.last_error = "Merchant phone is invalid."
                db.commit()
            log_event(db, "merchant_whatsapp_failed", details=f"order={order_id}; invalid merchant phone")
        return

    if not WHATSLOOP_API_BASE_URL or not WHATSLOOP_API_TOKEN:
        with SessionLocal() as db:
            row = db.get(MerchantNotification, notification_id)
            if row:
                row.status = "failed"
                row.last_error = "WhatsLoop environment variables are missing."
                db.commit()
            log_event(db, "merchant_whatsapp_failed", details=f"order={order_id}; WhatsLoop config missing")
        return

    message = (
        f"🎉 تم بيع {product_name} عبر Pakgat\n\n"
        f"مرحباً {partner}\n\n"
        f"تم شراء {product_name} بنجاح عبر Pakgat.\n\n"
        f"📦 رقم الطلب: {order_id}\n"
        f"🔢 الكمية: {quantity}\n"
        f"🎫 عدد القسائم: {voucher_count}\n\n"
        "القسيمة أصبحت جاهزة لدى العميل، وسيقوم بعرض رمز QR قبل استلام الخدمة.\n\n"
        f"🔐 الرقم السري لتأكيد استلام الخدمة: {MERCHANT_NOTIFICATION_PIN}\n\n"
        "يتم تأكيد استلام الخدمة عند حضور العميل وعرض رمز QR الخاص بالقسيمة.\n\n"
        "شكراً لشراكتكم مع Pakgat 💙"
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
                "merchant_whatsapp_sent",
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
                "merchant_whatsapp_failed",
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
                "merchant_whatsapp_failed",
                details=f"order={order_id}; phone={masked_phone(phone)}; error={type(exc).__name__}",
            )


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
    return {"status": "running", "service": "Pakgat Voucher System", "version": "3.0", "build": BUILD_VERSION, "admin": BASE_URL + "/admin/login", "database": "connected"}


@app.get("/health")
def health():
    with engine.connect():
        pass
    with SessionLocal() as db:
        oauth_ready = db.scalar(select(func.count(SallaOAuthCredential.id))) or 0
    return {
        "ok": True,
        "database": "connected",
        "build": BUILD_VERSION,
        "salla_oauth": "connected" if oauth_ready else "waiting_authorization",
    }


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
async def redeem_voucher(verification_token: str, request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
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
    background_tasks.add_task(
        send_redemption_whatsapp,
        voucher.id,
        voucher.customer_phone or "",
        voucher.customer_name or "",
        voucher.product_name,
        voucher.code,
        voucher.order_id,
        voucher.merchant_name,
        voucher.redeemed_at or now_utc(),
    )
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
def admin_redeem_voucher(voucher_id: int, request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    try:
        require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)
    voucher = db.get(Voucher, voucher_id)
    if not voucher:
        raise HTTPException(status_code=404, detail="Voucher not found")
    result = db.execute(update(Voucher).where(Voucher.id == voucher_id, Voucher.status == "active", Voucher.expires_at >= now_utc()).values(status="redeemed", redeemed_at=now_utc()).execution_options(synchronize_session=False))
    db.commit()
    if result.rowcount != 1:
        log_event(db, "admin_redeem_failed", voucher_id, "Voucher was not active")
        raise HTTPException(status_code=409, detail="Voucher is not active")
    db.refresh(voucher)
    log_event(db, "voucher_redeemed", voucher_id, "Redeemed from admin dashboard")
    background_tasks.add_task(
        send_redemption_whatsapp,
        voucher.id,
        voucher.customer_phone or "",
        voucher.customer_name or "",
        voucher.product_name,
        voucher.code,
        voucher.order_id,
        voucher.merchant_name,
        voucher.redeemed_at or now_utc(),
    )
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
        "merchant_whatsapp_duplicate_skipped": "تجاوز إشعار شريك مكرر",
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
    body = f"""<main class='wrap' style='padding:28px 0 48px'><h1>تكامل سلة</h1><div class='grid grid-mobile-1' style='grid-template-columns:repeat(3,1fr);margin-bottom:18px'><div class='card' style='padding:20px'><h3>توقيع Webhook</h3>{state(webhook_ready)}<p class='muted'>SALLA_WEBHOOK_SECRET</p></div><div class='card' style='padding:20px'><h3>منتجات القسائم</h3>{state(products_ready)}<p class='muted'>أي SKU يبدأ بـ {esc(VOUCHER_SKU_PREFIX)}</p></div><div class='card' style='padding:20px'><h3>البريد الإلكتروني</h3>{state(smtp_ready)}<p class='muted'>إرسال رابط القسيمة للعميل</p></div></div><section class='card' style='padding:22px'><h2>رابط Webhook</h2><input class='input' dir='ltr' readonly onclick='this.select()' value='{esc(webhook_url)}'><h2 style='margin-top:24px'>الحدث التشغيلي</h2><p><code>order.updated</code> هو الحدث الرئيسي المعتمد من إعدادات التطبيق، مع دعم <code>order.payment.updated</code> إن وصل. تُصدر القسيمة عند تأكيد الدفع صراحة، أو اكتمال المبلغ المدفوع، أو وصول الطلب إلى الحالة النهائية <code>closed/completed</code> في إعداد المتجر الإلكتروني الحالي.</p><h2 style='margin-top:24px'>اختبار رقم جوال الشريك</h2><p><a class='btn btn-blue' href='/admin/merchant-test?product_id=1181243277'>اختبار قراءة المنتج 1181243277 بدون شراء</a></p><h2 style='margin-top:24px'>المسار التشغيلي</h2><p>تحديث الطلب من سلة ← التحقق من الدفع الفعلي ← مطابقة SKU يبدأ بـ PKG-QR ← إنشاء القسيمة وQR مرة واحدة ← ظهورها في لوحة الإدارة وإرسال رابطها بالبريد عند اكتمال SMTP.</p></section></main>"""
    return HTMLResponse(page_shell("تكامل سلة", body, admin=True))


@app.get("/admin/merchant-test", response_class=HTMLResponse)
def admin_merchant_metadata_test(request: Request, product_id: str = "", db: Session = Depends(get_db)):
    try:
        require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)

    product_id = (product_id or "").strip()
    result_box = ""
    if product_id:
        metadata, error = fetch_salla_product_metadata(db, product_id)
        if metadata is None:
            result_box = (
                "<div class='alert alert-error'><strong>تعذر قراءة بيانات المنتج من سلة.</strong>"
                f"<div style='margin-top:8px' dir='ltr'>{esc(error or 'Unknown error')}</div></div>"
            )
            log_event(db, "merchant_metadata_test_failed", details=f"product_id={product_id}; error={(error or 'unknown')[:220]}")
        else:
            raw_phone = find_labeled_metadata_value(metadata, MERCHANT_PHONE_FIELD_LABELS)
            phones = merchant_phone_candidates(raw_phone)
            partner_name = find_labeled_metadata_value(metadata, PARTNER_NAME_FIELD_LABELS)
            if phones:
                phone_rows = "".join(f"<li dir='ltr'><strong>{esc(p)}</strong></li>" for p in phones)
                result_box = (
                    "<div class='alert alert-ok'><strong>تمت قراءة بيانات المنتج بنجاح ✅</strong></div>"
                    "<div class='card' style='padding:20px;margin-top:14px'>"
                    f"<p><strong>رقم المنتج:</strong> <span dir='ltr'>{esc(product_id)}</span></p>"
                    f"<p><strong>اسم الشريك:</strong> {esc(partner_name or 'غير موجود في الحقول المقروءة')}</p>"
                    "<p><strong>رقم جوال استقبال القسائم:</strong></p>"
                    f"<ul>{phone_rows}</ul>"
                    "<p class='muted'>هذا اختبار قراءة فقط؛ لم يتم إرسال أي رسالة واتساب ولم يتم إنشاء أي قسيمة.</p>"
                    "</div>"
                )
                log_event(db, "merchant_metadata_test_ok", details=f"product_id={product_id}; phones={','.join(masked_phone(p) for p in phones)}")
            else:
                paths = metadata_debug_paths(metadata)
                result_box = (
                    "<div class='alert alert-error'><strong>تم الوصول إلى بيانات المنتج، لكن حقل رقم جوال استقبال القسائم لم يتم العثور عليه.</strong>"
                    f"<div style='margin-top:8px'>المسارات الوصفية المكتشفة: {esc(', '.join(paths[:20]) if paths else 'لا يوجد')}</div></div>"
                )
                log_event(db, "merchant_metadata_test_no_phone", details=f"product_id={product_id}; metadata_paths={','.join(paths[:20]) if paths else 'none'}")

    body = f"""<main class='wrap' style='padding:28px 0 48px'>
    <section class='card' style='max-width:760px;margin:auto;padding:24px'>
      <h1>اختبار قراءة رقم جوال الشريك من سلة</h1>
      <p class='muted'>اختبار مباشر من بيانات المنتج بدون شراء، بدون إنشاء قسيمة وبدون إرسال واتساب.</p>
      <form method='get' action='/admin/merchant-test'>
        <label>رقم المنتج في سلة (Product ID)</label>
        <input class='input' name='product_id' dir='ltr' value='{esc(product_id)}' placeholder='1181243277' required>
        <button class='btn btn-blue' style='margin-top:14px' type='submit'>اختبار القراءة</button>
      </form>
      <div style='margin-top:20px'>{result_box}</div>
    </section></main>"""
    return HTMLResponse(page_shell("اختبار بيانات الشريك", body, admin=True))


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
        partner_name = find_labeled_metadata_value(item, PARTNER_NAME_FIELD_LABELS)
        metadata_source = "webhook"
        metadata_error = None

        # Hidden product metadata may not be embedded in Salla order webhooks.
        # If a Merchant API token is configured, fetch the product metadata values
        # directly using the product_id as a safe fallback.
        if not merchant_phone_raw:
            fetched_metadata, metadata_error = fetch_salla_product_metadata(
                db, product_id, salla_merchant_id
            )
            if fetched_metadata is not None:
                merchant_phone_raw = find_labeled_metadata_value(
                    fetched_metadata, MERCHANT_PHONE_FIELD_LABELS
                )
                partner_name = partner_name or find_labeled_metadata_value(
                    fetched_metadata, PARTNER_NAME_FIELD_LABELS
                )
                metadata_source = "salla_metadata_api"

        merchant_phones = merchant_phone_candidates(merchant_phone_raw)
        partner_name = partner_name or "شريك Pakgat"

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
                merchant_name=merchant_name,
                customer_name=customer_name,
                customer_phone=customer_phone,
                option_name=item_option_name(item),
                validity_days=int(env("DEFAULT_VALIDITY_DAYS", "7")),
            )
            verification_url = BASE_URL + "/v/" + voucher.verification_token
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
            if customer_phone:
                background_tasks.add_task(
                    send_voucher_whatsapp,
                    voucher.id,
                    customer_phone,
                    customer_name,
                    voucher.product_name,
                    voucher.code,
                    base_order_id,
                    verification_url,
                )
            else:
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
