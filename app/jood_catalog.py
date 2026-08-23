from __future__ import annotations

import json
import re
from typing import NamedTuple
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

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
    payload, error = core.fetch_salla_json_endpoint(
        db,
        f"/products?per_page={max(1, min(limit, 50))}&page=1&format=light",
        str(credential.merchant_id),
    )
    items = [] if error else parse_salla_catalog(payload)
    if items:
        return items

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
            str(credential.merchant_id),
        )
        if not detail_error:
            items.extend(parse_salla_catalog({"data": [detail.get("data", {})]}))
    return items


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
    if action == "send_selected_option" and selected.isdigit() and previous_options:
        index = int(selected) - 1
        if 0 <= index < len(previous_options):
            option_id = str(previous_options[index].get("id") or "")
            chosen = [item for item in items if item.id == option_id][:1]
    elif action in {"send_catalog_options", "send_product_link", "pitch_product"}:
        matches = [item for item in items if _matches(item, selected)] if selected else items
        if not matches:
            matches = items
        chosen = matches[:1] if action in {"send_product_link", "pitch_product"} else matches[:3]

    options = [{"id": item.id, "name": item.name, "url": item.url} for item in chosen]
    if chosen:
        # The backend owns product URLs. Remove model-rendered copies first so
        # the canonical raw link appears exactly once, at the message end.
        for item in chosen:
            reply = re.sub(re.escape(item.url), "", reply, flags=re.IGNORECASE)
        reply = " ".join(reply.split()).strip()
        details = []
        for item in chosen:
            price = f" — {item.price:g} ر.س" if item.price else ""
            details.append(f"{item.name}{price}\n{item.url}")
        reply = (reply.rstrip() + "\n\n" + "\n\n".join(details)).strip()
    elif action in {"send_catalog_options", "send_product_link", "pitch_product"}:
        reply = (reply.rstrip() + f"\n{PAKGAT_HOME_URL}").strip()
    approved = {PAKGAT_HOME_URL, *(item.url for item in items)}
    return CatalogActionResult(reply, options, approved)
