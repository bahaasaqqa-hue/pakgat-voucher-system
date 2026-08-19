"""Store Operations & Merchandising watch for data currently connected to Google."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import DateTime, Integer, String, Text, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app import application as core
from app.gce_entry import LocalPartnerProduct
from app.salla_data import SallaOrderItemSnapshot


class StoreOpsIssue(core.Base):
    __tablename__ = "store_ops_issues"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    severity: Mapped[str] = mapped_column(String(10), default="P2", index=True)
    issue_type: Mapped[str] = mapped_column(String(80), index=True)
    item_ref: Mapped[Optional[str]] = mapped_column(String(180), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)


def _admin_redirect(request: Request):
    try:
        core.require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)
    return None


def _ensure_issue(db: Session, severity: str, issue_type: str, item_ref: str, title: str, details: str) -> None:
    row = db.scalar(select(StoreOpsIssue).where(
        StoreOpsIssue.status == "open",
        StoreOpsIssue.issue_type == issue_type,
        StoreOpsIssue.item_ref == item_ref,
    ))
    if row:
        row.severity = severity
        row.title = title
        row.details = details
        row.updated_at = datetime.now(timezone.utc)
        return
    db.add(StoreOpsIssue(severity=severity, issue_type=issue_type, item_ref=item_ref or None, title=title, details=details or None))


def run_store_ops_scan(db: Session) -> dict:
    """Scan only data actually connected to this runtime; never invent full-catalog coverage."""
    scanned = 0
    found = 0

    partners = list(db.scalars(select(LocalPartnerProduct)).all())
    for row in partners:
        scanned += 1
        ref = row.product_id or row.sku or f"local-{row.id}"
        if not (row.product_name or "").strip():
            _ensure_issue(db, "P1", "missing_product_name", ref, "اسم المنتج غير محفوظ في سجل الشريك", "المنتج مربوط محليًا لكن product_name فارغ؛ يجب الاعتماد على قراءة سلة عند توفرها أو استكمال الاسم في السجل المحلي.")
            found += 1
        if not (row.partner_name or "").strip():
            _ensure_issue(db, "P0", "missing_partner", ref, "اسم الشريك مفقود", "لا يمكن تشغيل توجيه القسيمة بأمان بدون اسم شريك.")
            found += 1

    order_items = list(db.scalars(select(SallaOrderItemSnapshot).order_by(SallaOrderItemSnapshot.updated_at.desc()).limit(500)).all())
    for item in order_items:
        scanned += 1
        ref = item.product_id or item.sku or item.line_key
        if not (item.product_name or "").strip():
            _ensure_issue(db, "P1", "missing_order_product_name", ref, "اسم منتج مفقود في بيانات الطلب", "وصل المنتج عبر Data Hub بدون اسم واضح.")
            found += 1
        if float(item.unit_price or 0) <= 0:
            _ensure_issue(db, "P2", "missing_price_signal", ref, "سعر المنتج غير واضح في بيانات الطلب", "القيمة الملتقطة من Webhook تساوي صفر؛ لا تستخدمها في إعادة التسعير أو تحليل الهامش.")
            found += 1

    db.commit()
    open_count = int(db.scalar(select(func.count(StoreOpsIssue.id)).where(StoreOpsIssue.status == "open")) or 0)
    core.log_event(db, "store_ops_scan", details=f"scanned={scanned}; detected={found}; open={open_count}")
    return {"scanned": scanned, "detected": found, "open": open_count}


@core.app.get("/admin/company/store-ops", response_class=HTMLResponse)
def store_ops_page(request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect
    result = run_store_ops_scan(db)
    issues = list(db.scalars(select(StoreOpsIssue).order_by(StoreOpsIssue.status, StoreOpsIssue.severity, StoreOpsIssue.updated_at.desc()).limit(200)).all())
    rows = "".join(
        "<tr>"
        f"<td>{core.esc(i.severity)}</td><td>{core.esc(i.issue_type)}</td><td>{core.esc(i.item_ref or '—')}</td>"
        f"<td><strong>{core.esc(i.title)}</strong><div class='muted'>{core.esc(i.details or '')}</div></td>"
        f"<td>{core.esc(i.status)}</td>"
        f"<td>{(f'<form method=\"post\" action=\"/admin/company/store-ops/{i.id}/resolve\"><button class=\"btn btn-muted\" type=\"submit\">تم الحل</button></form>' if i.status == 'open' else '—')}</td></tr>"
        for i in issues
    ) or "<tr><td colspan='6' class='muted'>لا توجد مشاكل مرصودة ضمن البيانات المتصلة حاليًا.</td></tr>"
    body = f"""
    <main class='wrap' style='padding:28px 0 48px'>
      <div style='display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap'><div><h1 style='margin-bottom:4px'>تشغيل المتجر وجودة العرض</h1><p class='muted'>Store Operations & Merchandising</p></div><a class='btn btn-muted' href='/admin/company'>مركز التحكم</a></div>
      <div class='alert' style='background:#fff7ed;color:#9a3412;border:1px solid #fed7aa;margin-top:18px'><strong>النطاق الحالي:</strong> يفحص البيانات التي وصلت فعلًا إلى Google فقط. فحص AR/EN وRibbon والسعر قبل/بعد والصور والتصنيفات والـMetadata على كامل متجر سلة يحتاج Merchant API/قراءة الكتالوج.</div>
      <div class='grid grid-mobile-1' style='grid-template-columns:repeat(3,1fr);margin:18px 0'><section class='card' style='padding:18px'><div class='muted'>عناصر مفحوصة</div><strong style='font-size:28px'>{result['scanned']}</strong></section><section class='card' style='padding:18px'><div class='muted'>اكتشافات هذه الجولة</div><strong style='font-size:28px'>{result['detected']}</strong></section><section class='card' style='padding:18px'><div class='muted'>مشاكل مفتوحة</div><strong style='font-size:28px'>{result['open']}</strong></section></div>
      <section class='card' style='padding:22px'><div class='table-wrap'><table><thead><tr><th>الأولوية</th><th>النوع</th><th>المرجع</th><th>المشكلة</th><th>الحالة</th><th></th></tr></thead><tbody>{rows}</tbody></table></div></section>
    </main>"""
    return HTMLResponse(core.page_shell("تشغيل المتجر وجودة العرض", body, admin=True))


@core.app.post("/admin/company/store-ops/{issue_id}/resolve")
def resolve_store_issue(issue_id: int, request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect
    row = db.get(StoreOpsIssue, issue_id)
    if not row:
        raise HTTPException(status_code=404, detail="المشكلة غير موجودة")
    row.status = "resolved"
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    core.log_event(db, "store_ops_issue_resolved", details=f"issue={row.id}; type={row.issue_type}")
    return RedirectResponse("/admin/company/store-ops", status_code=303)
