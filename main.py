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
