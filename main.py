import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, FastAPI, Form, HTTPException, status
from fastapi.responses import HTMLResponse
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
    version="1.2",
    lifespan=lifespan,
)


@app.get("/")
def home():
    return {
        "status": "running",
        "service": "Pakgat Voucher System",
        "version": "1.2",
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
            "https://pakgat-voucher-system.onrender.com/v/"
            + voucher.verification_token
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
                    <span class="label">
                        كود القسيمة
                    </span>

                    <span class="value code">
                        {voucher.code}
                    </span>
                </div>

                <div class="detail-row">
                    <span class="label">
                        الخيار
                    </span>

                    <span class="value">
                        {voucher.option_name or "غير محدد"}
                    </span>
                </div>

                <div class="detail-row">
                    <span class="label">
                        اسم العميل
                    </span>

                    <span class="value">
                        {voucher.customer_name or "عميل بكجات"}
                    </span>
                </div>

                <div class="detail-row">
                    <span class="label">
                        تاريخ الانتهاء
                    </span>

                    <span class="value">
                        {voucher.expires_at.strftime("%Y-%m-%d %H:%M")}
                    </span>
                </div>
            </section>

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
            Voucher.verification_token
            == verification_token
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
                      content="width=device-width,
                      initial-scale=1.0">
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

                <p>
                    تأكد من صحة رابط القسيمة.
                </p>
            </body>
            </html>
            """,
            status_code=404,
        )

    update_voucher_status(voucher, db)

    return HTMLResponse(
        content=build_verification_page(voucher)
    )
