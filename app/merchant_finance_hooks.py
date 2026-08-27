"""Narrow integration hooks for merchant finance.

The existing voucher/WhatsLoop/Salla implementation stays the source flow. This
module wraps only the agreed policy points: no merchant purchase notification,
refund/cancel lifecycle, financial snapshots/payables, dashboard summary and
opt-in internal voucher-creation API protection.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone

from fastapi import BackgroundTasks, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import application as core
from app import merchant_finance as finance


def _ensure_tables_on_session(db: Session) -> None:
    core.Base.metadata.create_all(bind=db.get_bind(), tables=finance.FINANCE_TABLES)


# ---------------------------------------------------------------------------
# 1) Merchant notification policy: no purchase-time "sale" message.
# Historical rows/functions are kept for audit and old data compatibility.
# ---------------------------------------------------------------------------

_original_reserve_merchant_notification = core.reserve_merchant_notification


def _reserve_merchant_notification_disabled(
    db: Session,
    order_id: str,
    product_id: str,
    merchant_phone: str,
):
    core.log_event(
        db,
        "merchant_sale_notification_disabled",
        details=(
            f"order={order_id}; product_id={product_id}; "
            f"phone={core.masked_phone(core.normalize_saudi_phone(merchant_phone))}"
        ),
    )
    return None


core.reserve_merchant_notification = _reserve_merchant_notification_disabled


# ---------------------------------------------------------------------------
# 2) Redemption creates merchant payable before the existing redemption message
# is sent. Any finance error is audited but never blocks the customer/service
# redemption that already succeeded.
# ---------------------------------------------------------------------------

_original_notify_merchant_after_redemption = core.notify_merchant_after_redemption


def _notify_merchant_after_redemption_with_finance(voucher_id: int) -> None:
    try:
        with core.SessionLocal() as db:
            _ensure_tables_on_session(db)
            voucher = db.get(core.Voucher, voucher_id)
            if voucher and voucher.status == "redeemed":
                payable = finance.ensure_payable_for_redeemed_voucher(db, voucher)
                core.log_event(
                    db,
                    "merchant_payable_recorded" if payable else "merchant_payable_skipped",
                    voucher_id,
                    (
                        f"status={payable.status}; merchant_id={payable.merchant_id or 'unknown'}"
                        if payable
                        else "voucher is not eligible"
                    ),
                )
    except Exception as exc:
        try:
            with core.SessionLocal() as db:
                core.log_event(
                    db,
                    "merchant_payable_failed",
                    voucher_id,
                    f"finance_error={type(exc).__name__}",
                )
        except Exception:
            pass
    _original_notify_merchant_after_redemption(voucher_id)


core.notify_merchant_after_redemption = _notify_merchant_after_redemption_with_finance


# ---------------------------------------------------------------------------
# 3) Extend Salla webhook handling without changing signature verification or
# payment issuance behavior for existing supported order events.
# ---------------------------------------------------------------------------

_original_salla_webhook = core.salla_webhook


def _base_order_id(data: dict) -> str:
    return str(
        core.first_value(
            data,
            "id",
            "order.id",
            "reference_id",
            "order.reference_id",
        )
        or ""
    ).strip()


def _parse_dt(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except Exception:
            return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def _sync_product_event(db: Session, event: str, data: dict) -> dict:
    _ensure_tables_on_session(db)
    product_id = str(core.first_value(data, "id", "product.id", "product_id") or "").strip()
    sku = str(core.first_value(data, "sku", "product.sku") or "").strip().upper()
    link = finance.get_product_link(db, product_id, sku)
    if not link:
        return {"updated": False, "reason": "product_not_linked", "product_id": product_id}
    name = str(core.first_value(data, "name", "product.name") or "").strip()
    status_value = str(
        core.first_value(
            data,
            "status.slug",
            "status.name",
            "status",
            "product.status.slug",
            "product.status.name",
            "product.status",
        )
        or ""
    ).strip().lower()
    if event in {"product.deleted", "product.delete"}:
        status_value = "deleted"
    if name:
        link.product_name_snapshot = name
    if status_value:
        link.product_status = status_value
    ends_at = core.first_value(
        data,
        "offer_ends_at",
        "ends_at",
        "end_date",
        "sale_end",
        "sale_end_date",
        "discount.ends_at",
        "product.ends_at",
        "product.sale_end",
    )
    parsed_end = _parse_dt(ends_at)
    if parsed_end:
        link.offer_ends_at = parsed_end
    link.last_salla_sync_at = core.now_utc()
    link.updated_at = core.now_utc()
    db.commit()
    core.log_event(
        db,
        "merchant_product_salla_synced",
        details=f"event={event}; product_id={product_id or 'unknown'}; link_id={link.id}",
    )
    return {"updated": True, "product_id": product_id, "link_id": link.id}


async def _salla_webhook_with_finance(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(core.get_db),
):
    raw_body = await request.body()
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return await _original_salla_webhook(request, background_tasks, db)

    event = str(payload.get("event") or "").strip()
    data = payload.get("data") or {}

    custom_events = {
        "order.refunded",
        "order.cancelled",
        "product.updated",
        "product.status.updated",
        "product.price.updated",
        "product.deleted",
    }
    if event in custom_events:
        if not core.verify_salla_signature(
            raw_body,
            request.headers.get("x-salla-signature", ""),
        ):
            core.log_event(db, "salla_webhook_rejected", details=f"Invalid signature for {event}")
            return JSONResponse(
                status_code=401,
                content={"ok": False, "detail": "Invalid Salla signature."},
            )

        if event in {"order.refunded", "order.cancelled"}:
            order_id = _base_order_id(data)
            if not order_id:
                return JSONResponse(
                    status_code=422,
                    content={"ok": False, "detail": "Order ID is missing."},
                )
            product_ids = {
                core.item_product_id(item)
                for item in core.normalize_items(data)
                if core.item_product_id(item)
            }
            target_status = "refunded" if event == "order.refunded" else "revoked"
            result = finance.mark_order_vouchers_refunded_or_revoked(
                db,
                order_id,
                target_status,
                product_ids or None,
            )
            core.log_event(
                db,
                "salla_order_refund_cancel_processed",
                details=(
                    f"order={order_id}; event={event}; changed={result['changed']}; "
                    f"redeemed_review={result['redeemed_review']}"
                ),
            )
            return {
                "ok": True,
                "event": event,
                "order_id": order_id,
                "voucher_status": target_status,
                **result,
            }

        sync_result = _sync_product_event(db, event, data)
        return {"ok": True, "event": event, **sync_result}

    result = await _original_salla_webhook(request, background_tasks, db)

    # Capture sale amount + product commission snapshot only after the existing
    # paid-order voucher logic succeeds. Failure here never changes issuance.
    if isinstance(result, dict) and not result.get("ignored") and event in {"order.updated", "order.payment.updated"}:
        try:
            _ensure_tables_on_session(db)
            order_id = _base_order_id(data)
            for item in core.normalize_items(data):
                product_id = core.item_product_id(item)
                if not product_id:
                    continue
                vouchers = list(
                    db.scalars(
                        select(core.Voucher).where(
                            core.Voucher.product_id == product_id,
                            core.Voucher.order_id.like(order_id + ":" + product_id + ":%"),
                        )
                    ).all()
                )
                for voucher in vouchers:
                    finance.capture_voucher_financial_snapshot(db, voucher, item)
        except Exception as exc:
            core.log_event(
                db,
                "voucher_financial_snapshot_failed",
                details=f"event={event}; error={type(exc).__name__}",
            )
    return result


core.salla_webhook = _salla_webhook_with_finance
for _route in core.app.routes:
    if getattr(_route, "path", None) == "/webhooks/salla" and "POST" in (getattr(_route, "methods", set()) or set()):
        _route.endpoint = _salla_webhook_with_finance
        if getattr(_route, "dependant", None) is not None:
            _route.dependant.call = _salla_webhook_with_finance
        break


# ---------------------------------------------------------------------------
# 4) Voucher status presentation for refund/revoke without changing URLs.
# ---------------------------------------------------------------------------

_original_status_badge = core.status_badge


def _status_badge_extended(value: str) -> str:
    if value == "refunded":
        return "<span class='badge badge-redeemed'>مسترجعة</span>"
    if value == "revoked":
        return "<span class='badge badge-expired'>ملغاة</span>"
    return _original_status_badge(value)


core.status_badge = _status_badge_extended

_original_build_verification_page = core.build_verification_page


def _build_verification_page_extended(voucher: core.Voucher, error_message=None) -> str:
    if voucher.status in {"refunded", "revoked"}:
        title = "تم استرجاع القسيمة" if voucher.status == "refunded" else "تم إلغاء القسيمة"
        body = f"""<main class='wrap' style='padding:28px 0 44px'><section class='card' style='max-width:620px;margin:auto;padding:26px;text-align:center'><div style='font-size:36px;font-weight:900;color:#2446ba'>بكجات</div><div class='alert alert-error' style='margin-top:20px'><h2>{core.esc(title)}</h2><p>هذه القسيمة غير قابلة للاستخدام أو الاستبدال.</p></div><h3>{core.esc(voucher.product_name)}</h3><p class='muted'>{core.esc(voucher.code)}</p><div class='muted' style='margin-top:20px'>Pakgat Voucher System</div></section></main>"""
        return core.page_shell(title, body)
    return _original_build_verification_page(voucher, error_message)


core.build_verification_page = _build_verification_page_extended


# ---------------------------------------------------------------------------
# 5) Main admin dashboard finance summary, injected after the existing voucher
# dashboard to preserve the old layout and search behavior.
# ---------------------------------------------------------------------------

_original_admin_dashboard = core.admin_dashboard


def _admin_dashboard_with_finance(
    request: Request,
    q: str = "",
    voucher_status: str = "",
    page: int = 1,
    db: Session = Depends(core.get_db),
):
    response = _original_admin_dashboard(request, q, voucher_status, page, db)
    if not isinstance(response, HTMLResponse) or response.status_code >= 300:
        return response
    try:
        _ensure_tables_on_session(db)
        summary = finance.finance_dashboard_html(db)
    except Exception:
        summary = "<section class='card' style='padding:18px;margin-top:18px'><strong>مستحقات التجار</strong><div class='muted'>تعذر تحميل الملخص المالي؛ لوحة القسائم الأساسية ما زالت تعمل.</div></section>"
    html = response.body.decode("utf-8", errors="replace")
    if "مستحقات التجار" not in html:
        html = html.replace("</main>", summary + "</main>", 1)
    return HTMLResponse(html, status_code=response.status_code, headers=dict(response.headers))


core.admin_dashboard = _admin_dashboard_with_finance
for _route in core.app.routes:
    if getattr(_route, "path", None) == "/admin" and "GET" in (getattr(_route, "methods", set()) or set()):
        _route.endpoint = _admin_dashboard_with_finance
        if getattr(_route, "dependant", None) is not None:
            _route.dependant.call = _admin_dashboard_with_finance
        break


# ---------------------------------------------------------------------------
# 6) Opt-in protection for manual/internal voucher creation API.
# Existing API behavior is preserved until VOUCHER_API_SECRET is explicitly set.
# Salla webhook is unaffected.
# ---------------------------------------------------------------------------

VOUCHER_API_SECRET = core.env("VOUCHER_API_SECRET")
core.VOUCHER_API_SECRET = VOUCHER_API_SECRET


@core.app.middleware("http")
async def _protect_voucher_creation_api(request: Request, call_next):
    if (
        request.method.upper() == "POST"
        and request.url.path == "/api/vouchers"
        and VOUCHER_API_SECRET
    ):
        supplied = request.headers.get("x-pakgat-voucher-secret", "")
        if not supplied or not hmac.compare_digest(supplied, VOUCHER_API_SECRET):
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized voucher creation request."},
            )
    return await call_next(request)


__all__ = ["VOUCHER_API_SECRET"]
