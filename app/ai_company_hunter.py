"""Merchant & Supplier Hunter pipeline for Pakgat AI Company."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from urllib.parse import parse_qs

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import DateTime, Float, Integer, String, Text, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app import application as core
from app import ai_company
from app.ai_company_governance import ensure_approval


class CompanyLead(core.Base):
    __tablename__ = "company_leads"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lead_type: Mapped[str] = mapped_column(String(20), index=True)
    source: Mapped[str] = mapped_column(String(120), default="manual", index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    category: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    city: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    url: Mapped[Optional[str]] = mapped_column(String(600), nullable=True)
    contact: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    opportunity_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="new", index=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)


PIPELINE = ["new", "qualified", "contact_ready", "contacted", "replied", "negotiating", "live", "rejected"]
STATUS_AR = {
    "new": "جديد", "qualified": "مؤهل", "contact_ready": "جاهز للتواصل",
    "contacted": "تم التواصل", "replied": "تم الرد", "negotiating": "قيد التفاوض",
    "live": "تم التفعيل", "rejected": "مرفوض",
}


def _admin_redirect(request: Request):
    try:
        core.require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)
    return None


def _form_value(form: dict, key: str, default: str = "") -> str:
    return str((form.get(key) or [default])[0]).strip()


def _source_link(row: CompanyLead) -> str:
    if not row.url:
        return "—"
    return f"<a class='btn btn-muted' target='_blank' rel='noopener' href='{core.esc(row.url)}'>فتح المصدر</a>"


def ensure_lead_from_opportunity(db: Session, opportunity: ai_company.CompanyOpportunity, lead_type: str = "merchant") -> CompanyLead:
    existing = db.scalar(select(CompanyLead).where(CompanyLead.opportunity_id == opportunity.id).limit(1))
    if existing:
        return existing
    row = CompanyLead(
        lead_type=lead_type if lead_type in {"merchant", "supplier"} else "merchant",
        source=opportunity.source,
        name=opportunity.title,
        opportunity_id=opportunity.id,
        score=opportunity.score,
        status="new",
        notes=opportunity.details,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    core.log_event(db, "company_lead_created", details=f"lead={row.id}; opportunity=OP-{opportunity.id:04d}; type={row.lead_type}")
    return row


@core.app.get("/admin/company/hunter", response_class=HTMLResponse)
def hunter_page(request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect
    rows = list(db.scalars(select(CompanyLead).order_by(CompanyLead.updated_at.desc()).limit(200)).all())
    counts = {stage: int(db.scalar(select(func.count(CompanyLead.id)).where(CompanyLead.status == stage)) or 0) for stage in PIPELINE}
    table_rows = "".join(
        "<tr>"
        f"<td>{'تاجر' if r.lead_type == 'merchant' else 'مورد'}</td>"
        f"<td><strong>{core.esc(r.name)}</strong><div class='muted'>{core.esc(r.notes or '')}</div></td>"
        f"<td>{core.esc(r.category or '—')}</td><td>{core.esc(r.city or '—')}</td>"
        f"<td>{core.esc(f'{r.score:.0f}' if r.score is not None else '—')}</td>"
        f"<td>{core.esc(STATUS_AR.get(r.status, r.status))}</td>"
        f"<td>{_source_link(r)}</td><td><a class='btn btn-blue' href='/admin/company/hunter/{r.id}'>فتح</a></td></tr>"
        for r in rows
    ) or "<tr><td colspan='8' class='muted'>لا توجد Leads بعد.</td></tr>"
    body = f"""
    <main class='wrap' style='padding:28px 0 48px'>
      <div style='display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap'>
        <div><h1 style='margin-bottom:4px'>باحث التجار والموردين</h1><p class='muted'>Merchant Hunter + Supplier Hunter</p></div>
        <a class='btn btn-muted' href='/admin/company'>مركز التحكم</a>
      </div>
      <div class='grid grid-mobile-1' style='grid-template-columns:repeat(4,1fr);margin:18px 0'>
        <section class='card' style='padding:16px'><div class='muted'>جديدة</div><strong style='font-size:28px'>{counts['new']}</strong></section>
        <section class='card' style='padding:16px'><div class='muted'>مؤهلة</div><strong style='font-size:28px'>{counts['qualified'] + counts['contact_ready']}</strong></section>
        <section class='card' style='padding:16px'><div class='muted'>تفاوض</div><strong style='font-size:28px'>{counts['negotiating']}</strong></section>
        <section class='card' style='padding:16px'><div class='muted'>تم التفعيل</div><strong style='font-size:28px'>{counts['live']}</strong></section>
      </div>
      <section class='card' style='padding:22px;margin-bottom:18px'>
        <h2>إضافة Lead</h2><form method='post' action='/admin/company/hunter'>
          <div class='grid grid-mobile-1' style='grid-template-columns:repeat(2,1fr)'>
            <div><label>النوع</label><select class='select' name='lead_type'><option value='merchant'>تاجر / شريك كوبون</option><option value='supplier'>مورد منتج</option></select></div>
            <div><label>الاسم</label><input class='input' name='name' required></div>
            <div><label>الفئة</label><input class='input' name='category'></div>
            <div><label>المدينة</label><input class='input' name='city' placeholder='الرياض'></div>
            <div><label>رابط المصدر</label><input class='input' name='url' dir='ltr'></div>
            <div><label>التواصل</label><input class='input' name='contact'></div>
          </div>
          <label style='margin-top:12px'>ملاحظات</label><textarea class='input' name='notes' rows='3'></textarea>
          <button class='btn btn-blue' style='margin-top:12px' type='submit'>حفظ Lead</button>
        </form>
      </section>
      <section class='card' style='padding:22px'><h2>Pipeline</h2><div class='table-wrap'><table><thead><tr><th>النوع</th><th>الاسم</th><th>الفئة</th><th>المدينة</th><th>التقييم</th><th>الحالة</th><th>المصدر</th><th></th></tr></thead><tbody>{table_rows}</tbody></table></div></section>
    </main>"""
    return HTMLResponse(core.page_shell("باحث التجار والموردين", body, admin=True))


@core.app.post("/admin/company/hunter")
async def hunter_add(request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect
    form = parse_qs((await request.body()).decode("utf-8", errors="ignore"))
    lead_type = _form_value(form, "lead_type", "merchant")
    name = _form_value(form, "name")
    if not name:
        raise HTTPException(status_code=400, detail="الاسم مطلوب")
    row = CompanyLead(
        lead_type=lead_type if lead_type in {"merchant", "supplier"} else "merchant",
        source="manual", name=name,
        category=_form_value(form, "category") or None,
        city=_form_value(form, "city") or None,
        url=_form_value(form, "url") or None,
        contact=_form_value(form, "contact") or None,
        notes=_form_value(form, "notes") or None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    core.log_event(db, "company_lead_created", details=f"lead={row.id}; type={row.lead_type}; name={name}")
    return RedirectResponse("/admin/company/hunter", status_code=303)


@core.app.get("/admin/company/hunter/{lead_id}", response_class=HTMLResponse)
def hunter_detail(lead_id: int, request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect
    row = db.get(CompanyLead, lead_id)
    if not row:
        raise HTTPException(status_code=404, detail="Lead غير موجود")
    options = "".join(f"<option value='{s}' {'selected' if s == row.status else ''}>{STATUS_AR[s]}</option>" for s in PIPELINE)
    opportunity_ref = ("OP-%04d" % row.opportunity_id) if row.opportunity_id else "—"
    body = f"""
    <main class='wrap' style='padding:28px 0 48px'><section class='card' style='max-width:900px;margin:auto;padding:24px'>
      <div style='display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap'><div><h1>{core.esc(row.name)}</h1><p class='muted'>{'تاجر / شريك' if row.lead_type == 'merchant' else 'مورد منتج'}</p></div><a class='btn btn-muted' href='/admin/company/hunter'>رجوع</a></div>
      <table><tbody><tr><th>المصدر</th><td>{core.esc(row.source)}</td></tr><tr><th>الفئة</th><td>{core.esc(row.category or '—')}</td></tr><tr><th>المدينة</th><td>{core.esc(row.city or '—')}</td></tr><tr><th>التواصل</th><td>{core.esc(row.contact or '—')}</td></tr><tr><th>الفرصة</th><td>{opportunity_ref}</td></tr></tbody></table>
      <form method='post' action='/admin/company/hunter/{row.id}/stage' style='margin-top:18px'><label>حالة الـPipeline</label><select class='select' name='stage'>{options}</select><button class='btn btn-blue' style='margin-top:10px' type='submit'>تحديث الحالة</button></form>
      <form method='post' action='/admin/company/hunter/{row.id}/prepare-contact' style='margin-top:12px'><button class='btn btn-muted' type='submit'>تجهيز موافقة للتواصل التجاري</button></form>
    </section></main>"""
    return HTMLResponse(core.page_shell("تفاصيل Lead", body, admin=True))


@core.app.post("/admin/company/hunter/{lead_id}/stage")
async def hunter_stage(lead_id: int, request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect
    row = db.get(CompanyLead, lead_id)
    if not row:
        raise HTTPException(status_code=404, detail="Lead غير موجود")
    form = parse_qs((await request.body()).decode("utf-8", errors="ignore"))
    stage = _form_value(form, "stage")
    if stage not in PIPELINE:
        raise HTTPException(status_code=400, detail="حالة غير صحيحة")
    row.status = stage
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    core.log_event(db, "company_lead_stage", details=f"lead={row.id}; stage={stage}")
    return RedirectResponse(f"/admin/company/hunter/{row.id}", status_code=303)


@core.app.post("/admin/company/hunter/{lead_id}/prepare-contact")
def hunter_prepare_contact(lead_id: int, request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect
    row = db.get(CompanyLead, lead_id)
    if not row:
        raise HTTPException(status_code=404, detail="Lead غير موجود")
    row.status = "contact_ready"
    row.updated_at = datetime.now(timezone.utc)
    ensure_approval(
        db,
        priority="P1" if (row.score or 0) >= 90 else "P2",
        approval_level="APPROVAL",
        source="Merchant/Supplier Hunter",
        action_type="merchant_contact" if row.lead_type == "merchant" else "supplier_contact",
        title=f"التواصل مع {row.name}",
        details=f"النوع: {'تاجر/شريك' if row.lead_type == 'merchant' else 'مورد'} · الفئة: {row.category or 'غير محددة'} · المصدر: {row.source}",
    )
    db.commit()
    return RedirectResponse("/admin/company/governance", status_code=303)


@core.app.post("/admin/company/opportunities/{opportunity_id}/to-lead/{lead_type}")
def opportunity_to_lead(opportunity_id: int, lead_type: str, request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect
    opportunity = db.get(ai_company.CompanyOpportunity, opportunity_id)
    if not opportunity:
        raise HTTPException(status_code=404, detail="الفرصة غير موجودة")
    lead = ensure_lead_from_opportunity(db, opportunity, lead_type=lead_type)
    return RedirectResponse(f"/admin/company/hunter/{lead.id}", status_code=303)
