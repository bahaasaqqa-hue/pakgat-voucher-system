"""Salla scope compatibility: use Products Read for product metadata.

Salla review approved only the Products Read permission for Pakgat and confirmed
that product metadata can be read through that same scope. Production code must
therefore avoid the standalone Metadata API permission/endpoints.

This module is imported immediately after ``app.gce_entry`` so it wraps the
existing local-first Google VM fallbacks without changing voucher behavior.
"""

from urllib.parse import quote, unquote, urlsplit

from sqlalchemy.orm import Session

from app import application as core


_original_fetch_salla_json_endpoint = core.fetch_salla_json_endpoint


def _product_details_path(product_id: str) -> str:
    return f"/products/{quote(str(product_id or '').strip(), safe='')}"


def fetch_salla_json_products_read_only(
    db: Session,
    path: str,
    merchant_id: str = "",
):
    """Route legacy product-metadata reads through Product Details.

    Existing voucher/admin code still contains calls to
    ``/metadata/values/product/{id}``. Translate those calls to
    ``/products/{id}``, which is covered by the approved Products Read scope.
    Any other standalone Metadata API call is blocked instead of accidentally
    requiring the rejected Metadata permission.
    """
    split = urlsplit(str(path or ""))

    if split.path.startswith("/metadata/values/product/"):
        product_id = unquote(split.path.rsplit("/", 1)[-1]).strip()
        if not product_id:
            return None, "product_id is missing"
        return _original_fetch_salla_json_endpoint(
            db,
            _product_details_path(product_id),
            merchant_id,
        )

    if split.path.startswith("/metadata/"):
        return None, (
            "Standalone Salla Metadata API is disabled; "
            "Pakgat uses the approved Products Read scope"
        )

    return _original_fetch_salla_json_endpoint(db, path, merchant_id)


def fetch_salla_product_metadata_products_read_only(
    db: Session,
    product_id: str,
    merchant_id: str = "",
):
    """Read partner/custom product fields from Product Details only."""
    product_id = str(product_id or "").strip()
    if not product_id:
        return None, "product_id is missing"

    payload, error = _original_fetch_salla_json_endpoint(
        db,
        _product_details_path(product_id),
        merchant_id,
    )
    if payload is None:
        return None, error

    if isinstance(payload, dict) and "data" in payload:
        return payload.get("data"), None
    return payload, None


# Replace the global functions used by webhook processing, redemption, and
# admin diagnostics. No Salla write operation is added here.
core.fetch_salla_json_endpoint = fetch_salla_json_products_read_only
core.fetch_salla_product_metadata = fetch_salla_product_metadata_products_read_only
