"""Admin editing for Pakgat merchant legal/contact/bank profile.

This remains separate from Sadq signing. Sadq identifiers are displayed only when
real API integration later stores them; this module never fabricates a signature.
"""

from urllib.parse import parse_qs

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import application as core
from app import merchant_finance as finance
from app import merchant_contracts as contracts


def _guard(request: Request):
    try:
        core.require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)
    return None


def _latest_contract(db: Session, merchant_id: int):
    return db.scalar(
        select(finance.MerchantContract)
        .where(finance.MerchantContract.merchant_id == merchant_id)
        .order_by(finance.MerchantContract.created_at.desc())
        .limit(1)
    )


@core.app.get("/admin/merchants/{merchant_id}/edit", response_class=HTMLResponse)
def admin_edit_merchant_profile(
    merchant_id: int,
    request: Request,
    db: Session = Depends(core.get_db),
):
    redirect = _guard(request)
    if redirect:
        return redirect
    finance.ensure_merchant_finance_schema()
    merchant = db.get(finance.Merchant, merchant_id)
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
    contract = _latest_contract(db, merchant_id)
    contract_status = contract.status if contract else "غير مربوط بعد"
    sadq_document_id = contract.sadq_document_id if contract else None
    body = f"""
    <main class='wrap' style='padding:28px 0 48px'>
      <div style='display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap'>
        <div><h1 style='margin-bottom:5px'>تعديل بيانات التاجر</h1><div class='muted'>{core.esc(merchant.display_name)} · <span dir='ltr'>{core.esc(merchant.code)}</span></div></div>
        <a class='btn btn-muted' href='/admin/merchants/{merchant.id}'>العودة لملف التاجر</a>
      </div>
      <form method='post' action='/admin/merchants/{merchant.id}/edit'>
        <section class='card' style='padding:20px;margin-top:18px'>
          <h2>البيانات الأساسية والقانونية</h2>
          <div class='grid grid-mobile-1' style='grid-template-columns:1fr 1fr'>
            <div><label>اسم التاجر في Pakgat *</label><input class='input' name='display_name' value='{core.esc(merchant.display_name)}' required maxlength='255'></div>
            <div><label>الاسم القانوني</label><input class='input' name='legal_name' value='{core.esc(merchant.legal_name or "")}' maxlength='255'></div>
            <div><label>السجل التجاري</label><input class='input' name='commercial_registration' dir='ltr' value='{core.esc(merchant.commercial_registration or "")}' maxlength='80'></div>
            <div><label>الرقم الضريبي</label><input class='input' name='tax_number' dir='ltr' value='{core.esc(merchant.tax_number or "")}' maxlength='80'></div>
            <div><label>حالة التاجر</label><select class='select' name='status'><option value='active' {'selected' if merchant.status == 'active' else ''}>نشط</option><option value='suspended' {'selected' if merchant.status == 'suspended' else ''}>موقوف</option><option value='pending' {'selected' if merchant.status == 'pending' else ''}>قيد المراجعة</option></select></div>
            <div style='display:flex;align-items:end;padding-bottom:10px'><label style='display:flex;gap:8px;align-items:center'><input type='checkbox' name='vat_registered' value='1' {'checked' if merchant.vat_registered else ''}> مسجل في ضريبة القيمة المضافة</label></div>
          </div>
        </section>
        <section class='card' style='padding:20px;margin-top:18px'>
          <h2>التواصل والتحويل البنكي</h2>
          <div class='grid grid-mobile-1' style='grid-template-columns:1fr 1fr'>
            <div><label>جوال التواصل</label><input class='input' name='contact_phone' dir='ltr' value='{core.esc(merchant.contact_phone or "")}' maxlength='40'></div>
            <div><label>البريد الإلكتروني</label><input class='input' type='email' name='contact_email' dir='ltr' value='{core.esc(merchant.contact_email or "")}' maxlength='255'></div>
            <div><label>اسم البنك</label><input class='input' name='bank_name' value='{core.esc(merchant.bank_name or "")}' maxlength='120'></div>
            <div><label>IBAN</label><input class='input' name='iban' dir='ltr' value='{core.esc(merchant.iban or "")}' maxlength='80'></div>
          </div>
          <p class='muted' style='margin-bottom:0'>عند تسجيل حوالة تسوية، يحفظ النظام نسخة IBAN داخل سجل الحوالة حتى لا تتغير التسويات القديمة إذا تم تعديل الحساب لاحقًا.</p>
        </section>
        <section class='card' style='padding:20px;margin-top:18px'>
          <h2>العقد والتوقيع</h2>
          <p><strong>الحالة:</strong> {core.esc(contract_status)}</p>
          <p><strong>Sadq Document ID:</strong> <span dir='ltr'>{core.esc(sadq_document_id or '—')}</span></p>
          <p class='muted'>واجهة صادق غير مفعلة هنا حتى يتم تزويد Pakgat بالـAPI الحقيقي. لن يتم إنشاء أو ادعاء أي توقيع يدويًا.</p>
        </section>
        <button class='btn btn-blue' type='submit' style='margin-top:18px'>حفظ بيانات التاجر</button>
      </form>
    </main>
    """
    return HTMLResponse(core.page_shell("تعديل التاجر", body, admin=True))


@core.app.post("/admin/merchants/{merchant_id}/edit")
async def admin_save_merchant_profile(
    merchant_id: int,
    request: Request,
    db: Session = Depends(core.get_db),
):
    redirect = _guard(request)
    if redirect:
        return redirect
    finance.ensure_merchant_finance_schema()
    merchant = db.get(finance.Merchant, merchant_id)
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")

    form = parse_qs((await request.body()).decode("utf-8", errors="replace"))
    get = lambda key: (form.get(key, [""])[0] or "").strip()
    display_name = get("display_name")
    if not display_name:
        raise HTTPException(status_code=422, detail="Merchant display name is required")
    status_value = get("status") or "active"
    if status_value not in {"active", "suspended", "pending"}:
        raise HTTPException(status_code=422, detail="Invalid merchant status")

    merchant.display_name = display_name[:255]
    merchant.legal_name = get("legal_name")[:255] or None
    merchant.commercial_registration = get("commercial_registration")[:80] or None
    merchant.vat_registered = 1 if get("vat_registered") == "1" else 0
    merchant.tax_number = get("tax_number")[:80] or None
    merchant.contact_phone = get("contact_phone")[:40] or None
    merchant.contact_email = get("contact_email")[:255] or None
    merchant.bank_name = get("bank_name")[:120] or None
    merchant.iban = get("iban")[:80] or None
    merchant.status = status_value
    merchant.updated_at = core.now_utc()
    db.add(
        finance.MerchantNote(
            merchant_id=merchant.id,
            note_type="operations",
            text="تم تحديث بيانات ملف التاجر والبنك من لوحة الإدارة.",
            created_by=core.ADMIN_USERNAME,
            created_at=core.now_utc(),
        )
    )
    db.commit()
    core.log_event(
        db,
        "merchant_profile_updated",
        details=f"merchant_id={merchant.id}; status={merchant.status}",
    )
    return RedirectResponse(f"/admin/merchants/{merchant.id}", status_code=303)


# Add editing and contract visibility to the existing merchant detail page without
# changing its finance calculations or tables.
_original_detail = finance.admin_merchant_detail


def _merchant_detail_with_edit(
    merchant_id: int,
    request: Request,
    db: Session = Depends(core.get_db),
):
    response = _original_detail(merchant_id, request, db)
    if not isinstance(response, HTMLResponse) or response.status_code >= 300:
        return response
    html = response.body.decode("utf-8", errors="replace")
    marker = "<div class='muted' dir='ltr'>"
    button = f"<a class='btn btn-blue' href='/admin/merchants/{merchant_id}/edit' style='margin-top:10px'>تعديل بيانات التاجر</a>"
    if button not in html and marker in html:
        position = html.find("</div>", html.find(marker))
        if position != -1:
            position += len("</div>")
            html = html[:position] + button + html[position:]

    if "id='merchant-contract-summary'" not in html:
        summary = contracts.merchant_contract_summary_html(db, merchant_id)
        products_marker = "<section class='card' style='padding:18px;margin-bottom:18px'><h2>المنتجات</h2>"
        position = html.find(products_marker)
        if position == -1:
            position = html.rfind("</main>")
        if position != -1:
            html = html[:position] + summary + html[position:]

    return HTMLResponse(html, status_code=response.status_code, headers=dict(response.headers))


finance.admin_merchant_detail = _merchant_detail_with_edit
for _route in core.app.routes:
    if getattr(_route, "path", None) == "/admin/merchants/{merchant_id}" and "GET" in (getattr(_route, "methods", set()) or set()):
        _route.endpoint = _merchant_detail_with_edit
        if getattr(_route, "dependant", None) is not None:
            _route.dependant.call = _merchant_detail_with_edit
        break


__all__ = ["admin_edit_merchant_profile", "admin_save_merchant_profile"]