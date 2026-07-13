import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI
from sqlalchemy import DateTime, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


database_url = os.environ["DATABASE_URL"]

# يجعل رابط Render متوافقًا مع SQLAlchemy + Psycopg
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Pakgat Voucher System",
    version="1.1",
    lifespan=lifespan,
)


@app.get("/")
def home():
    return {
        "status": "running",
        "service": "Pakgat Voucher System",
        "version": "1.1",
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
