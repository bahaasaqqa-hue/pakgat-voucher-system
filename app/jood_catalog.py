from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import NamedTuple
from urllib.parse import quote

from sqlalchemy import DateTime, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app import application as core
from app.jood_policy import PAKGAT_HOME_URL


class CatalogItem(NamedTuple):
    id: str
    name: str
    url: str
    price: float


class CatalogActionResult(NamedTuple):
    reply: str
    presented_options: list[dict[str, str]]
    approved_urls: set[str]


class JoodCatalogCache(core.Base):
    __tablename__ = "jood_catalog_cache"

    merchant_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    products_json: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


def _ensure_cache_table(db: Session) -> None:
    JoodCatalogCache.__table__.create(bind=db.get_bind(), checkfirst=True)


def _save_catalog_cache(db: Session, merchant_id: str, items: list[CatalogItem]) -> None:
    if not items or not isinstance(db, Session):
        return
    _ensure_cache_table(db)
    row = db.get(JoodCatalogCache, merchant_id)
    payload = json.dumps(
        [item._asdict() for item in items],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    if row is None:
        row = JoodCatalogCache(merchant_id=merchant_id, products_json=payload)
        db.add(row)
    else:
        row.products_json = payload
        row.updated_at = datetime.now(timezone.utc)
    db.commit()


def _load_catalog_cache(db: Session, merchant_id: str) -> list[CatalogItem]:
    if not isinstance(db, Session):
        return []
    _ensure_cache_table(db)
    row = db.get(JoodCatalogCache, merchant_id)
    if row is None:
        return []
    try:
        payload = json.loads(row.products_json)
    except (TypeError, json.JSONDecodeError):
        return []
    return parse_salla_catalog({"data": payload})


def catalog_from_presented_options(options: object) -> list[CatalogItem]:
    items: list[CatalogItem] = []
    for option in options if isinstance(options, list) else []:
        if not isinstance(option, dict):
            continue
        product_id = str(option.get("id") or "").strip()
        name = str(option.get("name") or "").strip()
        url = str(option.get("url") or "").strip()
        if product_id and name and url.startswith("https://"):
            items.append(CatalogItem(product_id, name, url, _amount(option.get("price"))))
    return items


def strict_product_message(product: CatalogItem) -> str:
    return (
        f"أهلاً بك! أبشر، تفضل رابط العرض المباشر لـ {product.name}:\n"
        f"{product.url}\n"
        "استخدم كود الخصم: VIP"
    )


def is_sales_consent(text: str) -> bool:
    value = " ".join(str(text or "").strip().lower().split())
    if not value or any(marker in value for marker in ("لا ترسل", "لاترسل", "ما أبغى", "ما ابغى")):
        return False
    exact = {"ارسل", "أرسل", "موافق", "تمام", "تفضل", "اوكي", "أوكي", "نعم", "ايه", "إيه"}
    return value in exact or any(
        marker in value for marker in ("ارسل لي", "أرسل لي", "ايه ارسل", "إيه أرسل", "أبشر ارسل")
    )


def enforce_sales_action(decision: dict, customer_text: str, state: dict | None) -> dict:
    result = dict(decision or {})
    if not is_sales_consent(customer_text):
        return result
    saved = dict(state or {})
    selected = str(saved.get("selected_product_id") or "").strip()
    if not selected:
        options = saved.get("presented_options")
        if isinstance(options, list) and options and isinstance(options[0], dict):
            selected = str(options[0].get("id") or "").strip()
    result["action"] = "send_product_link"
    result["selected_option"] = selected
    result["last_commitment_fulfilled"] = True
    result["next_stage"] = "product_link_shared"
    result["last_commitment"] = ""
    return result


def _amount(value) -> float:
    if isinstance(value, dict):
        value = value.get("amount") or value.get("value")
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def parse_salla_catalog(payload: object) -> list[CatalogItem]:
    data = payload.get("data", []) if isinstance(payload, dict) else []
    if isinstance(data, dict):
        data = data.get("data") or data.get("items") or []
    rows: list[CatalogItem] = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        product_id = str(item.get("id") or "").strip()
        name = str(item.get("name") or item.get("title") or "").strip()
        urls = item.get("urls") if isinstance(item.get("urls"), dict) else {}
        url = str(urls.get("customer") or item.get("url") or "").strip()
        price = _amount(item.get("sale_price") or item.get("price") or item.get("regular_price"))
        if product_id and name and url.startswith("https://"):
            rows.append(CatalogItem(product_id, name[:255], url, price))
    return rows


def load_live_catalog(db: Session, limit: int = 30) -> list[CatalogItem]:
    credential = core.latest_salla_credential(db)
    if not credential:
        return []
    merchant_id = str(credential.merchant_id)
    payload, error = core.fetch_salla_json_endpoint(
        db,
        f"/products?per_page={max(1, min(limit, 50))}&page=1&format=light",
        merchant_id,
    )
    if error:
        payload, error = core.fetch_salla_json_endpoint(
            db,
            f"/products?per_page={max(1, min(limit, 50))}&page=1&format=light",
            merchant_id,
        )
    items = [] if error else parse_salla_catalog(payload)
    if items:
        _save_catalog_cache(db, merchant_id, items)
        return items
    if error:
        cached = _load_catalog_cache(db, merchant_id)
        if cached:
            return cached

    # Some Salla stores do not return inactive/custom products in the list
    # endpoint. Reuse product IDs already observed in real paid/order events and
    # resolve each product through the official detail endpoint.
    from app.salla_data import SallaOrderItemSnapshot

    product_ids = list(
        db.execute(
            select(SallaOrderItemSnapshot.product_id)
            .where(SallaOrderItemSnapshot.product_id.is_not(None))
            .distinct()
            .limit(min(limit, 12))
        ).scalars().all()
    )
    for product_id in product_ids:
        detail, detail_error = core.fetch_salla_json_endpoint(
            db,
            f"/products/{quote(str(product_id), safe='')}",
            merchant_id,
        )
        if not detail_error:
            items.extend(parse_salla_catalog({"data": [detail.get("data", {})]}))
    if items:
        _save_catalog_cache(db, merchant_id, items)
        return items
    return _load_catalog_cache(db, merchant_id)


def choose_featured_product(items: list[CatalogItem], instruction: str = "") -> CatalogItem | None:
    query = " ".join(str(instruction or "").lower().split())
    if query:
        for item in items:
            if any(word in item.name.lower() for word in query.split() if len(word) > 2):
                return item
    return items[0] if items else None


def catalog_context(items: list[CatalogItem]) -> str:
    compact = [
        {"id": item.id, "name": item.name, "url": item.url, "price_sar": item.price}
        for item in items[:12]
    ]
    return "Live approved Pakgat products from Salla:\n" + json.dumps(compact, ensure_ascii=False)


def _matches(item: CatalogItem, selected: str) -> bool:
    value = selected.lower().strip()
    if value == item.id.lower() or value == item.name.lower():
        return True
    aliases = {
        "هدايا": ("هدي", "gift"),
        "gifts": ("هدي", "gift"),
        "سيارات": ("سيار", "غسيل", "car"),
        "مطاعم": ("مطعم", "وجبة", "food"),
        "عناية": ("عناية", "سبا", "جمال", "care", "spa"),
    }
    markers = aliases.get(value, (value,))
    return any(marker and marker in item.name.lower() for marker in markers)


def execute_catalog_action(
    decision: dict,
    items: list[CatalogItem],
    *,
    previous_options: list[dict[str, str]] | None = None,
) -> CatalogActionResult:
    action = str(decision.get("action") or "answer").strip()
    selected = str(decision.get("selected_option") or "").strip()
    reply = str(decision.get("reply") or "").strip()
    chosen: list[CatalogItem] = []
    if action in {"send_selected_option", "send_catalog_options", "send_product_link", "pitch_product"}:
        # Product selection is intentionally deterministic: the approved first
        # live catalog product is the only product a sales message may expose.
        chosen = items[:1]

    options = [
        {"id": item.id, "name": item.name, "url": item.url, "price": str(item.price)}
        for item in chosen
    ]
    if chosen:
        reply = strict_product_message(chosen[0])
    elif action in {"send_catalog_options", "send_product_link", "pitch_product"}:
        reply = (reply.rstrip() + f"\n{PAKGAT_HOME_URL}").strip()
    approved = {PAKGAT_HOME_URL, *(item.url for item in items)}
    return CatalogActionResult(reply, options, approved)
