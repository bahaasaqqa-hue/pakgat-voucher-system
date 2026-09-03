"""Pakgat merchant, product commission and settlement extension.

This module is intentionally additive. It does not replace the existing voucher,
Salla or WhatsLoop flows; it stores merchant/finance state around them.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional
from urllib.parse import parse_qs

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import DateTime, Integer, Numeric, String, UniqueConstraint, func, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Mapped, Session, mapped_column

from app import application as core
from app import gce_entry as gce


RIYADH_TZ = timezone(timedelta(hours=3))
MONEY_PLACES = Decimal("0.01")


def _money(value: Optional[Decimal]) -> Decimal:
    return Decimal(value or 0).quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)


def _decimal(value) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value)).quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)
    except Exception:
        return None


class Merchant(core.Base):
    __tablename__ = "merchants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255), index=True)
    legal_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    commercial_registration: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    vat_registered: Mapped[int] = mapped_column(Integer, default=0)
    tax_number: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    contact_phone: Mapped[Optional[str]] = mapped_column(String(40), nullable=True, index=True)
    contact_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    iban: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    bank_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    settlement_frequency: Mapped[str] = mapped_column(String(30), default="weekly")
    settlement_day: Mapped[int] = mapped_column(Integer, default=3)  # Monday=0, Thursday=3
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=core.now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=core.now_utc)


class MerchantProductLink(core.Base):
    __tablename__ = "merchant_product_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    merchant_id: Mapped[int] = mapped_column(Integer, index=True)
    product_id: Mapped[Optional[str]] = mapped_column(String(100), unique=True, index=True, nullable=True)
    sku: Mapped[Optional[str]] = mapped_column(String(150), unique=True, index=True, nullable=True)
    product_name_snapshot: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    commission_percent: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2), nullable=True)
    sales_rep_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    product_status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    offer_ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_salla_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=core.now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=core.now_utc)


class MerchantContract(core.Base):
    __tablename__ = "merchant_contracts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    merchant_id: Mapped[int] = mapped_column(Integer, index=True)
    agreement_number: Mapped[Optional[str]] = mapped_column(String(40), nullable=True, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(40), default="draft", index=True)
    sadq_document_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    sadq_transaction_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    signed_document_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    signed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=core.now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=core.now_utc)


class MerchantContractDelivery(core.Base):
    __tablename__ = "merchant_contract_deliveries"
    __table_args__ = (
        UniqueConstraint("merchant_contract_id", "channel", name="uq_contract_delivery_channel"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    merchant_contract_id: Mapped[int] = mapped_column(Integer, index=True)
    merchant_id: Mapped[int] = mapped_column(Integer, index=True)
    channel: Mapped[str] = mapped_column(String(30), default="whatsapp", index=True)
    destination: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    provider_message_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=core.now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=core.now_utc)


class MerchantNote(core.Base):
    __tablename__ = "merchant_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    merchant_id: Mapped[int] = mapped_column(Integer, index=True)
    note_type: Mapped[str] = mapped_column(String(40), default="general", index=True)
    text: Mapped[str] = mapped_column(String(2000))
    created_by: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=core.now_utc, index=True)


class VoucherFinancialSnapshot(core.Base):
    __tablename__ = "voucher_financial_snapshots"
    __table_args__ = (UniqueConstraint("voucher_id", name="uq_voucher_financial_snapshot"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    voucher_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    merchant_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    order_id: Mapped[str] = mapped_column(String(120), index=True)
    product_id: Mapped[str] = mapped_column(String(100), index=True)
    gross_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="SAR")
    commission_percent: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=core.now_utc)


class MerchantPayable(core.Base):
    __tablename__ = "merchant_payables"
    __table_args__ = (UniqueConstraint("voucher_id", name="uq_merchant_payable_voucher"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    voucher_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    merchant_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    gross_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    commission_percent: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2), nullable=True)
    commission_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    merchant_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    settlement_batch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=core.now_utc, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=core.now_utc)


class SettlementBatch(core.Base):
    __tablename__ = "settlement_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    merchant_id: Mapped[int] = mapped_column(Integer, index=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    gross_redeemed_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    commission_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    payable_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    note: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=core.now_utc)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class SettlementPayment(core.Base):
    __tablename__ = "settlement_payments"
    __table_args__ = (UniqueConstraint("settlement_batch_id", name="uq_settlement_payment_batch"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    settlement_batch_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    merchant_id: Mapped[int] = mapped_column(Integer, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    transfer_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    bank_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    iban_snapshot: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    bank_reference: Mapped[str] = mapped_column(String(255), index=True)
    recorded_by: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=core.now_utc)


FINANCE_TABLES = [
    Merchant.__table__,
    MerchantProductLink.__table__,
    MerchantContract.__table__,
    MerchantContractDelivery.__table__,
    MerchantNote.__table__,
    VoucherFinancialSnapshot.__table__,
    MerchantPayable.__table__,
    SettlementBatch.__table__,
    SettlementPayment.__table__,
]


def ensure_merchant_finance_schema() -> None:
    """Create only new additive finance tables; never mutate legacy tables."""
    core.Base.metadata.create_all(bind=core.engine, tables=FINANCE_TABLES)


def next_agreement_number(db: Session, when: Optional[datetime] = None) -> str:
    """Return the next immutable Pakgat merchant-agreement number for a Riyadh month."""
    current = when or core.now_utc()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(RIYADH_TZ)
    prefix = f"PKG-MA-{current.year:04d}-{current.month:02d}-"
    values = list(
        db.scalars(
            select(MerchantContract.agreement_number).where(
                MerchantContract.agreement_number.like(prefix + "%")
            )
        ).all()
    )
    highest = 0
    for value in values:
        raw = str(value or "")
        if not raw.startswith(prefix):
            continue
        suffix = raw[len(prefix):]
        if len(suffix) == 4 and suffix.isdigit():
            highest = max(highest, int(suffix))
    if highest >= 9999:
        raise RuntimeError("Monthly merchant agreement sequence exhausted")
    return f"{prefix}{highest + 1:04d}"


def _new_merchant_code(db: Session) -> str:
    for _ in range(12):
        code = "PKG-M-" + secrets.token_hex(4).upper()
        if not db.scalar(select(Merchant.id).where(Merchant.code == code)):
            return code
    raise RuntimeError("Unable to generate merchant code")


def get_product_link(db: Session, product_id: str = "", sku: str = "") -> Optional[MerchantProductLink]:
    conditions = []
    product_id = str(product_id or "").strip()
    sku = str(sku or "").strip().upper()
    if product_id:
        conditions.append(MerchantProductLink.product_id == product_id)
    if sku:
        conditions.append(MerchantProductLink.sku == sku)
    if not conditions:
        return None
    return db.scalar(select(MerchantProductLink).where(or_(*conditions)).limit(1))


def backfill_local_partners(db: Session) -> int:
    """Mirror existing local partner rows into the new merchant layer.

    Commission is intentionally left unset; Pakgat must approve it per product.
    """
    try:
        rows = list(db.scalars(select(gce.LocalPartnerProduct)).all())
    except SQLAlchemyError:
        return 0
    added = 0
    for row in rows:
        phone = core.normalize_saudi_phone(row.merchant_phone or "") or (row.merchant_phone or "").strip()
        merchant = db.scalar(
            select(Merchant).where(
                Merchant.display_name == row.partner_name,
                Merchant.contact_phone == (phone or None),
            )
        )
        if not merchant:
            merchant = Merchant(
                code=_new_merchant_code(db),
                display_name=row.partner_name,
                contact_phone=phone or None,
                status="active",
                created_at=core.now_utc(),
                updated_at=core.now_utc(),
            )
            db.add(merchant)
            db.flush()
            added += 1
        link = get_product_link(db, row.product_id or "", row.sku or "")
        if not link:
            link = MerchantProductLink(
                merchant_id=merchant.id,
                product_id=row.product_id or None,
                sku=(row.sku or "").upper() or None,
                product_name_snapshot=row.product_name or None,
                commission_percent=None,
                product_status="active",
                last_salla_sync_at=row.updated_at,
                created_at=core.now_utc(),
                updated_at=core.now_utc(),
            )
            db.add(link)
            added += 1
    if added:
        db.commit()
    return added


def item_unit_gross_amount(item: dict) -> Optional[Decimal]:
    """Read a conservative per-unit amount from common Salla item shapes."""
    quantity = max(1, core.item_quantity(item))
    unit_candidates = (
        "price.amount",
        "price",
        "unit_price.amount",
        "unit_price",
        "amounts.price.amount",
        "amounts.price",
    )
    for path in unit_candidates:
        value = core.first_value(item, path)
        if isinstance(value, dict):
            value = value.get("amount") or value.get("value")
        parsed = _decimal(value)
        if parsed is not None:
            return parsed
    total_candidates = (
        "amounts.total.amount",
        "amounts.total",
        "total.amount",
        "total",
    )
    for path in total_candidates:
        value = core.first_value(item, path)
        if isinstance(value, dict):
            value = value.get("amount") or value.get("value")
        parsed = _decimal(value)
        if parsed is not None:
            return _money(parsed / Decimal(quantity))
    return None


def capture_voucher_financial_snapshot(
    db: Session,
    voucher: core.Voucher,
    item: dict,
    *,
    commit: bool = True,
) -> VoucherFinancialSnapshot:
    existing = db.scalar(
        select(VoucherFinancialSnapshot).where(VoucherFinancialSnapshot.voucher_id == voucher.id)
    )
    if existing:
        return existing
    link = get_product_link(db, voucher.product_id, core.item_sku(item))
    snapshot = VoucherFinancialSnapshot(
        voucher_id=voucher.id,
        merchant_id=link.merchant_id if link else None,
        order_id=voucher.order_id,
        product_id=voucher.product_id,
        gross_amount=item_unit_gross_amount(item),
        currency="SAR",
        commission_percent=link.commission_percent if link else None,
        created_at=core.now_utc(),
    )
    db.add(snapshot)
    if commit:
        db.commit()
        db.refresh(snapshot)
    else:
        db.flush()
    return snapshot


def ensure_payable_for_redeemed_voucher(db: Session, voucher: core.Voucher) -> Optional[MerchantPayable]:
    if voucher.status != "redeemed":
        return None
    existing = db.scalar(select(MerchantPayable).where(MerchantPayable.voucher_id == voucher.id))
    if existing:
        return existing
    snapshot = db.scalar(
        select(VoucherFinancialSnapshot).where(VoucherFinancialSnapshot.voucher_id == voucher.id)
    )
    link = get_product_link(db, voucher.product_id)
    merchant_id = (snapshot.merchant_id if snapshot else None) or (link.merchant_id if link else None)
    gross = snapshot.gross_amount if snapshot else None
    commission_percent = (
        snapshot.commission_percent if snapshot and snapshot.commission_percent is not None
        else (link.commission_percent if link else None)
    )
    status = "pending"
    commission_amount = merchant_amount = None
    if merchant_id is None or gross is None or commission_percent is None:
        status = "review_required"
    else:
        commission_amount = _money(Decimal(gross) * Decimal(commission_percent) / Decimal("100"))
        merchant_amount = _money(Decimal(gross) - commission_amount)
    payable = MerchantPayable(
        voucher_id=voucher.id,
        merchant_id=merchant_id,
        gross_amount=gross,
        commission_percent=commission_percent,
        commission_amount=commission_amount,
        merchant_amount=merchant_amount,
        status=status,
        created_at=voucher.redeemed_at or core.now_utc(),
        updated_at=core.now_utc(),
    )
    db.add(payable)
    try:
        db.commit()
        db.refresh(payable)
        return payable
    except IntegrityError:
        db.rollback()
        return db.scalar(select(MerchantPayable).where(MerchantPayable.voucher_id == voucher.id))


def reconcile_redeemed_payables(db: Session) -> int:
    missing = list(
        db.scalars(
            select(core.Voucher)
            .outerjoin(MerchantPayable, MerchantPayable.voucher_id == core.Voucher.id)
            .where(core.Voucher.status == "redeemed", MerchantPayable.id.is_(None))
        ).all()
    )
    added = 0
    for voucher in missing:
        if ensure_payable_for_redeemed_voucher(db, voucher):
            added += 1
    return added


def mark_order_vouchers_refunded_or_revoked(
    db: Session,
    base_order_id: str,
    target_status: str,
    product_ids: Optional[set[str]] = None,
) -> dict:
    if target_status not in {"refunded", "revoked"}:
        raise ValueError("Unsupported terminal voucher status")
    base_order_id = str(base_order_id or "").strip()
    if not base_order_id:
        return {"changed": 0, "redeemed_review": 0}
    candidates = list(
        db.scalars(
            select(core.Voucher).where(
                or_(
                    core.Voucher.order_id == base_order_id,
                    core.Voucher.order_id.like(base_order_id + ":%"),
                )
            )
        ).all()
    )
    changed = redeemed_review = 0
    for voucher in candidates:
        if product_ids and str(voucher.product_id) not in product_ids:
            continue
        if voucher.status == "active":
            voucher.status = target_status
            changed += 1
            db.add(
                core.AuditLog(
                    voucher_id=voucher.id,
                    action=f"voucher_{target_status}",
                    details=f"Salla order event changed active voucher to {target_status}",
                    created_at=core.now_utc(),
                )
            )
        elif voucher.status == "redeemed":
            redeemed_review += 1
            db.add(
                core.AuditLog(
                    voucher_id=voucher.id,
                    action="refund_after_redemption_review",
                    details=f"Salla requested {target_status} after voucher redemption",
                    created_at=core.now_utc(),
                )
            )
    db.commit()
    return {"changed": changed, "redeemed_review": redeemed_review}


def next_thursday(value: Optional[datetime] = None) -> datetime:
    current = (value or core.now_utc()).astimezone(RIYADH_TZ)
    days = (3 - current.weekday()) % 7
    target = current + timedelta(days=days)
    return target.replace(hour=12, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def build_weekly_settlement_batch(
    db: Session,
    merchant_id: int,
    as_of: Optional[datetime] = None,
) -> Optional[SettlementBatch]:
    rows = list(
        db.scalars(
            select(MerchantPayable)
            .where(
                MerchantPayable.merchant_id == merchant_id,
                MerchantPayable.status == "pending",
                MerchantPayable.settlement_batch_id.is_(None),
                MerchantPayable.merchant_amount.is_not(None),
            )
            .order_by(MerchantPayable.created_at.asc())
        ).all()
    )
    if not rows:
        return None
    as_of = as_of or core.now_utc()
    batch = SettlementBatch(
        merchant_id=merchant_id,
        period_start=min(row.created_at for row in rows),
        period_end=as_of,
        due_at=next_thursday(as_of),
        status="draft",
        gross_redeemed_amount=_money(sum((Decimal(row.gross_amount or 0) for row in rows), Decimal("0"))),
        commission_amount=_money(sum((Decimal(row.commission_amount or 0) for row in rows), Decimal("0"))),
        payable_amount=_money(sum((Decimal(row.merchant_amount or 0) for row in rows), Decimal("0"))),
        created_at=core.now_utc(),
    )
    db.add(batch)
    db.flush()
    for row in rows:
        row.settlement_batch_id = batch.id
        row.status = "batched"
        row.updated_at = core.now_utc()
    db.commit()
    db.refresh(batch)
    return batch


def approve_settlement_batch(db: Session, batch_id: int) -> SettlementBatch:
    batch = db.get(SettlementBatch, batch_id)
    if not batch:
        raise ValueError("Settlement batch not found")
    if batch.status == "paid":
        return batch
    if batch.status not in {"draft", "on_hold"}:
        raise ValueError("Settlement batch cannot be approved")
    batch.status = "approved"
    batch.approved_at = core.now_utc()
    db.commit()
    db.refresh(batch)
    return batch


def record_settlement_payment(
    db: Session,
    batch_id: int,
    *,
    amount: Decimal,
    bank_reference: str,
    transfer_at: Optional[datetime] = None,
    bank_name: str = "",
    iban_snapshot: str = "",
    recorded_by: str = "",
    note: str = "",
) -> SettlementPayment:
    batch = db.get(SettlementBatch, batch_id)
    if not batch:
        raise ValueError("Settlement batch not found")
    existing = db.scalar(select(SettlementPayment).where(SettlementPayment.settlement_batch_id == batch_id))
    if existing:
        return existing
    if batch.status != "approved":
        raise ValueError("Settlement must be approved before payment")
    amount = _money(amount)
    if amount != _money(batch.payable_amount):
        raise ValueError("Transferred amount must match approved settlement amount")
    merchant = db.get(Merchant, batch.merchant_id)
    payment = SettlementPayment(
        settlement_batch_id=batch.id,
        merchant_id=batch.merchant_id,
        amount=amount,
        transfer_at=transfer_at or core.now_utc(),
        bank_name=(bank_name or (merchant.bank_name if merchant else "")) or None,
        iban_snapshot=(iban_snapshot or (merchant.iban if merchant else "")) or None,
        bank_reference=str(bank_reference or "").strip(),
        recorded_by=str(recorded_by or "").strip() or None,
        note=str(note or "").strip() or None,
        created_at=core.now_utc(),
    )
    if not payment.bank_reference:
        raise ValueError("Bank reference is required")
    db.add(payment)
    batch.status = "paid"
    batch.paid_at = payment.transfer_at
    payables = list(
        db.scalars(select(MerchantPayable).where(MerchantPayable.settlement_batch_id == batch.id)).all()
    )
    for payable in payables:
        payable.status = "paid"
        payable.updated_at = core.now_utc()
    db.commit()
    db.refresh(payment)
    return payment


def merchant_voucher_counts(db: Session, merchant: Merchant) -> dict[str, int]:
    product_ids = list(
        db.scalars(select(MerchantProductLink.product_id).where(
            MerchantProductLink.merchant_id == merchant.id,
            MerchantProductLink.product_id.is_not(None),
        )).all()
    )
    condition = core.Voucher.merchant_name == merchant.display_name
    if product_ids:
        condition = or_(condition, core.Voucher.product_id.in_(product_ids))
    rows = db.execute(
        select(core.Voucher.status, func.count(core.Voucher.id)).where(condition).group_by(core.Voucher.status)
    ).all()
    return dict(rows)


def merchant_due_amount(db: Session, merchant_id: int) -> Decimal:
    values = list(
        db.scalars(
            select(MerchantPayable.merchant_amount).where(
                MerchantPayable.merchant_id == merchant_id,
                MerchantPayable.status.in_(["pending", "batched"]),
                MerchantPayable.merchant_amount.is_not(None),
            )
        ).all()
    )
    return _money(sum((Decimal(v or 0) for v in values), Decimal("0")))


def finance_dashboard_html(db: Session) -> str:
    ensure_merchant_finance_schema()
    backfill_local_partners(db)
    reconcile_redeemed_payables(db)
    merchants = list(db.scalars(select(Merchant).order_by(Merchant.display_name)).all())
    unpaid = _money(sum((merchant_due_amount(db, m.id) for m in merchants), Decimal("0")))
    now = core.now_utc()
    week_start = now - timedelta(days=7)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    paid_week = _money(
        db.scalar(select(func.coalesce(func.sum(SettlementPayment.amount), 0)).where(SettlementPayment.transfer_at >= week_start)) or 0
    )
    paid_month = _money(
        db.scalar(select(func.coalesce(func.sum(SettlementPayment.amount), 0)).where(SettlementPayment.transfer_at >= month_start)) or 0
    )
    merchants_with_due = sum(1 for m in merchants if merchant_due_amount(db, m.id) > 0)
    rows = []
    for merchant in merchants:
        due = merchant_due_amount(db, merchant.id)
        if due <= 0:
            continue
        counts = merchant_voucher_counts(db, merchant)
        latest_payment = db.scalar(
            select(SettlementPayment).where(SettlementPayment.merchant_id == merchant.id).order_by(SettlementPayment.transfer_at.desc()).limit(1)
        )
        note = db.scalar(
            select(MerchantNote).where(MerchantNote.merchant_id == merchant.id).order_by(MerchantNote.created_at.desc()).limit(1)
        )
        rows.append(
            "<tr>"
            f"<td><a style='font-weight:900;color:#2446ba' href='/admin/merchants/{merchant.id}'>{core.esc(merchant.display_name)}</a></td>"
            f"<td>{counts.get('redeemed', 0)}</td>"
            f"<td><strong>{due:,.2f} ر.س</strong></td>"
            f"<td>{'بانتظار التسوية' if due else 'لا يوجد مستحق'}</td>"
            f"<td dir='ltr'>{core.esc(latest_payment.bank_reference if latest_payment else '—')}</td>"
            f"<td>{core.esc(note.text[:80] if note else '—')}</td>"
            "</tr>"
        )
    table_rows = "".join(rows) or "<tr><td colspan='6' style='text-align:center;padding:24px'>لا توجد مستحقات تجار غير مدفوعة حاليًا.</td></tr>"
    return f"""
    <section style='margin:20px 0'>
      <div style='display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap'>
        <h2 style='margin:0'>مستحقات التجار</h2>
        <a class='btn btn-blue' href='/admin/settlements'>إدارة التسويات</a>
      </div>
      <div class='grid grid-mobile-1' style='grid-template-columns:repeat(4,1fr);margin:14px 0'>
        <div class='card' style='padding:18px'><div class='muted'>غير مدفوع</div><strong style='font-size:25px'>{unpaid:,.2f} ر.س</strong></div>
        <div class='card' style='padding:18px'><div class='muted'>تجار لهم مستحقات</div><strong style='font-size:25px'>{merchants_with_due}</strong></div>
        <div class='card' style='padding:18px'><div class='muted'>دُفع آخر 7 أيام</div><strong style='font-size:25px'>{paid_week:,.2f} ر.س</strong></div>
        <div class='card' style='padding:18px'><div class='muted'>دُفع هذا الشهر</div><strong style='font-size:25px'>{paid_month:,.2f} ر.س</strong></div>
      </div>
      <div class='card' style='padding:18px'><div class='table-wrap'><table><thead><tr><th>التاجر</th><th>Redeemed</th><th>المستحق</th><th>الحالة</th><th>آخر حوالة</th><th>ملاحظة</th></tr></thead><tbody>{table_rows}</tbody></table></div></div>
    </section>
    """


def _admin_guard(request: Request):
    try:
        core.require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)
    return None


_original_page_shell = core.page_shell


def _page_shell_with_merchant_finance(title: str, body: str, admin: bool = False) -> str:
    html = _original_page_shell(title, body, admin=admin)
    if admin and 'href="/admin/merchants"' not in html:
        marker = '<a class="btn btn-muted" href="/admin/local-partners">بيانات الشركاء</a>'
        extra = marker + '<a class="btn btn-muted" href="/admin/merchants">التجار</a><a class="btn btn-muted" href="/admin/settlements">التسويات</a>'
        if marker in html:
            html = html.replace(marker, extra)
        else:
            marker = '<a class="btn btn-muted" href="/admin/integrations">تكامل سلة</a>'
            html = html.replace(marker, marker + '<a class="btn btn-muted" href="/admin/merchants">التجار</a><a class="btn btn-muted" href="/admin/settlements">التسويات</a>')
    return html


core.page_shell = _page_shell_with_merchant_finance


@core.app.get("/admin/merchants", response_class=HTMLResponse)
def admin_merchants(request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_guard(request)
    if redirect:
        return redirect
    ensure_merchant_finance_schema()
    backfill_local_partners(db)
    reconcile_redeemed_payables(db)
    merchants = list(db.scalars(select(Merchant).order_by(Merchant.display_name)).all())
    rows = []
    for merchant in merchants:
        counts = merchant_voucher_counts(db, merchant)
        product_count = db.scalar(select(func.count(MerchantProductLink.id)).where(MerchantProductLink.merchant_id == merchant.id)) or 0
        due = merchant_due_amount(db, merchant.id)
        paid = _money(db.scalar(select(func.coalesce(func.sum(SettlementPayment.amount), 0)).where(SettlementPayment.merchant_id == merchant.id)) or 0)
        rows.append(
            "<tr>"
            f"<td><a style='font-weight:900;color:#2446ba' href='/admin/merchants/{merchant.id}'>{core.esc(merchant.display_name)}</a><div class='muted' dir='ltr'>{core.esc(merchant.code)}</div></td>"
            f"<td>{product_count}</td><td>{counts.get('redeemed', 0)}</td><td>{counts.get('refunded', 0)}</td><td>{counts.get('expired', 0)}</td>"
            f"<td><strong>{due:,.2f} ر.س</strong></td><td>{paid:,.2f} ر.س</td><td>{core.esc(merchant.status)}</td>"
            "</tr>"
        )
    body = f"""<main class='wrap' style='padding:28px 0 48px'><div style='display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap'><div><h1 style='margin-bottom:6px'>التجار</h1><p class='muted'>العقود، المنتجات، القسائم والمستحقات في ملف واحد.</p></div><a class='btn btn-blue' href='/admin/settlements'>مستحقات التجار</a></div><section class='card' style='padding:18px'><div class='table-wrap'><table><thead><tr><th>التاجر</th><th>المنتجات</th><th>Redeemed</th><th>Refunded</th><th>Expired</th><th>المستحق</th><th>مدفوع</th><th>الحالة</th></tr></thead><tbody>{''.join(rows) or "<tr><td colspan='8'>لا يوجد تجار بعد.</td></tr>"}</tbody></table></div></section></main>"""
    return HTMLResponse(core.page_shell("التجار", body, admin=True))


@core.app.get("/admin/merchants/{merchant_id}", response_class=HTMLResponse)
def admin_merchant_detail(merchant_id: int, request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_guard(request)
    if redirect:
        return redirect
    ensure_merchant_finance_schema()
    merchant = db.get(Merchant, merchant_id)
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
    reconcile_redeemed_payables(db)
    counts = merchant_voucher_counts(db, merchant)
    issued = sum(counts.values())
    redeemed = counts.get("redeemed", 0)
    refunded = counts.get("refunded", 0)
    redemption_rate = (redeemed / issued * 100) if issued else 0
    refund_rate = (refunded / issued * 100) if issued else 0
    due = merchant_due_amount(db, merchant.id)
    paid = _money(db.scalar(select(func.coalesce(func.sum(SettlementPayment.amount), 0)).where(SettlementPayment.merchant_id == merchant.id)) or 0)
    products = list(db.scalars(select(MerchantProductLink).where(MerchantProductLink.merchant_id == merchant.id).order_by(MerchantProductLink.updated_at.desc())).all())
    product_rows = "".join(
        "<tr>"
        f"<td>{core.esc(p.product_name_snapshot or '—')}</td><td dir='ltr'>{core.esc(p.product_id or '—')}</td><td dir='ltr'>{core.esc(p.sku or '—')}</td>"
        f"<td><form method='post' action='/admin/merchants/{merchant.id}/products/{p.id}/commission' style='display:flex;gap:6px'><input class='input' style='min-width:90px' name='commission_percent' type='number' min='0' max='100' step='0.01' value='{core.esc(p.commission_percent if p.commission_percent is not None else '')}' placeholder='%'><button class='btn btn-muted'>حفظ</button></form></td>"
        f"<td>{core.esc(p.product_status)}</td><td>{core.fmt_dt(p.offer_ends_at)}</td><td>{core.fmt_dt(p.last_salla_sync_at)}</td>"
        "</tr>"
        for p in products
    ) or "<tr><td colspan='7'>لا توجد منتجات مرتبطة.</td></tr>"
    notes = list(db.scalars(select(MerchantNote).where(MerchantNote.merchant_id == merchant.id).order_by(MerchantNote.created_at.desc()).limit(30)).all())
    note_rows = "".join(f"<tr><td>{core.fmt_dt(n.created_at)}</td><td>{core.esc(n.note_type)}</td><td>{core.esc(n.text)}</td><td>{core.esc(n.created_by or '—')}</td></tr>" for n in notes) or "<tr><td colspan='4'>لا توجد ملاحظات.</td></tr>"
    batches = list(db.scalars(select(SettlementBatch).where(SettlementBatch.merchant_id == merchant.id).order_by(SettlementBatch.created_at.desc()).limit(20)).all())
    batch_rows = "".join(
        f"<tr><td>#{b.id}</td><td>{core.fmt_dt(b.period_start)} — {core.fmt_dt(b.period_end)}</td><td>{_money(b.payable_amount):,.2f} ر.س</td><td>{core.esc(b.status)}</td><td>{core.fmt_dt(b.paid_at)}</td></tr>"
        for b in batches
    ) or "<tr><td colspan='5'>لا توجد تسويات.</td></tr>"
    body = f"""<main class='wrap' style='padding:28px 0 48px'><a class='btn btn-muted' href='/admin/merchants'>← التجار</a><h1>{core.esc(merchant.display_name)}</h1><div class='muted' dir='ltr'>{core.esc(merchant.code)}</div><div class='grid grid-mobile-1' style='grid-template-columns:repeat(6,1fr);margin:18px 0'><div class='card' style='padding:16px'><div class='muted'>Active</div><strong>{counts.get('active',0)}</strong></div><div class='card' style='padding:16px'><div class='muted'>Redeemed</div><strong>{redeemed}</strong></div><div class='card' style='padding:16px'><div class='muted'>Refunded</div><strong>{refunded}</strong></div><div class='card' style='padding:16px'><div class='muted'>Expired</div><strong>{counts.get('expired',0)}</strong></div><div class='card' style='padding:16px'><div class='muted'>المستحق</div><strong>{due:,.2f} ر.س</strong></div><div class='card' style='padding:16px'><div class='muted'>مدفوع</div><strong>{paid:,.2f} ر.س</strong></div></div><section class='card' style='padding:18px;margin-bottom:18px'><h2>ملخص الأداء</h2><p>Redemption Rate: <strong>{redemption_rate:.1f}%</strong> · Refund Rate: <strong>{refund_rate:.1f}%</strong></p><p><strong>IBAN:</strong> <span dir='ltr'>{core.esc(merchant.iban or 'غير مسجل')}</span> · <strong>البنك:</strong> {core.esc(merchant.bank_name or 'غير مسجل')}</p></section><section class='card' style='padding:18px;margin-bottom:18px'><h2>المنتجات</h2><div class='table-wrap'><table><thead><tr><th>المنتج</th><th>Product ID</th><th>SKU</th><th>نسبة Pakgat</th><th>الحالة</th><th>نهاية العرض</th><th>آخر مزامنة</th></tr></thead><tbody>{product_rows}</tbody></table></div></section><section class='card' style='padding:18px;margin-bottom:18px'><h2>التسويات</h2><div class='table-wrap'><table><thead><tr><th>رقم</th><th>الفترة</th><th>المبلغ</th><th>الحالة</th><th>الدفع</th></tr></thead><tbody>{batch_rows}</tbody></table></div></section><section class='card' style='padding:18px'><h2>الملاحظات</h2><form method='post' action='/admin/merchants/{merchant.id}/notes' class='grid grid-mobile-1' style='grid-template-columns:1fr 3fr auto;align-items:end'><div><label>النوع</label><select class='select' name='note_type'><option value='general'>عام</option><option value='finance'>مالي</option><option value='sales'>مبيعات</option><option value='contract'>عقد</option><option value='complaint'>شكوى</option><option value='operations'>تشغيل</option></select></div><div><label>الملاحظة</label><input class='input' name='text' required maxlength='2000'></div><button class='btn btn-blue'>إضافة</button></form><div class='table-wrap' style='margin-top:14px'><table><thead><tr><th>التاريخ</th><th>النوع</th><th>الملاحظة</th><th>بواسطة</th></tr></thead><tbody>{note_rows}</tbody></table></div></section></main>"""
    return HTMLResponse(core.page_shell("ملف التاجر", body, admin=True))


@core.app.post("/admin/merchants/{merchant_id}/products/{link_id}/commission")
async def admin_update_product_commission(merchant_id: int, link_id: int, request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_guard(request)
    if redirect:
        return redirect
    form = parse_qs((await request.body()).decode("utf-8", errors="replace"))
    raw = (form.get("commission_percent", [""])[0] or "").strip()
    value = _decimal(raw)
    if value is None or value < 0 or value > 100:
        raise HTTPException(status_code=422, detail="Commission must be between 0 and 100")
    link = db.get(MerchantProductLink, link_id)
    if not link or link.merchant_id != merchant_id:
        raise HTTPException(status_code=404, detail="Product link not found")
    link.commission_percent = value
    link.updated_at = core.now_utc()
    db.add(MerchantNote(merchant_id=merchant_id, note_type="finance", text=f"تم تحديث نسبة Pakgat للمنتج {link.product_name_snapshot or link.product_id} إلى {value}%", created_by=core.ADMIN_USERNAME, created_at=core.now_utc()))
    db.commit()
    return RedirectResponse(f"/admin/merchants/{merchant_id}", status_code=303)


@core.app.post("/admin/merchants/{merchant_id}/notes")
async def admin_add_merchant_note(merchant_id: int, request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_guard(request)
    if redirect:
        return redirect
    if not db.get(Merchant, merchant_id):
        raise HTTPException(status_code=404, detail="Merchant not found")
    form = parse_qs((await request.body()).decode("utf-8", errors="replace"))
    text = (form.get("text", [""])[0] or "").strip()
    note_type = (form.get("note_type", ["general"])[0] or "general").strip()[:40]
    if not text:
        raise HTTPException(status_code=422, detail="Note text is required")
    db.add(MerchantNote(merchant_id=merchant_id, note_type=note_type, text=text[:2000], created_by=core.ADMIN_USERNAME, created_at=core.now_utc()))
    db.commit()
    return RedirectResponse(f"/admin/merchants/{merchant_id}", status_code=303)


@core.app.get("/admin/settlements", response_class=HTMLResponse)
def admin_settlements(request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_guard(request)
    if redirect:
        return redirect
    ensure_merchant_finance_schema()
    backfill_local_partners(db)
    reconcile_redeemed_payables(db)
    merchants = list(db.scalars(select(Merchant).order_by(Merchant.display_name)).all())
    due_rows = []
    for merchant in merchants:
        due = merchant_due_amount(db, merchant.id)
        if due <= 0:
            continue
        due_rows.append(f"<tr><td><a href='/admin/merchants/{merchant.id}' style='font-weight:900;color:#2446ba'>{core.esc(merchant.display_name)}</a></td><td>{due:,.2f} ر.س</td><td>{core.fmt_dt(next_thursday())}</td><td><form method='post' action='/admin/settlements/build/{merchant.id}'><button class='btn btn-blue'>إنشاء تسوية</button></form></td></tr>")
    batches = list(db.scalars(select(SettlementBatch).order_by(SettlementBatch.created_at.desc()).limit(100)).all())
    batch_rows = []
    for batch in batches:
        merchant = db.get(Merchant, batch.merchant_id)
        payment = db.scalar(select(SettlementPayment).where(SettlementPayment.settlement_batch_id == batch.id))
        actions = ""
        if batch.status == "draft":
            actions = f"<form method='post' action='/admin/settlements/{batch.id}/approve'><button class='btn btn-muted'>اعتماد</button></form>"
        elif batch.status == "approved":
            actions = f"<details><summary class='btn btn-blue' style='list-style:none'>تسجيل التحويل</summary><form method='post' action='/admin/settlements/{batch.id}/pay' style='min-width:320px;margin-top:10px'><label>المبلغ</label><input class='input' name='amount' type='number' step='0.01' value='{_money(batch.payable_amount)}' required><label style='margin-top:8px'>رقم الحوالة</label><input class='input' name='bank_reference' required><label style='margin-top:8px'>البنك</label><input class='input' name='bank_name' value='{core.esc(merchant.bank_name if merchant else '')}'><label style='margin-top:8px'>IBAN</label><input class='input' name='iban_snapshot' dir='ltr' value='{core.esc(merchant.iban if merchant else '')}'><label style='margin-top:8px'>ملاحظة</label><input class='input' name='note'><button class='btn btn-blue' style='margin-top:10px'>تأكيد التحويل</button></form></details>"
        batch_rows.append(f"<tr><td>#{batch.id}</td><td>{core.esc(merchant.display_name if merchant else batch.merchant_id)}</td><td>{_money(batch.payable_amount):,.2f} ر.س</td><td>{core.esc(batch.status)}</td><td>{core.fmt_dt(batch.due_at)}</td><td dir='ltr'>{core.esc(payment.bank_reference if payment else '—')}</td><td>{actions}</td></tr>")
    body = f"""<main class='wrap' style='padding:28px 0 48px'><h1>مستحقات وتسويات التجار</h1><p class='muted'>التسوية الأسبوعية الافتراضية يوم الخميس. لا يدخل هنا إلا ما تم Redeem فعليًا.</p><section class='card' style='padding:18px;margin-bottom:18px'><h2>غير مدفوع</h2><div class='table-wrap'><table><thead><tr><th>التاجر</th><th>المستحق</th><th>موعد التسوية</th><th></th></tr></thead><tbody>{''.join(due_rows) or "<tr><td colspan='4'>لا توجد مبالغ جاهزة.</td></tr>"}</tbody></table></div></section><section class='card' style='padding:18px'><h2>سجل التسويات</h2><div class='table-wrap'><table><thead><tr><th>رقم</th><th>التاجر</th><th>المبلغ</th><th>الحالة</th><th>الاستحقاق</th><th>رقم الحوالة</th><th></th></tr></thead><tbody>{''.join(batch_rows) or "<tr><td colspan='7'>لا توجد تسويات بعد.</td></tr>"}</tbody></table></div></section></main>"""
    return HTMLResponse(core.page_shell("التسويات", body, admin=True))


@core.app.post("/admin/settlements/build/{merchant_id}")
def admin_build_settlement(merchant_id: int, request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_guard(request)
    if redirect:
        return redirect
    build_weekly_settlement_batch(db, merchant_id)
    return RedirectResponse("/admin/settlements", status_code=303)


@core.app.post("/admin/settlements/{batch_id}/approve")
def admin_approve_settlement(batch_id: int, request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_guard(request)
    if redirect:
        return redirect
    try:
        approve_settlement_batch(db, batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return RedirectResponse("/admin/settlements", status_code=303)


@core.app.post("/admin/settlements/{batch_id}/pay")
async def admin_record_settlement_payment(batch_id: int, request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_guard(request)
    if redirect:
        return redirect
    form = parse_qs((await request.body()).decode("utf-8", errors="replace"))
    get = lambda key: (form.get(key, [""])[0] or "").strip()
    amount = _decimal(get("amount"))
    if amount is None:
        raise HTTPException(status_code=422, detail="Valid transfer amount is required")
    try:
        record_settlement_payment(
            db,
            batch_id,
            amount=amount,
            bank_reference=get("bank_reference"),
            bank_name=get("bank_name"),
            iban_snapshot=get("iban_snapshot"),
            recorded_by=core.ADMIN_USERNAME,
            note=get("note"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return RedirectResponse("/admin/settlements", status_code=303)


__all__ = [
    "Merchant",
    "MerchantProductLink",
    "MerchantContract",
    "MerchantContractDelivery",
    "MerchantNote",
    "VoucherFinancialSnapshot",
    "MerchantPayable",
    "SettlementBatch",
    "SettlementPayment",
    "ensure_merchant_finance_schema",
    "next_agreement_number",
    "backfill_local_partners",
    "capture_voucher_financial_snapshot",
    "ensure_payable_for_redeemed_voucher",
    "mark_order_vouchers_refunded_or_revoked",
    "build_weekly_settlement_batch",
    "approve_settlement_batch",
    "record_settlement_payment",
    "finance_dashboard_html",
]
