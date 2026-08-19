"""Google VM extension: local Salla partner registry.

This keeps Pakgat voucher routing independent from Salla Merchant API OAuth.
Registered local products are treated as voucher products even when their Salla
SKU does not start with PKG-QR. Existing Salla OAuth behavior remains available
as a fallback whenever a local record is not found.
"""

from datetime import datetime, timezone
from typing import Optional
from urllib.parse import parse_qs, unquote, urlsplit

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import DateTime, Integer, String, or_, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app import application as core


class LocalPartnerProduct(core.Base):
    __tablename__ = "local_partner_products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[Optional[str]] = mapped_column(String(100), unique=True, index=True, nullable=True)
    sku: Mapped[Optional[str]] = mapped_column(String(150), unique=True, index=True, nullable=True)
    product_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    partner_name: Mapped[str] = mapped_column(String(255))
    merchant_phone: Mapped[str] = mapped_column(String(120))
    partner_hours: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    partner_contact: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    partner_address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    partner_map_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


def _normalize_product_id(value: str) -> str:
    value = str(value or "").strip()
    if len(value) > 1 and value[:1].lower() == "p" and value[1:].isdigit():
        return value[1:]
    return value


def _normalize_sku(value: str) -> str:
    return str(value or "").strip().upper()


def _lookup_local_partner(
    db: Session,
    product_id: str = "",
    sku: str = "",
) -> Optional[LocalPartnerProduct]:
    product_id = _normalize_product_id(product_id)
    sku = _normalize_sku(sku)
    conditions = []
    if product_id:
        conditions.append(LocalPartnerProduct.product_id == product_id)
    if sku:
        conditions.append(LocalPartnerProduct.sku == sku)
    if not conditions:
        return None
    return db.scalar(
        select(LocalPartnerProduct)
        .where(or_(*conditions))
        .order_by(LocalPartnerProduct.updated_at.desc())
        .limit(1)
    )


def _metadata_payload(row: LocalPartnerProduct) -> dict:
    fields = [
        {"label": "اسم الشريك", "value": row.partner_name},
        {"label": "رقم جوال استقبال القسائم", "value": row.merchant_phone},
    ]
    optional_fields = (
        ("ساعات العمل", row.partner_hours),
        ("رقم التواصل", row.partner_contact),
        ("العنوان", row.partner_address),
        ("رابط خرائط Google", row.partner_map_url),
    )
    for label, value in optional_fields:
        if value:
            fields.append({"label": label, "value": value})
    return {
        "id": row.product_id or "",
        "sku": row.sku or "",
        "name": row.product_name or "",
        "metadata": fields,
        "source": "pakgat_local_partner_registry",
    }


# --- Local-first fallbacks for Salla product metadata -----------------------

_original_fetch_salla_product_metadata = core.fetch_salla_product_metadata
_original_fetch_salla_json_endpoint = core.fetch_salla_json_endpoint
_original_item_sku = core.item_sku


def _fetch_salla_product_metadata_local_first(
    db: Session,
    product_id: str,
    merchant_id: str = "",
):
    row = _lookup_local_partner(db, product_id=product_id)
    if row:
        return _metadata_payload(row), None
    return _original_fetch_salla_product_metadata(db, product_id, merchant_id)


def _fetch_salla_json_endpoint_local_first(
    db: Session,
    path: str,
    merchant_id: str = "",
):
    clean_path = str(path or "")
    split = urlsplit(clean_path)

    if split.path.startswith("/metadata/values/product/"):
        product_id = unquote(split.path.rsplit("/", 1)[-1])
        row = _lookup_local_partner(db, product_id=product_id)
        if row:
            return {"data": _metadata_payload(row)}, None

    if split.path.startswith("/products/"):
        product_id = unquote(split.path.rsplit("/", 1)[-1])
        row = _lookup_local_partner(db, product_id=product_id)
        if row:
            return {
                "data": {
                    "id": row.product_id or "",
                    "sku": row.sku or "",
                    "name": row.product_name or "",
                    "metadata": _metadata_payload(row)["metadata"],
                    "source": "pakgat_local_partner_registry",
                }
            }, None

    if split.path == "/products" and split.query:
        query = parse_qs(split.query)
        sku = (query.get("sku") or query.get("keyword") or [""])[0]
        row = _lookup_local_partner(db, sku=sku)
        if row:
            return {
                "data": [
                    {
                        "id": row.product_id or "",
                        "sku": row.sku or "",
                        "name": row.product_name or "",
                        "source": "pakgat_local_partner_registry",
                    }
                ]
            }, None

    return _original_fetch_salla_json_endpoint(db, path, merchant_id)


def _item_sku_with_local_registry(item: dict) -> str:
    """Make a locally registered product eligible for voucher processing.

    We do not alter Salla. The synthetic PKG-QR value exists only inside this
    process so the existing webhook safety filter keeps ignoring all other
    products.
    """
    raw_sku = _original_item_sku(item)
    if _normalize_sku(raw_sku).startswith(core.VOUCHER_SKU_PREFIX):
        return raw_sku

    product_id = core.item_product_id(item)
    with core.SessionLocal() as db:
        row = _lookup_local_partner(db, product_id=product_id, sku=raw_sku)
    if row:
        return f"{core.VOUCHER_SKU_PREFIX}-LOCAL-{row.id}"
    return raw_sku


core.fetch_salla_product_metadata = _fetch_salla_product_metadata_local_first
core.fetch_salla_json_endpoint = _fetch_salla_json_endpoint_local_first
core.item_sku = _item_sku_with_local_registry


# --- Admin UI ---------------------------------------------------------------

_original_page_shell = core.page_shell


def _page_shell_with_local_partners(title: str, body: str, admin: bool = False) -> str:
    html = _original_page_shell(title, body, admin=admin)
    if admin and 'href="/admin/local-partners"' not in html:
        marker = '<a class="btn btn-muted" href="/admin/integrations">تكامل سلة</a>'
        extra = marker + '<a class="btn btn-muted" href="/admin/local-partners">بيانات الشركاء</a>'
        html = html.replace(marker, extra)
    return html


core.page_shell = _page_shell_with_local_partners


def _admin_redirect_if_needed(request: Request):
    try:
        core.require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)
    return None


@core.app.get("/admin/local-partners", response_class=HTMLResponse)
def admin_local_partners(
    request: Request,
    saved: int = 0,
    error: str = "",
    db: Session = Depends(core.get_db),
):
    redirect = _admin_redirect_if_needed(request)
    if redirect:
        return redirect

    rows = list(
        db.scalars(
            select(LocalPartnerProduct).order_by(
                LocalPartnerProduct.updated_at.desc(),
                LocalPartnerProduct.id.desc(),
            )
        ).all()
    )

    status_box = ""
    if saved:
        status_box = "<div class='alert alert-ok'><strong>تم حفظ بيانات الشريك ✅</strong></div>"
    elif error:
        status_box = f"<div class='alert alert-error'><strong>{core.esc(error)}</strong></div>"

    table_rows = ""
    for row in rows:
        table_rows += (
            "<tr>"
            f"<td dir='ltr'>{core.esc(row.product_id or '—')}</td>"
            f"<td dir='ltr'>{core.esc(row.sku or '—')}</td>"
            f"<td>{core.esc(row.product_name or '—')}</td>"
            f"<td>{core.esc(row.partner_name)}</td>"
            f"<td dir='ltr'>{core.esc(core.masked_phone(row.merchant_phone))}</td>"
            "<td>"
            f"<form method='post' action='/admin/local-partners/{row.id}/delete' "
            "onsubmit=\"return confirm('حذف ربط هذا المنتج؟');\">"
            "<button class='btn btn-danger' type='submit'>حذف</button></form>"
            "</td>"
            "</tr>"
        )
    if not table_rows:
        table_rows = "<tr><td colspan='6' class='muted'>لا توجد منتجات مربوطة محلياً حتى الآن.</td></tr>"

    body = f"""
    <main class='wrap' style='padding:28px 0 48px'>
      <section class='card' style='padding:24px;margin-bottom:18px'>
        <h1>بيانات الشركاء المحلية</h1>
        <p class='muted'>
          هذا السجل هو المصدر الأول لبيانات الشريك. لا يحتاج Access Token من سلة،
          ولا يغيّر أي إعداد داخل متجر سلة. المنتج المسجل هنا يصبح مؤهلاً لنظام
          القسائم حتى لو كان SKU الحالي لا يبدأ بـ PKG-QR.
        </p>
        {status_box}
        <form method='post' action='/admin/local-partners/save'>
          <div class='grid grid-mobile-1' style='grid-template-columns:1fr 1fr'>
            <div>
              <label>Product ID في سلة</label>
              <input class='input' name='product_id' dir='ltr' placeholder='مثال: 1840815203'>
            </div>
            <div>
              <label>SKU الحالي</label>
              <input class='input' name='sku' dir='ltr' placeholder='مثال: TAM-PKG-001'>
            </div>
            <div>
              <label>اسم المنتج</label>
              <input class='input' name='product_name' placeholder='اسم العرض في سلة'>
            </div>
            <div>
              <label>اسم الشريك *</label>
              <input class='input' name='partner_name' required placeholder='اسم التاجر أو الشريك'>
            </div>
            <div>
              <label>جوال استقبال القسائم *</label>
              <input class='input' name='merchant_phone' dir='ltr' required placeholder='05xxxxxxxx'>
            </div>
            <div>
              <label>ساعات العمل</label>
              <input class='input' name='partner_hours' placeholder='مثال: يومياً 4م - 11م'>
            </div>
            <div>
              <label>رقم التواصل</label>
              <input class='input' name='partner_contact' dir='ltr' placeholder='05xxxxxxxx'>
            </div>
            <div>
              <label>العنوان</label>
              <input class='input' name='partner_address' placeholder='العنوان أو الفرع'>
            </div>
          </div>
          <label style='margin-top:12px'>رابط خرائط Google</label>
          <input class='input' name='partner_map_url' dir='ltr' placeholder='https://maps.google.com/...'>
          <button class='btn btn-blue' style='margin-top:14px' type='submit'>حفظ بيانات الشريك</button>
        </form>
      </section>

      <section class='card' style='padding:24px'>
        <h2>المنتجات المربوطة</h2>
        <div class='table-wrap'>
          <table>
            <thead>
              <tr>
                <th>Product ID</th><th>SKU</th><th>المنتج</th>
                <th>الشريك</th><th>جوال الشريك</th><th></th>
              </tr>
            </thead>
            <tbody>{table_rows}</tbody>
          </table>
        </div>
      </section>
    </main>
    """
    return HTMLResponse(core.page_shell("بيانات الشركاء", body, admin=True))


@core.app.post("/admin/local-partners/save", response_class=HTMLResponse)
async def admin_local_partner_save(
    request: Request,
    db: Session = Depends(core.get_db),
):
    redirect = _admin_redirect_if_needed(request)
    if redirect:
        return redirect

    form = parse_qs((await request.body()).decode("utf-8", errors="replace"))
    value = lambda name: (form.get(name, [""])[0] or "").strip()

    product_id = _normalize_product_id(value("product_id"))
    sku = _normalize_sku(value("sku"))
    product_name = value("product_name")
    partner_name = value("partner_name")
    merchant_phone = value("merchant_phone")
    partner_hours = value("partner_hours")
    partner_contact = value("partner_contact")
    partner_address = value("partner_address")
    partner_map_url = value("partner_map_url")

    if not product_id and not sku:
        return RedirectResponse(
            "/admin/local-partners?error=أدخل Product ID أو SKU على الأقل",
            status_code=303,
        )
    if not partner_name:
        return RedirectResponse(
            "/admin/local-partners?error=اسم الشريك مطلوب",
            status_code=303,
        )
    if not core.merchant_phone_candidates(merchant_phone):
        return RedirectResponse(
            "/admin/local-partners?error=رقم جوال استقبال القسائم غير صحيح",
            status_code=303,
        )

    row = _lookup_local_partner(db, product_id=product_id, sku=sku)
    if not row:
        row = LocalPartnerProduct(
            product_id=product_id or None,
            sku=sku or None,
            product_name=product_name or None,
            partner_name=partner_name,
            merchant_phone=merchant_phone,
            partner_hours=partner_hours or None,
            partner_contact=partner_contact or None,
            partner_address=partner_address or None,
            partner_map_url=partner_map_url or None,
            created_at=core.now_utc(),
            updated_at=core.now_utc(),
        )
        db.add(row)
    else:
        row.product_id = product_id or row.product_id
        row.sku = sku or row.sku
        row.product_name = product_name or row.product_name
        row.partner_name = partner_name
        row.merchant_phone = merchant_phone
        row.partner_hours = partner_hours or None
        row.partner_contact = partner_contact or None
        row.partner_address = partner_address or None
        row.partner_map_url = partner_map_url or None
        row.updated_at = core.now_utc()

    try:
        db.commit()
    except Exception:
        db.rollback()
        return RedirectResponse(
            "/admin/local-partners?error=تعذر الحفظ. تأكد أن Product ID و SKU غير مكررين",
            status_code=303,
        )

    core.log_event(
        db,
        "local_partner_saved",
        details=f"product_id={product_id or 'none'}; sku={sku or 'none'}",
    )
    return RedirectResponse("/admin/local-partners?saved=1", status_code=303)


@core.app.post("/admin/local-partners/{row_id}/delete")
def admin_local_partner_delete(
    row_id: int,
    request: Request,
    db: Session = Depends(core.get_db),
):
    redirect = _admin_redirect_if_needed(request)
    if redirect:
        return redirect

    row = db.get(LocalPartnerProduct, row_id)
    if row:
        product_id = row.product_id or ""
        sku = row.sku or ""
        db.delete(row)
        db.commit()
        core.log_event(
            db,
            "local_partner_deleted",
            details=f"product_id={product_id or 'none'}; sku={sku or 'none'}",
        )
    return RedirectResponse("/admin/local-partners", status_code=303)


app = core.app

__all__ = ["app", "LocalPartnerProduct"]
