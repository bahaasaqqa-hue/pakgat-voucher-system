"""Voucher lifecycle sweep and Pakgat financial status summary.

Expired means the active voucher reached its validity date unused. This module
marks that state automatically and shows operational amounts. It does not make
or change VAT/accounting tax-point decisions.
"""

from decimal import Decimal

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import application as core
from app import merchant_finance as finance


def expire_due_vouchers(db: Session) -> int:
    """Idempotently expire active vouchers whose validity has ended."""
    due = list(
        db.scalars(
            select(core.Voucher).where(
                core.Voucher.status == "active",
                core.Voucher.expires_at < core.now_utc(),
            )
        ).all()
    )
    if not due:
        return 0
    for voucher in due:
        voucher.status = "expired"
        db.add(
            core.AuditLog(
                voucher_id=voucher.id,
                action="voucher_expired",
                details="Voucher expired automatically by lifecycle sweep",
                created_at=voucher.expires_at or core.now_utc(),
            )
        )
    db.commit()
    return len(due)


def _status_count(db: Session, status: str) -> int:
    return int(
        db.scalar(
            select(func.count(core.Voucher.id)).where(core.Voucher.status == status)
        )
        or 0
    )


def _status_value(db: Session, status: str) -> Decimal:
    value = db.scalar(
        select(func.coalesce(func.sum(finance.VoucherFinancialSnapshot.gross_amount), 0))
        .select_from(core.Voucher)
        .join(
            finance.VoucherFinancialSnapshot,
            finance.VoucherFinancialSnapshot.voucher_id == core.Voucher.id,
        )
        .where(core.Voucher.status == status)
    )
    return Decimal(value or 0).quantize(Decimal("0.01"))


def voucher_lifecycle_finance_html(db: Session) -> str:
    statuses = {
        "active": ("Active / أموال معلقة", "القسيمة ما زالت قابلة للاستخدام"),
        "redeemed": ("Redeemed", "تم تقديم الخدمة"),
        "expired": ("Expired بدون استخدام", "لا مستحق للتاجر؛ لصالح Pakgat تشغيليًا حسب السياسة"),
        "refunded": ("Refunded", "تم استرجاع العملية للعميل"),
        "revoked": ("Cancelled / Revoked", "القسيمة ملغاة وغير قابلة للاستخدام"),
    }
    cards = []
    for status, (label, description) in statuses.items():
        count = _status_count(db, status)
        value = _status_value(db, status)
        cards.append(
            "<div class='card' style='padding:17px'>"
            f"<div style='font-weight:900'>{core.esc(label)}</div>"
            f"<div style='font-size:24px;font-weight:900;margin:4px 0'>{count}</div>"
            f"<div><strong>{value:,.2f} ر.س</strong> <span class='muted'>قيمة مسجلة</span></div>"
            f"<div class='muted' style='font-size:12px;margin-top:6px'>{core.esc(description)}</div>"
            "</div>"
        )
    return (
        "<section style='margin:20px 0'>"
        "<h2 style='margin-bottom:10px'>حالة القسائم والقيمة</h2>"
        "<div class='grid grid-mobile-1' style='grid-template-columns:repeat(5,1fr)'>"
        + "".join(cards)
        + "</div>"
        "<p class='muted' style='font-size:12px'>القيمة المعروضة تعتمد على السعر الذي تم التقاطه من طلب سلة؛ القسائم التاريخية التي لا تملك Snapshot تبقى محسوبة في العدد دون اختلاق قيمة مالية.</p>"
        "</section>"
    )


_original_admin_dashboard = core.admin_dashboard


def _admin_dashboard_with_lifecycle(
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
        finance.ensure_merchant_finance_schema()
        expire_due_vouchers(db)
        block = voucher_lifecycle_finance_html(db)
    except Exception:
        block = (
            "<section class='card' style='padding:16px;margin-top:18px'>"
            "<strong>حالة القسائم والقيمة</strong>"
            "<div class='muted'>تعذر تحميل الملخص المالي؛ لوحة القسائم الأساسية ما زالت تعمل.</div>"
            "</section>"
        )
    html = response.body.decode("utf-8", errors="replace")
    if "حالة القسائم والقيمة" not in html:
        marker = "<h2 style='margin:0'>مستحقات التجار</h2>"
        section_start = html.rfind("<section", 0, html.find(marker)) if marker in html else -1
        if section_start >= 0:
            html = html[:section_start] + block + html[section_start:]
        else:
            html = html.replace("</main>", block + "</main>", 1)
    return HTMLResponse(html, status_code=response.status_code, headers=dict(response.headers))


core.admin_dashboard = _admin_dashboard_with_lifecycle
for _route in core.app.routes:
    if getattr(_route, "path", None) == "/admin" and "GET" in (getattr(_route, "methods", set()) or set()):
        _route.endpoint = _admin_dashboard_with_lifecycle
        if getattr(_route, "dependant", None) is not None:
            _route.dependant.call = _admin_dashboard_with_lifecycle
        break


# Load branch management as a sibling additive extension. Keeping this import
# here avoids further changes to the long application entry file.
from app import merchant_branches as _merchant_branches  # noqa: E402,F401


def run_once() -> int:
    with core.SessionLocal() as db:
        changed = expire_due_vouchers(db)
    print(f"voucher_lifecycle_expired={changed}")
    return changed


if __name__ == "__main__":
    run_once()


__all__ = ["expire_due_vouchers", "voucher_lifecycle_finance_html", "run_once"]
