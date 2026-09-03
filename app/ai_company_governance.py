"""Governance, approval queue and CEO briefs for Pakgat AI Company."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import DateTime, Integer, String, Text, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app import ai_company
from app import application as core


class CompanyApproval(core.Base):
    __tablename__ = "company_approvals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    priority: Mapped[str] = mapped_column(String(10), default="P2", index=True)
    approval_level: Mapped[str] = mapped_column(String(20), default="APPROVAL", index=True)
    source: Mapped[str] = mapped_column(String(100), default="AI Company", index=True)
    action_type: Mapped[str] = mapped_column(String(80), default="general", index=True)
    title: Mapped[str] = mapped_column(String(255))
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class CompanyDecision(core.Base):
    __tablename__ = "company_decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255))
    decision: Mapped[str] = mapped_column(Text)
    rationale: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)


class CompanyBrief(core.Base):
    __tablename__ = "company_briefs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    period: Mapped[str] = mapped_column(String(20), index=True)
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)


def _admin_redirect(request: Request):
    try:
        core.require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)
    return None


def ensure_approval(db: Session, *, priority: str, approval_level: str, source: str, action_type: str, title: str, details: str = "") -> CompanyApproval:
    existing = db.scalar(select(CompanyApproval).where(
        CompanyApproval.status == "pending",
        CompanyApproval.source == source,
        CompanyApproval.action_type == action_type,
        CompanyApproval.title == title,
    ))
    if existing:
        existing.priority = priority
        existing.approval_level = approval_level
        existing.details = details or existing.details
        db.commit()
        return existing
    row = CompanyApproval(priority=priority, approval_level=approval_level, source=source, action_type=action_type, title=title, details=details or None)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def generate_ceo_brief(db: Session, period: str = "daily", save: bool = False) -> str:
    period = period if period in {"daily", "weekly", "monthly"} else "daily"
    snapshot = ai_company.collect_company_snapshot(db)
    pending_approvals = int(db.scalar(select(func.count(CompanyApproval.id)).where(CompanyApproval.status == "pending")) or 0)
    new_opportunities = int(db.scalar(select(func.count(ai_company.CompanyOpportunity.id)).where(ai_company.CompanyOpportunity.status == "new")) or 0)
    high_alerts = int(db.scalar(select(func.count(ai_company.CompanyAlert.id)).where(ai_company.CompanyAlert.status == "open", ai_company.CompanyAlert.severity.in_(["P0", "P1"]))) or 0)
    open_tasks = int(db.scalar(select(func.count(ai_company.CompanyTask.id)).where(ai_company.CompanyTask.status == "open")) or 0)
    label = {"daily": "اليومي", "weekly": "الأسبوعي", "monthly": "الشهري"}[period]
    body = (
        f"ملخص المدير التنفيذي {label}\n"
        f"صحة الشركة: {snapshot['overall_score']}/100\n"
        f"صحة التقنية: {snapshot['technology_score']}/100\n"
        f"القسائم: {snapshot['vouchers']['total']} إجمالي · {snapshot['vouchers']['active']} نشطة · {snapshot['vouchers']['redeemed']} مستخدمة\n"
        f"الفرص الجديدة: {new_opportunities}\n"
        f"التنبيهات الحرجة/العالية المفتوحة: {high_alerts}\n"
        f"المهام المفتوحة: {open_tasks}\n"
        f"الموافقات بانتظار القرار: {pending_approvals}\n"
        "قاعدة التشغيل: البحث والتحليل والمراقبة AUTO؛ التواصل التجاري/تعديل السعر/إضافة منتج APPROVAL؛ الالتزامات المالية والشراكات الحساسة ONLY_CEO."
    )
    if save:
        db.add(CompanyBrief(period=period, title=f"الملخص {label}", body=body))
        db.commit()
        core.log_event(db, "company_ceo_brief_saved", details=f"period={period}")
    return body


def _approval_actions(row: CompanyApproval) -> str:
    if row.status != "pending":
        return "—"
    return (
        f"<form method='post' action='/admin/company/governance/{row.id}/approve' style='display:inline'>"
        "<button class='btn btn-blue' type='submit'>موافقة</button></form> "
        f"<form method='post' action='/admin/company/governance/{row.id}/reject' style='display:inline'>"
        "<button class='btn btn-muted' type='submit'>رفض</button></form>"
    )


@core.app.get("/admin/company/governance", response_class=HTMLResponse)
def governance_page(request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect
    approvals = list(db.scalars(select(CompanyApproval).order_by(CompanyApproval.created_at.desc()).limit(100)).all())
    decisions = list(db.scalars(select(CompanyDecision).order_by(CompanyDecision.created_at.desc()).limit(30)).all())
    approval_rows = "".join(
        "<tr>"
        f"<td>{core.esc(a.priority)}</td><td>{core.esc(a.approval_level)}</td>"
        f"<td>{core.esc(a.source)}</td><td><strong>{core.esc(a.title)}</strong><div class='muted'>{core.esc(a.details or '')}</div></td>"
        f"<td>{core.esc(a.status)}</td><td>{_approval_actions(a)}</td></tr>"
        for a in approvals
    ) or "<tr><td colspan='6' class='muted'>لا توجد موافقات بعد.</td></tr>"
    decision_rows = "".join(
        f"<tr><td>{core.esc(d.title)}</td><td>{core.esc(d.decision)}</td><td>{core.esc(d.rationale or '—')}</td><td>{core.esc(core.fmt_dt(d.created_at))}</td></tr>"
        for d in decisions
    ) or "<tr><td colspan='4' class='muted'>لا توجد قرارات محفوظة بعد.</td></tr>"
    body = f"""
    <main class='wrap' style='padding:28px 0 48px'>
      <div style='display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap'>
        <div><h1 style='margin-bottom:4px'>الحوكمة والموافقات</h1><p class='muted'>AUTO · APPROVAL · ONLY CEO</p></div>
        <div style='display:flex;gap:8px;flex-wrap:wrap'><a class='btn btn-muted' href='/admin/company'>مركز التحكم</a><a class='btn btn-blue' href='/admin/company/brief'>ملخص المدير التنفيذي</a></div>
      </div>
      <section class='card' style='padding:22px;margin:18px 0'><h2>مصفوفة الصلاحيات</h2><table><tbody>
        <tr><th>AUTO</th><td>بحث، تحليل، مراقبة، تصنيف، تقارير، اكتشاف مشاكل وفرص.</td></tr>
        <tr><th>APPROVAL</th><td>مراسلة تاجر/مورد، تعديل سعر أو خصم، إضافة منتج، تغيير صفحة أو حملة.</td></tr>
        <tr><th>ONLY CEO</th><td>شراء/التزام مالي، عقد، تغيير عمولة، خصم كبير، حذف جوهري، شراكة أو تغيير أمني مهم.</td></tr>
      </tbody></table></section>
      <section class='card' style='padding:22px;margin-bottom:18px'><h2>قائمة الموافقات</h2><div class='table-wrap'><table><thead><tr><th>الأولوية</th><th>المستوى</th><th>المصدر</th><th>الإجراء</th><th>الحالة</th><th>القرار</th></tr></thead><tbody>{approval_rows}</tbody></table></div></section>
      <section class='card' style='padding:22px'><h2>سجل القرارات</h2><div class='table-wrap'><table><thead><tr><th>العنوان</th><th>القرار</th><th>السبب</th><th>التاريخ</th></tr></thead><tbody>{decision_rows}</tbody></table></div></section>
    </main>"""
    return HTMLResponse(core.page_shell("الحوكمة والموافقات", body, admin=True))


@core.app.post("/admin/company/governance/{approval_id}/{decision}")
def decide_approval(approval_id: int, decision: str, request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect
    if decision not in {"approve", "reject"}:
        raise HTTPException(status_code=400, detail="قرار غير صحيح")
    row = db.get(CompanyApproval, approval_id)
    if not row:
        raise HTTPException(status_code=404, detail="الموافقة غير موجودة")
    if row.status != "pending":
        return RedirectResponse("/admin/company/governance", status_code=303)
    row.status = "approved" if decision == "approve" else "rejected"
    row.decided_at = datetime.now(timezone.utc)
    db.add(CompanyDecision(title=row.title, decision=row.status, rationale=f"المستوى: {row.approval_level} · المصدر: {row.source}"))
    db.commit()
    core.log_event(db, "company_approval_decided", details=f"approval={row.id}; status={row.status}; level={row.approval_level}")
    return RedirectResponse("/admin/company/governance", status_code=303)


@core.app.get("/admin/company/brief", response_class=HTMLResponse)
def ceo_brief_page(request: Request, period: str = "daily", db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect
    body_text = generate_ceo_brief(db, period=period, save=False)
    latest = list(db.scalars(select(CompanyBrief).order_by(CompanyBrief.created_at.desc()).limit(10)).all())
    history = "".join(f"<tr><td>{core.esc(b.period)}</td><td>{core.esc(b.title)}</td><td>{core.esc(core.fmt_dt(b.created_at))}</td></tr>" for b in latest) or "<tr><td colspan='3' class='muted'>لا توجد نسخ محفوظة بعد.</td></tr>"
    content = core.esc(body_text).replace("\n", "<br>")
    body = f"""
    <main class='wrap' style='padding:28px 0 48px'>
      <div style='display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap'><h1>ملخص المدير التنفيذي</h1><a class='btn btn-muted' href='/admin/company'>مركز التحكم</a></div>
      <div style='display:flex;gap:8px;flex-wrap:wrap;margin-bottom:18px'><a class='btn btn-muted' href='?period=daily'>يومي</a><a class='btn btn-muted' href='?period=weekly'>أسبوعي</a><a class='btn btn-muted' href='?period=monthly'>شهري</a></div>
      <section class='card' style='padding:24px;margin-bottom:18px'><div style='line-height:2;font-size:17px'>{content}</div><form method='post' action='/admin/company/brief/save?period={core.esc(period)}'><button class='btn btn-blue' style='margin-top:16px' type='submit'>حفظ هذا الملخص</button></form></section>
      <section class='card' style='padding:22px'><h2>سجل الملخصات</h2><table><thead><tr><th>الفترة</th><th>العنوان</th><th>التاريخ</th></tr></thead><tbody>{history}</tbody></table></section>
    </main>"""
    return HTMLResponse(core.page_shell("ملخص المدير التنفيذي", body, admin=True))


@core.app.post("/admin/company/brief/save")
def save_ceo_brief(request: Request, period: str = "daily", db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect
    generate_ceo_brief(db, period=period, save=True)
    return RedirectResponse(f"/admin/company/brief?period={period}", status_code=303)
