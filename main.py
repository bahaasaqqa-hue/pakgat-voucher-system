import os
import json
import secrets
import hashlib
import hmac
import io
import smtplib
from email.message import EmailMessage
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import parse_qs

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
import qrcode
from sqlalchemy import DateTime, Integer, String, create_engine, select
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    sessionmaker,
)


database_url = os.environ["DATABASE_URL"]

if database_url.startswith("postgres://"):
    database_url = database_url.replace(
        "postgres://",
        "postgresql+psycopg://",
        1,
    )
elif database_url.startswith("postgresql://"):
    database_url = database_url.replace(
        "postgresql://",
        "postgresql+psycopg://",
        1,
    )


engine = create_engine(
    database_url,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    pass


class Voucher(Base):
    __tablename__ = "vouchers"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    code: Mapped[str] = mapped_column(
        String(40),
        unique=True,
        index=True,
    )

    verification_token: Mapped[str] = mapped_column(
        String(150),
        unique=True,
        index=True,
    )

    order_id: Mapped[str] = mapped_column(
        String(100),
        index=True,
    )

    product_id: Mapped[str] = mapped_column(
        String(100),
        index=True,
    )

    product_name: Mapped[str] = mapped_column(
        String(255),
    )

    merchant_name: Mapped[str] = mapped_column(
        String(255),
    )

    customer_name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )

    customer_phone: Mapped[Optional[str]] = mapped_column(
        String(30),
        nullable=True,
    )

    option_name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default="active",
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
    )

    redeemed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class VoucherCreate(BaseModel):
    order_id: str = Field(min_length=1, max_length=100)
    product_id: str = Field(min_length=1, max_length=100)
    product_name: str = Field(min_length=1, max_length=255)
    merchant_name: str = Field(min_length=1, max_length=255)
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    option_name: Optional[str] = None
    validity_days: int = Field(default=7, ge=1, le=365)


class VoucherResponse(BaseModel):
    code: str
    verification_token: str
    verification_url: str
    status: str
    expires_at: datetime


def get_db():
    session = SessionLocal()

    try:
        yield session
    finally:
        session.close()


def generate_voucher_code() -> str:
    return "PKG-" + secrets.token_hex(4).upper()


def generate_verification_token() -> str:
    return secrets.token_urlsafe(32)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Pakgat Voucher System",
    version="1.4",
    lifespan=lifespan,
)


BASE_URL = os.getenv(
    "PUBLIC_BASE_URL",
    "https://pakgat-voucher-system.onrender.com",
).rstrip("/")

SALLA_WEBHOOK_SECRET = os.getenv("SALLA_WEBHOOK_SECRET", "")

try:
    MERCHANT_CODES = json.loads(
        os.getenv("MERCHANT_CODES", "{}")
    )
except json.JSONDecodeError:
    MERCHANT_CODES = {}

VOUCHER_PRODUCT_IDS = {
    value.strip()
    for value in os.getenv(
        "VOUCHER_PRODUCT_IDS",
        "782332771",
    ).split(",")
    if value.strip()
}


def verify_salla_signature(raw_body: bytes, received_signature: str) -> bool:
    if not SALLA_WEBHOOK_SECRET:
        return False

    expected_signature = hmac.new(
        SALLA_WEBHOOK_SECRET.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(
        expected_signature,
        received_signature or "",
    )


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
    value = first_value(
        item,
        "product.id",
        "product_id",
        "id",
    )
    return str(value or "")


def item_product_name(item: dict) -> str:
    return str(
        first_value(
            item,
            "product.name",
            "name",
            "product_name",
        )
        or "عرض بكجات"
    )


def item_option_name(item: dict) -> Optional[str]:
    options = item.get("options")

    if isinstance(options, list):
        labels = []

        for option in options:
            if isinstance(option, dict):
                label = (
                    first_value(option, "value.name", "value", "name")
                    or ""
                )
                if label:
                    labels.append(str(label))

        return "، ".join(labels) or None

    return str(options) if options else None


def item_quantity(item: dict) -> int:
    value = first_value(item, "quantity", "qty")

    try:
        return max(1, int(value or 1))
    except (TypeError, ValueError):
        return 1


def generate_qr_png(url: str) -> bytes:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)

    image = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def send_voucher_email(
    customer_email: str,
    customer_name: str,
    product_name: str,
    voucher_code: str,
    verification_url: str,
    expires_at: datetime,
) -> None:
    smtp_host = os.getenv("SMTP_HOST", "")
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_password = os.getenv("SMTP_PASSWORD", "")
    smtp_from = os.getenv("SMTP_FROM", smtp_user)
    smtp_port = int(os.getenv("SMTP_PORT", "587"))

    if not all(
        [
            smtp_host,
            smtp_user,
            smtp_password,
            smtp_from,
            customer_email,
        ]
    ):
        return

    message = EmailMessage()
    message["Subject"] = f"قسيمتك من بكجات — {product_name}"
    message["From"] = smtp_from
    message["To"] = customer_email

    message.set_content(
        f"""مرحبًا {customer_name or 'عميل بكجات'},

تم إصدار قسيمتك بنجاح.

العرض: {product_name}
الكود: {voucher_code}
تاريخ الانتهاء: {expires_at.strftime('%Y-%m-%d %H:%M')}

افتح القسيمة:
{verification_url}

أظهر القسيمة للتاجر عند استلام الخدمة فقط.
"""
    )

    html = f"""
    <html lang="ar" dir="rtl">
      <body style="font-family:Arial,sans-serif;line-height:1.8;color:#10233f">
        <h2 style="color:#0b5cff">بكجات Pakgat</h2>
        <p>مرحبًا {customer_name or 'عميل بكجات'}،</p>
        <p>تم إصدار قسيمتك بنجاح.</p>
        <p><strong>العرض:</strong> {product_name}</p>
        <p><strong>الكود:</strong> {voucher_code}</p>
        <p><strong>تاريخ الانتهاء:</strong>
           {expires_at.strftime('%Y-%m-%d %H:%M')}</p>
        <p>
          <img src="cid:voucher-qr" alt="QR" width="240"
               style="display:block;margin:20px auto">
        </p>
        <p style="text-align:center">
          <a href="{verification_url}"
             style="display:inline-block;padding:13px 24px;background:#0b5cff;
                    color:white;text-decoration:none;border-radius:10px">
            فتح القسيمة
          </a>
        </p>
        <p><strong>تنبيه:</strong>
           أظهر القسيمة للتاجر عند استلام الخدمة فقط.</p>
      </body>
    </html>
    """

    message.add_alternative(html, subtype="html")
    html_part = message.get_payload()[-1]
    html_part.add_related(
        generate_qr_png(verification_url),
        maintype="image",
        subtype="png",
        cid="<voucher-qr>",
        filename="pakgat-voucher-qr.png",
    )

    if smtp_port == 465:
        with smtplib.SMTP_SSL(
            smtp_host,
            smtp_port,
            timeout=20,
        ) as smtp:
            smtp.login(smtp_user, smtp_password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(
            smtp_host,
            smtp_port,
            timeout=20,
        ) as smtp:
            smtp.starttls()
            smtp.login(smtp_user, smtp_password)
            smtp.send_message(message)


def create_voucher_record(
    db: Session,
    order_id: str,
    product_id: str,
    product_name: str,
    merchant_name: str,
    customer_name: Optional[str],
    customer_phone: Optional[str],
    option_name: Optional[str],
    validity_days: int = 7,
) -> Voucher:
    existing = db.scalar(
        select(Voucher).where(
            Voucher.order_id == order_id,
            Voucher.product_id == product_id,
        )
    )

    if existing:
        return existing

    voucher = Voucher(
        code=generate_voucher_code(),
        verification_token=generate_verification_token(),
        order_id=order_id,
        product_id=product_id,
        product_name=product_name,
        merchant_name=merchant_name,
        customer_name=customer_name,
        customer_phone=customer_phone,
        option_name=option_name,
        status="active",
        expires_at=datetime.now(timezone.utc)
        + timedelta(days=validity_days),
    )

    db.add(voucher)
    db.commit()
    db.refresh(voucher)
    return voucher


@app.get("/")
def home():
    return {
        "status": "running",
        "service": "Pakgat Voucher System",
        "version": "1.4",
        "database": "connected",
    }


@app.get("/health")
def health():
    with engine.connect():
        pass

    return {
        "ok": True,
        "database": "connected",
    }


@app.post(
    "/api/vouchers",
    response_model=VoucherResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_voucher(
    payload: VoucherCreate,
    db: Session = Depends(get_db),
):
    existing = db.scalar(
        select(Voucher).where(
            Voucher.order_id == payload.order_id,
            Voucher.product_id == payload.product_id,
        )
    )

    if existing:
        raise HTTPException(
            status_code=409,
            detail="A voucher already exists for this order and product.",
        )

    voucher = Voucher(
        code=generate_voucher_code(),
        verification_token=generate_verification_token(),
        order_id=payload.order_id,
        product_id=payload.product_id,
        product_name=payload.product_name,
        merchant_name=payload.merchant_name,
        customer_name=payload.customer_name,
        customer_phone=payload.customer_phone,
        option_name=payload.option_name,
        status="active",
        expires_at=datetime.now(timezone.utc)
        + timedelta(days=payload.validity_days),
    )

    db.add(voucher)
    db.commit()
    db.refresh(voucher)

    return VoucherResponse(
        code=voucher.code,
        verification_token=voucher.verification_token,
        verification_url=(
            BASE_URL + "/v/" + voucher.verification_token
        ),
        status=voucher.status,
        expires_at=voucher.expires_at,
    )


def update_voucher_status(
    voucher: Voucher,
    db: Session,
) -> str:
    current_time = datetime.now(timezone.utc)

    if (
        voucher.status == "active"
        and voucher.expires_at < current_time
    ):
        voucher.status = "expired"
        db.commit()
        db.refresh(voucher)

    return voucher.status


def build_verification_page(
    voucher: Voucher,
    error_message: Optional[str] = None,
) -> str:
    if voucher.status == "active":
        status_title = "القسيمة صالحة"
        status_color = "#15803d"
        status_background = "#dcfce7"
        status_icon = "✓"

    elif voucher.status == "redeemed":
        status_title = "تم استخدام القسيمة"
        status_color = "#b91c1c"
        status_background = "#fee2e2"
        status_icon = "✓"

    elif voucher.status == "expired":
        status_title = "القسيمة منتهية"
        status_color = "#a16207"
        status_background = "#fef3c7"
        status_icon = "!"

    else:
        status_title = "حالة القسيمة غير معروفة"
        status_color = "#475569"
        status_background = "#e2e8f0"
        status_icon = "?"

    redeem_section = ""

    if voucher.status == "active":
        error_box = ""

        if error_message:
            error_box = f"""
            <div class="error-box">
                {error_message}
            </div>
            """

        redeem_section = f"""
        {error_box}

        <form method="post"
              action="/v/{voucher.verification_token}/redeem"
              onsubmit="return confirm('هل أنت متأكد من تسليم الخدمة للعميل؟');">

            <label class="merchant-code-label"
                   for="merchant_code">
                رمز التاجر
            </label>

            <input
                id="merchant_code"
                name="merchant_code"
                class="merchant-code-input"
                type="password"
                inputmode="numeric"
                autocomplete="off"
                maxlength="20"
                placeholder="أدخل رمز التاجر"
                required
            >

            <button type="submit" class="redeem-button">
                تأكيد تسليم الخدمة للعميل
            </button>
        </form>

        <div class="employee-note">
            <strong>تعليمات للموظف</strong>
            <p>رحّب بعميلك وعميل بكجات بابتسامة.</p>
            <p>تأكد من مطابقة الخدمة قبل الضغط على الزر.</p>
            <p>أدخل رمز التاجر ثم أكد تقديم الخدمة.</p>
            <p>بعد الاعتماد لن يمكن استخدام القسيمة مرة أخرى.</p>
        </div>
        """

    redeemed_details = ""

    if voucher.status == "redeemed" and voucher.redeemed_at:
        redeemed_details = f"""
        <div class="used-details">
            تم استخدام القسيمة بتاريخ:
            <strong>
                {voucher.redeemed_at.strftime("%Y-%m-%d %H:%M")}
            </strong>
        </div>
        """

    return f"""
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport"
              content="width=device-width, initial-scale=1.0">
        <title>التحقق من قسيمة بكجات</title>

        <style>
            * {{
                box-sizing: border-box;
            }}

            body {{
                margin: 0;
                min-height: 100vh;
                padding: 20px;
                display: flex;
                align-items: center;
                justify-content: center;
                font-family: Arial, sans-serif;
                background: linear-gradient(
                    135deg,
                    #eff6ff,
                    #ffffff,
                    #dbeafe
                );
                color: #10233f;
            }}

            .card {{
                width: 100%;
                max-width: 560px;
                padding: 28px;
                background: #ffffff;
                border: 1px solid #dbeafe;
                border-radius: 28px;
                box-shadow:
                    0 22px 70px rgba(11, 92, 255, 0.15);
            }}

            .brand {{
                margin-bottom: 22px;
                text-align: center;
            }}

            .brand-ar {{
                margin: 0;
                color: #0b5cff;
                font-size: 42px;
                font-weight: 900;
            }}

            .brand-en {{
                margin-top: -5px;
                color: #0b5cff;
                font-size: 24px;
                font-weight: 800;
            }}

            .status-box {{
                padding: 18px;
                margin-bottom: 24px;
                text-align: center;
                border-radius: 18px;
                color: {status_color};
                background: {status_background};
            }}

            .status-icon {{
                width: 54px;
                height: 54px;
                margin: 0 auto 10px;
                display: flex;
                align-items: center;
                justify-content: center;
                border-radius: 50%;
                color: #ffffff;
                background: {status_color};
                font-size: 30px;
                font-weight: bold;
            }}

            .status-title {{
                margin: 0;
                font-size: 25px;
                font-weight: 900;
            }}

            .service-name {{
                margin: 0 0 8px;
                text-align: center;
                font-size: 27px;
            }}

            .merchant-name {{
                margin: 0 0 24px;
                text-align: center;
                color: #64748b;
                font-size: 18px;
            }}

            .details {{
                overflow: hidden;
                border: 1px solid #e2e8f0;
                border-radius: 18px;
            }}

            .detail-row {{
                padding: 15px 18px;
                display: flex;
                justify-content: space-between;
                gap: 20px;
                border-bottom: 1px solid #e2e8f0;
            }}

            .detail-row:last-child {{
                border-bottom: 0;
            }}

            .label {{
                color: #64748b;
            }}

            .value {{
                font-weight: 800;
            }}

            .code {{
                direction: ltr;
                display: inline-block;
                color: #0b5cff;
                letter-spacing: 1px;
            }}

            .merchant-code-label {{
                display: block;
                margin-top: 20px;
                margin-bottom: 8px;
                color: #10233f;
                font-size: 16px;
                font-weight: 800;
            }}

            .merchant-code-input {{
                width: 100%;
                padding: 15px;
                border: 1px solid #cbd5e1;
                border-radius: 14px;
                outline: none;
                text-align: center;
                direction: ltr;
                font-size: 20px;
                letter-spacing: 3px;
            }}

            .merchant-code-input:focus {{
                border-color: #0b5cff;
                box-shadow: 0 0 0 4px rgba(11, 92, 255, 0.12);
            }}

            .error-box {{
                padding: 14px;
                margin-top: 18px;
                border: 1px solid #fecaca;
                border-radius: 14px;
                color: #991b1b;
                background: #fef2f2;
                text-align: center;
                font-weight: 800;
            }}

            .redeem-button {{
                width: 100%;
                padding: 17px;
                margin-top: 20px;
                border: 0;
                border-radius: 15px;
                cursor: pointer;
                color: #ffffff;
                background: linear-gradient(135deg, #0b5cff, #1648c8);
                box-shadow: 0 12px 28px rgba(11, 92, 255, 0.25);
                font-size: 18px;
                font-weight: 900;
            }}

            .employee-note {{
                padding: 18px;
                margin-top: 18px;
                border-radius: 16px;
                color: #475569;
                background: #f8fafc;
                line-height: 1.8;
            }}

            .employee-note strong {{
                display: block;
                margin-bottom: 7px;
                color: #10233f;
                font-size: 17px;
            }}

            .employee-note p {{
                margin: 5px 0;
            }}

            .used-details {{
                padding: 15px;
                margin-top: 16px;
                text-align: center;
                border-radius: 14px;
                color: #7f1d1d;
                background: #fff1f2;
            }}

            .footer {{
                margin-top: 22px;
                text-align: center;
                color: #94a3b8;
                font-size: 13px;
            }}

            @media (max-width: 600px) {{
                .card {{
                    padding: 22px 17px;
                }}

                .detail-row {{
                    flex-direction: column;
                    gap: 5px;
                }}
            }}
        </style>
    </head>

    <body>
        <main class="card">
            <header class="brand">
                <h1 class="brand-ar">بكجات</h1>
                <div class="brand-en">Pakgat</div>
            </header>

            <section class="status-box">
                <div class="status-icon">
                    {status_icon}
                </div>

                <h2 class="status-title">
                    {status_title}
                </h2>
            </section>

            <h2 class="service-name">
                {voucher.product_name}
            </h2>

            <p class="merchant-name">
                {voucher.merchant_name}
            </p>

            <section class="details">
                <div class="detail-row">
                    <span class="label">كود القسيمة</span>
                    <span class="value code">{voucher.code}</span>
                </div>

                <div class="detail-row">
                    <span class="label">الخيار</span>
                    <span class="value">
                        {voucher.option_name or "غير محدد"}
                    </span>
                </div>

                <div class="detail-row">
                    <span class="label">اسم العميل</span>
                    <span class="value">
                        {voucher.customer_name or "عميل بكجات"}
                    </span>
                </div>

                <div class="detail-row">
                    <span class="label">تاريخ الانتهاء</span>
                    <span class="value">
                        {voucher.expires_at.strftime("%Y-%m-%d %H:%M")}
                    </span>
                </div>
            </section>

            {redeem_section}

            {redeemed_details}

            <footer class="footer">
                نظام التحقق من القسائم — Pakgat
            </footer>
        </main>
    </body>
    </html>
    """


@app.get(
    "/v/{verification_token}",
    response_class=HTMLResponse,
)
def verify_voucher(
    verification_token: str,
    db: Session = Depends(get_db),
):
    voucher = db.scalar(
        select(Voucher).where(
            Voucher.verification_token == verification_token
        )
    )

    if not voucher:
        return HTMLResponse(
            content="""
            <!DOCTYPE html>
            <html lang="ar" dir="rtl">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport"
                      content="width=device-width, initial-scale=1.0">
                <title>القسيمة غير موجودة</title>
            </head>

            <body style="
                font-family: Arial;
                text-align: center;
                padding: 60px;
                background: #f8fafc;
            ">
                <h1 style="color:#b91c1c">
                    القسيمة غير موجودة
                </h1>
                <p>تأكد من صحة رابط القسيمة.</p>
            </body>
            </html>
            """,
            status_code=404,
        )

    update_voucher_status(voucher, db)

    return HTMLResponse(
        content=build_verification_page(voucher)
    )


@app.post(
    "/v/{verification_token}/redeem",
    response_class=HTMLResponse,
)
async def redeem_voucher(
    verification_token: str,
    request: Request,
    db: Session = Depends(get_db),
):
    voucher = db.scalar(
        select(Voucher).where(
            Voucher.verification_token == verification_token
        )
    )

    if not voucher:
        return HTMLResponse(
            content="""
            <!DOCTYPE html>
            <html lang="ar" dir="rtl">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport"
                      content="width=device-width, initial-scale=1.0">
                <title>القسيمة غير موجودة</title>
            </head>
            <body style="
                font-family: Arial;
                text-align: center;
                padding: 60px;
                background: #f8fafc;
            ">
                <h1 style="color:#b91c1c">
                    القسيمة غير موجودة
                </h1>
                <p>تأكد من صحة رابط القسيمة.</p>
            </body>
            </html>
            """,
            status_code=404,
        )

    update_voucher_status(voucher, db)

    if voucher.status == "expired":
        return HTMLResponse(
            content=build_verification_page(voucher),
            status_code=410,
        )

    if voucher.status == "redeemed":
        return HTMLResponse(
            content=build_verification_page(voucher),
            status_code=409,
        )

    raw_form = (await request.body()).decode(
        "utf-8",
        errors="ignore",
    )
    form_data = parse_qs(raw_form)
    entered_code = (
        form_data.get("merchant_code", [""])[0].strip()
    )

    expected_code = str(
        MERCHANT_CODES.get(voucher.merchant_name)
        or MERCHANT_CODES.get("*")
        or ""
    ).strip()

    if not expected_code:
        return HTMLResponse(
            content=build_verification_page(
                voucher,
                "لم يتم إعداد رمز لهذا التاجر. تواصل مع إدارة بكجات.",
            ),
            status_code=503,
        )

    if not hmac.compare_digest(
        entered_code,
        expected_code,
    ):
        return HTMLResponse(
            content=build_verification_page(
                voucher,
                "رمز التاجر غير صحيح. حاول مرة أخرى.",
            ),
            status_code=403,
        )

    voucher.status = "redeemed"
    voucher.redeemed_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(voucher)

    return HTMLResponse(
        content=build_verification_page(voucher)
    )


@app.get(
    "/v/{verification_token}/qr.png",
    response_class=Response,
)
def voucher_qr(
    verification_token: str,
    db: Session = Depends(get_db),
):
    voucher = db.scalar(
        select(Voucher).where(
            Voucher.verification_token == verification_token
        )
    )

    if not voucher:
        raise HTTPException(
            status_code=404,
            detail="Voucher not found.",
        )

    verification_url = BASE_URL + "/v/" + verification_token

    return Response(
        content=generate_qr_png(verification_url),
        media_type="image/png",
        headers={
            "Cache-Control": "private, max-age=300",
        },
    )


@app.post("/webhooks/salla")
async def salla_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    raw_body = await request.body()
    received_signature = request.headers.get(
        "x-salla-signature",
        "",
    )

    if not verify_salla_signature(
        raw_body,
        received_signature,
    ):
        return JSONResponse(
            status_code=401,
            content={
                "ok": False,
                "detail": "Invalid Salla signature.",
            },
        )

    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "detail": "Invalid JSON.",
            },
        )

    event = str(payload.get("event") or "")
    data = payload.get("data") or {}

    if event != "order.payment.updated":
        return {
            "ok": True,
            "ignored": True,
            "reason": "Unsupported event.",
        }

    payment_status = str(
        first_value(
            data,
            "payment.status.slug",
            "payment.status",
            "payment_status",
            "status.slug",
        )
        or ""
    ).lower()

    if payment_status not in {
        "paid",
        "completed",
        "success",
        "successful",
    }:
        return {
            "ok": True,
            "ignored": True,
            "reason": "Order payment is not paid.",
            "payment_status": payment_status,
        }

    base_order_id = str(
        first_value(
            data,
            "id",
            "order.id",
            "reference_id",
        )
        or ""
    )

    if not base_order_id:
        return JSONResponse(
            status_code=422,
            content={
                "ok": False,
                "detail": "Order ID is missing.",
            },
        )

    customer_name = str(
        first_value(
            data,
            "customer.name",
            "customer.first_name",
        )
        or "عميل بكجات"
    )
    customer_email = str(
        first_value(
            data,
            "customer.email",
            "email",
        )
        or ""
    )
    customer_phone = str(
        first_value(
            data,
            "customer.mobile",
            "customer.phone",
            "mobile",
        )
        or ""
    )
    merchant_name = str(
        first_value(
            payload,
            "merchant.name",
            "merchant.store_name",
        )
        or "Pakgat"
    )

    created = []

    for item in normalize_items(data):
        product_id = item_product_id(item)

        if product_id not in VOUCHER_PRODUCT_IDS:
            continue

        quantity = item_quantity(item)

        for index in range(1, quantity + 1):
            voucher_order_id = (
                f"{base_order_id}:{product_id}:{index}"
            )

            voucher = create_voucher_record(
                db=db,
                order_id=voucher_order_id,
                product_id=product_id,
                product_name=item_product_name(item),
                merchant_name=merchant_name,
                customer_name=customer_name,
                customer_phone=customer_phone,
                option_name=item_option_name(item),
                validity_days=int(
                    os.getenv(
                        "DEFAULT_VALIDITY_DAYS",
                        "7",
                    )
                ),
            )

            verification_url = (
                BASE_URL
                + "/v/"
                + voucher.verification_token
            )

            created.append(
                {
                    "code": voucher.code,
                    "verification_url": verification_url,
                }
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

    return {
        "ok": True,
        "event": event,
        "created_count": len(created),
        "email_queued": bool(
            created and customer_email
        ),
        "vouchers": created,
    }
