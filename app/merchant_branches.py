"""Merchant branch management for Pakgat admin.

Branches are additive and linked to the stable Merchant id. Product-to-branch
assignment can be layered on later without changing voucher or WhatsApp routes.
"""

from urllib.parse import parse_qs, urlsplit

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import DateTime, Integer, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app import application as core
from app import merchant_finance as finance


class MerchantBranch(core.Base):
    __tablename__ = "merchant_branches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    merchant_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(255))
    contact_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    map_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=core.now_utc)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=core.now_utc)


def ensure_branch_schema(bind=None) -> None:
    core.Base.metadata.create_all(bind=bind or core.engine, tables=[MerchantBranch.__table__])


def _guard(request: Request):
    try:
        core.require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)
    return None


def _safe_map_url(value: str) -> str | None:
    value = str(value or "").strip()
    if not value:
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"}:
        return None
    host = (parsed.hostname or "").lower()
    if host == "google.com" or host.endswith(".google.com") or host == "maps.app.goo.gl":
        return value
    return None


@core.app.get("/admin/merchants/{merchant_id}/branches", response_class=HTMLResponse)
def admin_merchant_branches(
    merchant_id: int,
    request: Request,
    db: Session = Depends(core.get_db),
):
    redirect = _guard(request)
    if redirect:
        return redirect
    ensure_branch_schema(db.get_bind())
    merchant = db.get(finance.Merchant, merchant_id)
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
    branches = list(
        db.scalars(
            select(MerchantBranch)
            .where(MerchantBranch.merchant_id == merchant_id)
            .order_by(MerchantBranch.status.asc(), MerchantBranch.name.asc())
        ).all()
    )
    rows = "".join(
        "<tr>"
        f"<td>{core.esc(branch.name)}</td>"
        f"<td dir='ltr'>{core.esc(branch.contact_phone or '—')}</td>"
        f"<td>{core.esc(branch.address or '—')}</td>"
        f"<td>{core.esc(branch.status)}</td>"
        f"<td>{core.fmt_dt(branch.updated_at)}</td>"
        "</tr>"
        for branch in branches
    ) or "<tr><td colspan='5'>لا توجد فروع مسجلة بعد.</td></tr>"
    body = f"""
    <main class='wrap' style='padding:28px 0 48px'>
      <div style='display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap'>
        <div><h1 style='margin-bottom:5px'>فروع {core.esc(merchant.display_name)}</h1><p class='muted'>أضف الفروع التي يمكن ربط العروض بها لاحقًا.</p></div>
        <a class='btn btn-muted' href='/admin/merchants/{merchant.id}'>العودة لملف التاجر</a>
      </div>
      <section class='card' style='padding:20px;margin-top:18px'>
        <h2>إضافة فرع</h2>
        <form method='post' action='/admin/merchants/{merchant.id}/branches/save'>
          <div class='grid grid-mobile-1' style='grid-template-columns:1fr 1fr'>
            <div><label>اسم الفرع *</label><input class='input' name='name' required maxlength='255' placeholder='مثال: فرع العليا'></div>
            <div><label>جوال الفرع</label><input class='input' name='contact_phone' dir='ltr' maxlength='40'></div>
            <div><label>العنوان</label><input class='input' name='address' maxlength='500'></div>
            <div><label>رابط خرائط Google</label><input class='input' name='map_url' dir='ltr' maxlength='1000'></div>
            <div><label>الحالة</label><select class='select' name='status'><option value='active'>نشط</option><option value='inactive'>غير نشط</option></select></div>
          </div>
          <button class='btn btn-blue' type='submit' style='margin-top:14px'>حفظ الفرع</button>
        </form>
      </section>
      <section class='card' style='padding:20px;margin-top:18px'>
        <h2>الفروع الحالية</h2>
        <div class='table-wrap'><table><thead><tr><th>الفرع</th><th>الجوال</th><th>العنوان</th><th>الحالة</th><th>آخر تحديث</th></tr></thead><tbody>{rows}</tbody></table></div>
      </section>
    </main>
    """
    return HTMLResponse(core.page_shell("فروع التاجر", body, admin=True))


@core.app.post("/admin/merchants/{merchant_id}/branches/save")
async def admin_save_merchant_branch(
    merchant_id: int,
    request: Request,
    db: Session = Depends(core.get_db),
):
    redirect = _guard(request)
    if redirect:
        return redirect
    ensure_branch_schema(db.get_bind())
    merchant = db.get(finance.Merchant, merchant_id)
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
    form = parse_qs((await request.body()).decode("utf-8", errors="replace"))
    get = lambda key: (form.get(key, [""])[0] or "").strip()
    name = get("name")
    if not name:
        raise HTTPException(status_code=422, detail="Branch name is required")
    status_value = get("status") or "active"
    if status_value not in {"active", "inactive"}:
        raise HTTPException(status_code=422, detail="Invalid branch status")
    branch = MerchantBranch(
        merchant_id=merchant_id,
        name=name[:255],
        contact_phone=get("contact_phone")[:40] or None,
        address=get("address")[:500] or None,
        map_url=_safe_map_url(get("map_url")),
        status=status_value,
        created_at=core.now_utc(),
        updated_at=core.now_utc(),
    )
    db.add(branch)
    db.add(
        finance.MerchantNote(
            merchant_id=merchant_id,
            note_type="operations",
            text=f"تم إضافة الفرع: {name[:255]}",
            created_by=core.ADMIN_USERNAME,
            created_at=core.now_utc(),
        )
    )
    db.commit()
    return RedirectResponse(f"/admin/merchants/{merchant_id}/branches", status_code=303)


_original_detail = finance.admin_merchant_detail


def _detail_with_branches(
    merchant_id: int,
    request: Request,
    db: Session = Depends(core.get_db),
):
    response = _original_detail(merchant_id, request, db)
    if not isinstance(response, HTMLResponse) or response.status_code >= 300:
        return response
    html = response.body.decode("utf-8", errors="replace")
    action = f"<a class='btn btn-muted' href='/admin/merchants/{merchant_id}/branches' style='margin-top:10px;margin-right:8px'>الفروع</a>"
    if action not in html:
        marker = f"href='/admin/merchants/{merchant_id}/edit'"
        index = html.find(marker)
        if index >= 0:
            end = html.find("</a>", index)
            if end >= 0:
                end += 4
                html = html[:end] + action + html[end:]
        else:
            html = html.replace("<h1>", action + "<h1>", 1)
    return HTMLResponse(html, status_code=response.status_code, headers=dict(response.headers))


finance.admin_merchant_detail = _detail_with_branches
for _route in core.app.routes:
    if getattr(_route, "path", None) == "/admin/merchants/{merchant_id}" and "GET" in (getattr(_route, "methods", set()) or set()):
        _route.endpoint = _detail_with_branches
        if getattr(_route, "dependant", None) is not None:
            _route.dependant.call = _detail_with_branches
        break


__all__ = ["MerchantBranch", "ensure_branch_schema"]
