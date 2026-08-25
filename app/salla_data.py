"""Salla business-data snapshots for Pakgat AI Company on Google.

Stores only operational/business fields from valid signed Salla order webhooks.
No customer PII and no raw payloads are persisted.
"""

from __future__ import annotations

import json
import hashlib
import hmac
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

from fastapi import BackgroundTasks, Depends, Request
from fastapi.routing import APIRoute
from sqlalchemy import DateTime, Float, Integer, String, UniqueConstraint, and_, delete, func, inspect, or_, select, text
from sqlalchemy.orm import Mapped, Session, mapped_column

from app import application as core


class SallaOrderSnapshot(core.Base):
    __tablename__ = "salla_order_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    reference_id: Mapped[Optional[str]] = mapped_column(String(100), index=True, nullable=True)
    last_event: Mapped[str] = mapped_column(String(80), index=True)
    order_status: Mapped[Optional[str]] = mapped_column(String(80), index=True, nullable=True)
    payment_status: Mapped[Optional[str]] = mapped_column(String(80), index=True, nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    total_amount: Mapped[float] = mapped_column(Float, default=0.0)
    paid_amount: Mapped[float] = mapped_column(Float, default=0.0)
    items_count: Mapped[int] = mapped_column(Integer, default=0)
    salla_created_at: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    customer_ref_hash: Mapped[Optional[str]] = mapped_column(String(64), index=True, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


class SallaOrderItemSnapshot(core.Base):
    __tablename__ = "salla_order_item_snapshots"
    __table_args__ = (
        UniqueConstraint("order_id", "line_key", name="uq_salla_order_item_snapshot"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String(100), index=True)
    line_key: Mapped[str] = mapped_column(String(220))
    product_id: Mapped[Optional[str]] = mapped_column(String(100), index=True, nullable=True)
    sku: Mapped[Optional[str]] = mapped_column(String(150), index=True, nullable=True)
    product_name: Mapped[str] = mapped_column(String(255))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[float] = mapped_column(Float, default=0.0)
    line_total: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


def _number(value) -> float:
    if isinstance(value, dict):
        value = value.get("amount") or value.get("value")
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _amount(data: dict, *paths: str) -> float:
    return _number(core.first_value(data, *paths))


def _text(data: dict, *paths: str) -> str:
    value = core.first_value(data, *paths)
    if isinstance(value, dict):
        value = value.get("slug") or value.get("name") or value.get("value")
    return str(value or "").strip()


def extract_salla_customer_id(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    order = data.get("order") if isinstance(data.get("order"), dict) else {}
    customer = data.get("customer") if isinstance(data.get("customer"), dict) else {}
    order_customer = order.get("customer") if isinstance(order.get("customer"), dict) else {}
    value = (
        customer.get("id")
        or data.get("customer_id")
        or order_customer.get("id")
        or order.get("customer_id")
    )
    return str(value or "").strip()


def customer_reference_hash(customer_id: str, secret: str | None = None) -> str:
    clean = str(customer_id or "").strip()
    if not clean:
        return ""
    key = str(secret or core.ADMIN_SECRET).encode("utf-8")
    return hmac.new(key, f"pakgat:retention:v1:{clean}".encode("utf-8"), hashlib.sha256).hexdigest()


def ensure_salla_retention_schema() -> None:
    inspector = inspect(core.engine)
    if "salla_order_snapshots" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("salla_order_snapshots")}
    with core.engine.begin() as connection:
        if "customer_ref_hash" not in columns:
            connection.execute(text("ALTER TABLE salla_order_snapshots ADD COLUMN customer_ref_hash VARCHAR(64)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_salla_order_snapshots_customer_ref_hash ON salla_order_snapshots (customer_ref_hash)"))


def _capture_order_payload(db: Session, payload: dict) -> None:
    event = str(payload.get("event") or "").strip()
    if not event.startswith("order."):
        return

    data = payload.get("data") or {}
    if not isinstance(data, dict):
        return

    order_id = _text(data, "id", "order.id", "reference_id", "order.reference_id")
    if not order_id:
        return
    customer_id = extract_salla_customer_id(data)
    customer_ref_hash = customer_reference_hash(customer_id) if customer_id else None

    reference_id = _text(data, "reference_id", "order.reference_id") or None
    order_status = _text(
        data,
        "status.slug",
        "status.name",
        "status",
        "order.status.slug",
        "order.status.name",
        "order.status",
    ) or None
    payment_status = _text(
        data,
        "payment.status.slug",
        "payment.status.name",
        "payment.status",
        "payment_status.slug",
        "payment_status.name",
        "payment_status",
        "order.payment.status.slug",
        "order.payment.status.name",
        "order.payment.status",
    ) or None

    total_amount = _amount(
        data,
        "amounts.total.amount",
        "amounts.total",
        "total.amount",
        "total",
        "order.amounts.total.amount",
        "order.amounts.total",
    )
    paid_amount = _amount(
        data,
        "amounts.paid.amount",
        "amounts.paid",
        "paid_amount.amount",
        "paid_amount",
        "order.amounts.paid.amount",
        "order.amounts.paid",
    )
    currency = _text(
        data,
        "amounts.total.currency",
        "total.currency",
        "currency",
        "order.currency",
    ) or None

    items = core.normalize_items(data)
    now = datetime.now(timezone.utc)
    row = db.scalar(select(SallaOrderSnapshot).where(SallaOrderSnapshot.order_id == order_id))
    if row is None:
        row = SallaOrderSnapshot(
            order_id=order_id,
            reference_id=reference_id,
            last_event=event,
            order_status=order_status,
            payment_status=payment_status,
            currency=currency,
            total_amount=total_amount,
            paid_amount=paid_amount,
            items_count=len(items),
            salla_created_at=str(payload.get("created_at") or data.get("created_at") or "")[:120] or None,
            customer_ref_hash=customer_ref_hash,
            first_seen_at=now,
            updated_at=now,
        )
        db.add(row)
    else:
        row.reference_id = reference_id or row.reference_id
        row.customer_ref_hash = customer_ref_hash or row.customer_ref_hash
        row.last_event = event
        row.order_status = order_status or row.order_status
        row.payment_status = payment_status or row.payment_status
        row.currency = currency or row.currency
        if total_amount:
            row.total_amount = total_amount
        if paid_amount:
            row.paid_amount = paid_amount
        if items:
            row.items_count = len(items)
        row.updated_at = now

    if items:
        db.execute(delete(SallaOrderItemSnapshot).where(SallaOrderItemSnapshot.order_id == order_id))
        for index, item in enumerate(items, start=1):
            product_id = str(core.item_product_id(item) or "").strip()
            sku = str(core.item_sku(item) or "").strip()
            product_name = str(core.item_product_name(item) or "منتج").strip()
            quantity = max(1, int(core.item_quantity(item) or 1))
            unit_price = _amount(
                item,
                "price.amount",
                "price",
                "unit_price.amount",
                "unit_price",
                "amounts.price.amount",
                "amounts.price",
            )
            line_total = _amount(
                item,
                "total.amount",
                "total",
                "amounts.total.amount",
                "amounts.total",
            )
            if not line_total and unit_price:
                line_total = unit_price * quantity
            line_key = str(
                core.first_value(item, "id", "item_id", "product.id")
                or product_id
                or sku
                or index
            )
            db.add(
                SallaOrderItemSnapshot(
                    order_id=order_id,
                    line_key=f"{line_key}:{index}",
                    product_id=product_id or None,
                    sku=sku or None,
                    product_name=product_name[:255],
                    quantity=quantity,
                    unit_price=unit_price,
                    line_total=line_total,
                    updated_at=now,
                )
            )

    db.commit()



def _payload_with_order_items(payload: dict, items_payload: object) -> Optional[dict]:
    """Return a copy of an order event enriched with Salla Order Items data."""
    item_data = items_payload.get("data", items_payload) if isinstance(items_payload, dict) else items_payload
    if isinstance(item_data, dict):
        items = item_data.get("data") or item_data.get("items") or []
    elif isinstance(item_data, list):
        items = item_data
    else:
        items = []
    items = [item for item in items if isinstance(item, dict)]
    if not items:
        return None

    data = payload.get("data") or {}
    if not isinstance(data, dict):
        return None
    enriched = dict(payload)
    enriched_data = dict(data)
    enriched_data["items"] = items
    enriched["data"] = enriched_data
    return enriched


def salla_metrics(db: Session) -> dict:
    paid_statuses = ["paid", "completed", "success", "successful", "تم الدفع", "مدفوع"]
    final_statuses = ["closed", "completed", "fulfilled", "مكتمل", "مغلق", "تم التنفيذ"]
    confirmed_condition = or_(
        SallaOrderSnapshot.payment_status.in_(paid_statuses),
        SallaOrderSnapshot.order_status.in_(final_statuses),
        and_(
            SallaOrderSnapshot.total_amount > 0,
            SallaOrderSnapshot.paid_amount >= SallaOrderSnapshot.total_amount,
        ),
    )

    orders_total = int(db.scalar(select(func.count(SallaOrderSnapshot.id))) or 0)
    confirmed_orders = int(
        db.scalar(select(func.count(SallaOrderSnapshot.id)).where(confirmed_condition)) or 0
    )
    revenue = float(
        db.scalar(select(func.coalesce(func.sum(SallaOrderSnapshot.total_amount), 0.0)).where(confirmed_condition))
        or 0.0
    )
    product_key = func.coalesce(
        SallaOrderItemSnapshot.product_id,
        SallaOrderItemSnapshot.sku,
        SallaOrderItemSnapshot.product_name,
    )
    products = int(
        db.scalar(select(func.count(func.distinct(product_key))))
        or 0
    )
    units = int(db.scalar(select(func.coalesce(func.sum(SallaOrderItemSnapshot.quantity), 0))) or 0)
    return {
        "orders_total": orders_total,
        "confirmed_orders": confirmed_orders,
        "pending_orders": max(0, orders_total - confirmed_orders),
        "revenue": round(revenue, 2),
        "products": products,
        "units": units,
    }


def retention_metrics(db: Session) -> dict:
    paid_statuses = ["paid", "completed", "success", "successful", "تم الدفع", "مدفوع"]
    final_statuses = ["closed", "completed", "fulfilled", "مكتمل", "مغلق", "تم التنفيذ"]
    confirmed = or_(
        SallaOrderSnapshot.payment_status.in_(paid_statuses),
        SallaOrderSnapshot.order_status.in_(final_statuses),
        and_(SallaOrderSnapshot.total_amount > 0, SallaOrderSnapshot.paid_amount >= SallaOrderSnapshot.total_amount),
    )
    total_confirmed = int(db.scalar(select(func.count(SallaOrderSnapshot.id)).where(confirmed)) or 0)
    identified = int(db.scalar(select(func.count(SallaOrderSnapshot.id)).where(confirmed, SallaOrderSnapshot.customer_ref_hash.is_not(None))) or 0)
    grouped = select(
        SallaOrderSnapshot.customer_ref_hash.label("customer_ref"),
        func.count(SallaOrderSnapshot.id).label("order_count"),
    ).where(confirmed, SallaOrderSnapshot.customer_ref_hash.is_not(None)).group_by(SallaOrderSnapshot.customer_ref_hash).subquery()
    unique_customers = int(db.scalar(select(func.count()).select_from(grouped)) or 0)
    returning_customers = int(db.scalar(select(func.count()).select_from(grouped).where(grouped.c.order_count > 1)) or 0)
    repeat_orders = int(db.scalar(select(func.coalesce(func.sum(grouped.c.order_count - 1), 0)).where(grouped.c.order_count > 1)) or 0)
    return {
        "confirmed_orders": total_confirmed,
        "identified_confirmed_orders": identified,
        "unique_customers": unique_customers,
        "returning_customers": returning_customers,
        "repeat_orders": repeat_orders,
        "repeat_customer_rate": round((returning_customers / unique_customers * 100) if unique_customers else 0.0, 1),
        "coverage_percent": round((identified / total_confirmed * 100) if total_confirmed else 0.0, 1),
    }


def backfill_retention_customer_refs(db: Session) -> dict:
    rows = list(db.scalars(select(SallaOrderSnapshot).where(SallaOrderSnapshot.customer_ref_hash.is_(None)).order_by(SallaOrderSnapshot.id)).all())
    updated = failed = missing = 0
    for row in rows:
        result, error = core.fetch_salla_json_endpoint(db, "/orders/" + quote(row.order_id, safe=""))
        if error:
            failed += 1
            continue
        customer_id = extract_salla_customer_id(result)
        if not customer_id:
            missing += 1
            continue
        row.customer_ref_hash = customer_reference_hash(customer_id)
        updated += 1
    db.commit()
    return {"examined": len(rows), "updated": updated, "missing_customer_id": missing, "failed": failed}


def latest_orders(db: Session, limit: int = 20):
    return list(
        db.scalars(
            select(SallaOrderSnapshot)
            .order_by(SallaOrderSnapshot.updated_at.desc())
            .limit(limit)
        ).all()
    )


def latest_items(db: Session, limit: int = 30):
    return list(
        db.scalars(
            select(SallaOrderItemSnapshot)
            .order_by(SallaOrderItemSnapshot.updated_at.desc())
            .limit(limit)
        ).all()
    )


def _find_route(path: str, method: str):
    for route in core.app.routes:
        if isinstance(route, APIRoute) and route.path == path and method in route.methods:
            return route
    return None


_webhook_route = _find_route("/webhooks/salla", "POST")
if _webhook_route is not None:
    _original_salla_webhook = _webhook_route.dependant.call

    async def _salla_webhook_with_data(
        request: Request,
        background_tasks: BackgroundTasks,
        db: Session = Depends(core.get_db),
    ):
        raw_body = await request.body()
        signature = request.headers.get("x-salla-signature", "")
        if core.verify_salla_signature(raw_body, signature):
            try:
                payload = json.loads(raw_body.decode("utf-8"))
                _capture_order_payload(db, payload)

                event = str(payload.get("event") or "").strip()
                data = payload.get("data") or {}
                order_id = _text(
                    data if isinstance(data, dict) else {},
                    "id",
                    "order.id",
                    "reference_id",
                    "order.reference_id",
                )
                merchant_id = core.payload_merchant_id(payload)
                if event.startswith("order.") and order_id and merchant_id:
                    items_payload, items_error = core.fetch_salla_json_endpoint(
                        db,
                        "/orders/items?order_id=" + quote(order_id, safe=""),
                        merchant_id,
                    )
                    if items_error:
                        core.log_event(
                            db,
                            "salla_order_items_auto_sync_failed",
                            details=f"order={order_id}; error={items_error[:220]}",
                        )
                    else:
                        enriched = _payload_with_order_items(payload, items_payload)
                        if enriched is not None:
                            _capture_order_payload(db, enriched)
            except Exception as exc:
                db.rollback()
                core.log_event(
                    db,
                    "salla_datahub_capture_failed",
                    details=f"{type(exc).__name__}: {str(exc)[:300]}",
                )
        return await _original_salla_webhook(request, background_tasks, db)

    _webhook_route.endpoint = _salla_webhook_with_data
    _webhook_route.dependant.call = _salla_webhook_with_data
