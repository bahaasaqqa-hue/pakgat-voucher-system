"""Non-destructive customer voucher page enhancement.

Adds only merchant operational details. Voucher URL, QR URL, redemption form and
WhatsApp URLs remain owned by the existing voucher implementation.
"""

from urllib.parse import urlsplit

from app import application as core
from app import gce_entry as gce


def _safe_map_url(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ""
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"https", "http"}:
        return ""
    allowed = (
        host == "google.com"
        or host.endswith(".google.com")
        or host == "maps.google.com"
        or host == "maps.app.goo.gl"
        or host.endswith(".googleusercontent.com")
    )
    return value if allowed else ""


def partner_details_html(
    *,
    partner_name: str = "",
    hours: str = "",
    contact: str = "",
    address: str = "",
    map_url: str = "",
) -> str:
    rows = []
    if partner_name:
        rows.append(("مقدم الخدمة", partner_name))
    if hours:
        rows.append(("ساعات العمل", hours))
    if contact:
        rows.append(("التواصل", contact))
    if address:
        rows.append(("العنوان", address))
    safe_map = _safe_map_url(map_url)
    if not rows and not safe_map:
        return ""
    table_rows = "".join(
        f"<tr><th>{core.esc(label)}</th><td>{core.esc(value)}</td></tr>"
        for label, value in rows
    )
    map_action = (
        f"<a class='btn btn-muted' href='{core.esc(safe_map)}' target='_blank' rel='noopener noreferrer' style='margin-top:12px'>فتح الموقع على الخريطة</a>"
        if safe_map
        else ""
    )
    return (
        "<div style='background:#f8fbff;border:1px solid #dbe7f7;padding:16px;border-radius:14px;margin-top:14px;line-height:1.9'>"
        "<strong>تفاصيل مقدم الخدمة</strong>"
        f"<div class='table-wrap' style='margin-top:10px'><table>{table_rows}</table></div>"
        f"{map_action}</div>"
    )


def _lookup_partner_details(product_id: str):
    try:
        with core.SessionLocal() as db:
            row = gce._lookup_local_partner(db, product_id=str(product_id or ""))
            if not row:
                return None
            return {
                "partner_name": row.partner_name or "",
                "hours": row.partner_hours or "",
                "contact": row.partner_contact or row.merchant_phone or "",
                "address": row.partner_address or "",
                "map_url": row.partner_map_url or "",
            }
    except Exception:
        return None


_original_build_verification_page = core.build_verification_page


def _build_verification_page_with_partner_details(voucher: core.Voucher, error_message=None) -> str:
    html = _original_build_verification_page(voucher, error_message)
    details = _lookup_partner_details(voucher.product_id)
    if not details:
        return html
    card = partner_details_html(**details)
    if not card or "تفاصيل مقدم الخدمة" in html:
        return html
    marker = "<strong>شروط استخدام العميل</strong>"
    marker_index = html.find(marker)
    if marker_index == -1:
        return html
    container_start = html.rfind("<div", 0, marker_index)
    if container_start == -1:
        return html
    return html[:container_start] + card + html[container_start:]


core.build_verification_page = _build_verification_page_with_partner_details

__all__ = ["partner_details_html"]
