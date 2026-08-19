"""Manual opportunity assignment and WhatsLoop dispatch for Pakgat AI Company.

No opportunity is sent automatically. A protected admin user must choose an active
agent, review/edit the message, and explicitly confirm the WhatsApp send.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs
from urllib.request import Request as UrlRequest, urlopen

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.routing import APIRoute
from sqlalchemy import DateTime, Integer, String, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app import application as core
from app import ai_company


class CompanyAgent(core.Base):
    __tablename__ = "company_agents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    phone: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    city: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    specialties: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


class OpportunityDispatch(core.Base):
    __tablename__ = "opportunity_dispatches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    opportunity_id: Mapped[int] = mapped_column(Integer, index=True)
    agent_id: Mapped[int] = mapped_column(Integer, index=True)
    message: Mapped[str] = mapped_column(String(4000))
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    provider_status: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


OPEN_STAGES = ["new", "review", "approved", "active", "assigned", "contacted", "replied", "negotiating"]
PIPELINE_STAGES = ["assigned", "contacted", "replied", "negotiating", "won", "lost"]


def _admin_redirect(request: Request):
    try:
        core.require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)
    return None


def _form_value(form: dict, key: str, default: str = "") -> str:
    return str((form.get(key) or [default])[0]).strip()


def _default_message(opportunity: ai_company.CompanyOpportunity) -> str:
    score = f"{opportunity.score:.1f}" if opportunity.score is not None else "—"
    details = (opportunity.details or "لا توجد تفاصيل إضافية.").strip()
    return (
        "📌 فرصة جديدة من Pakgat\n\n"
        f"رقم الفرصة: OP-{opportunity.id:04d}\n"
        f"المصدر: {opportunity.source}\n"
        f"الأولوية: {opportunity.priority}\n"
        f"الفرصة: {opportunity.title}\n"
        f"Opportunity Score: {score}\n\n"
        f"التفاصيل:\n{details}\n\n"
        "المطلوب: راجع الفرصة، تواصل مع الجهة المناسبة إذا كانت قابلة للتنفيذ، ثم حدّث الإدارة بالنتيجة.\n\n"
        "Pakgat AI Company"
    )


def _send_whatsloop(phone: str, message: str) -> tuple[bool, str]:
    normalized = core.normalize_saudi_phone(phone)
    if not normalized:
        return False, "Invalid Saudi mobile number"
    if not core.WHATSLOOP_API_BASE_URL or not core.WHATSLOOP_API_TOKEN:
        return False, "WhatsLoop configuration is missing"

    body = json.dumps({"to": normalized, "message": message}, ensure_ascii=False).encode("utf-8")
    req = UrlRequest(
        f"{core.WHATSLOOP_API_BASE_URL}/messages/send-text",
        data=body,
        headers={
            "Authorization": f"Bearer {core.WHATSLOOP_API_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=25) as response:
            text = response.read().decode("utf-8", errors="replace")
            status_code = getattr(response, "status", response.getcode())
        return 200 <= int(status_code) < 300, f"HTTP {status_code}: {text[:350]}"
    except HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        return False, f"HTTP {exc.code}: {text[:350]}"
    except (URLError, TimeoutError, OSError) as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:350]}"


@core.app.get("/admin/company/agents", response_class=HTMLResponse)
def agents_page(request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect

    agents = list(db.scalars(select(CompanyAgent).order_by(CompanyAgent.name)).all())
    rows = "".join(
        "<tr>"
        f"<td><strong>{core.esc(a.name)}</strong></td>"
        f"<td>{core.esc(a.city or '—')}</td>"
        f"<td>{core.esc(a.specialties or '—')}</td>"
        f"<td dir='ltr'>{core.esc(core.masked_phone(a.phone))}</td>"
        f"<td>{core.esc(a.status)}</td>"
        "</tr>"
        for a in agents
    ) or "<tr><td colspan='5' class='muted'>لا يوجد مندوبون محفوظون بعد.</td></tr>"

    body = f"""
    <main class='wrap' style='padding:28px 0 48px'>
      <div style='display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap'>
        <div><h1 style='margin-bottom:4px'>دليل مندوبي Pakgat</h1><p class='muted'>يستخدم فقط لإسناد الفرص يدويًا وإرسالها عبر WhatsLoop.</p></div>
        <a class='btn btn-muted' href='/admin/company/opportunities'>الفرص والإسناد</a>
      </div>
      <section class='card' style='padding:22px;margin:18px 0'>
        <h2>إضافة مندوب</h2>
        <form method='post' action='/admin/company/agents'>
          <div class='grid grid-mobile-1' style='grid-template-columns:repeat(2,1fr)'>
            <div><label>الاسم</label><input class='input' name='name' required></div>
            <div><label>رقم واتساب</label><input class='input' name='phone' dir='ltr' placeholder='05xxxxxxxx' required></div>
            <div><label>المدينة</label><input class='input' name='city' placeholder='الرياض'></div>
            <div><label>التخصص / الفئات</label><input class='input' name='specialties' placeholder='مطاعم، سيارات، جمال...'></div>
          </div>
          <button class='btn btn-blue' style='margin-top:14px' type='submit'>حفظ المندوب</button>
        </form>
      </section>
      <section class='card' style='padding:22px'>
        <h2>المندوبون</h2>
        <div class='table-wrap'><table><thead><tr><th>الاسم</th><th>المدينة</th><th>التخصص</th><th>الهاتف</th><th>الحالة</th></tr></thead><tbody>{rows}</tbody></table></div>
      </section>
    </main>
    """
    return HTMLResponse(core.page_shell("مندوبي Pakgat", body, admin=True))


@core.app.post("/admin/company/agents")
async def agents_add(request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect
    form = parse_qs((await request.body()).decode("utf-8", errors="ignore"))
    name = _form_value(form, "name")
    phone = core.normalize_saudi_phone(_form_value(form, "phone"))
    city = _form_value(form, "city")
    specialties = _form_value(form, "specialties")
    if not name or not phone:
        raise HTTPException(status_code=400, detail="Name and valid Saudi phone are required")

    existing = db.scalar(select(CompanyAgent).where(CompanyAgent.phone == phone))
    if existing:
        existing.name = name
        existing.city = city or existing.city
        existing.specialties = specialties or existing.specialties
        existing.status = "active"
    else:
        db.add(
            CompanyAgent(
                name=name,
                phone=phone,
                city=city or None,
                specialties=specialties or None,
                status="active",
            )
        )
    db.commit()
    core.log_event(db, "company_agent_saved", details=f"name={name}; phone={core.masked_phone(phone)}")
    return RedirectResponse("/admin/company/agents", status_code=303)


@core.app.get("/admin/company/opportunities", response_class=HTMLResponse)
def opportunity_assignment_center(request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect

    opportunities = list(
        db.scalars(
            select(ai_company.CompanyOpportunity)
            .where(ai_company.CompanyOpportunity.status.in_(OPEN_STAGES))
            .order_by(ai_company.CompanyOpportunity.score.desc().nullslast(), ai_company.CompanyOpportunity.created_at.desc())
        ).all()
    )
    agents_count = int(db.scalar(select(func.count(CompanyAgent.id)).where(CompanyAgent.status == "active")) or 0)
    rows = "".join(
        "<tr>"
        f"<td>OP-{o.id:04d}</td>"
        f"<td>{core.esc(o.priority)}</td>"
        f"<td>{core.esc(o.source)}</td>"
        f"<td><strong>{core.esc(o.title)}</strong><div class='muted'>{core.esc(o.details or '')}</div></td>"
        f"<td>{core.esc(f'{o.score:.1f}' if o.score is not None else '—')}</td>"
        f"<td>{core.esc(o.status)}</td>"
        f"<td><a class='btn btn-blue' href='/admin/company/opportunities/{o.id}/assign'>إسناد وإرسال</a></td>"
        "</tr>"
        for o in opportunities
    ) or "<tr><td colspan='7' class='muted'>لا توجد فرص مفتوحة حاليًا.</td></tr>"

    body = f"""
    <main class='wrap' style='padding:28px 0 48px'>
      <div style='display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap'>
        <div><h1 style='margin-bottom:4px'>الفرص · الإسناد والتنفيذ</h1><p class='muted'>الإرسال لا يتم تلقائيًا. أنت تختار المندوب وتراجع الرسالة ثم تؤكد الإرسال.</p></div>
        <div style='display:flex;gap:8px'><a class='btn btn-muted' href='/admin/company'>Control Center</a><a class='btn btn-blue' href='/admin/company/agents'>المندوبون ({agents_count})</a></div>
      </div>
      <section class='card' style='padding:22px;margin-top:18px'>
        <div class='table-wrap'><table><thead><tr><th>ID</th><th>Priority</th><th>Source</th><th>Opportunity</th><th>Score</th><th>Status</th><th>Action</th></tr></thead><tbody>{rows}</tbody></table></div>
      </section>
    </main>
    """
    return HTMLResponse(core.page_shell("إسناد الفرص", body, admin=True))


@core.app.get("/admin/company/opportunities/{opportunity_id}/assign", response_class=HTMLResponse)
def opportunity_assign_page(opportunity_id: int, request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect

    opportunity = db.get(ai_company.CompanyOpportunity, opportunity_id)
    if not opportunity:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    agents = list(
        db.scalars(select(CompanyAgent).where(CompanyAgent.status == "active").order_by(CompanyAgent.name)).all()
    )
    options = "".join(
        f"<option value='{a.id}'>{core.esc(a.name)} · {core.esc(a.city or 'بدون مدينة')} · {core.esc(a.specialties or 'عام')}</option>"
        for a in agents
    )
    if not options:
        options = "<option value=''>أضف مندوبًا أولاً من دليل المندوبين</option>"
    message = _default_message(opportunity)

    body = f"""
    <main class='wrap' style='padding:28px 0 48px'>
      <section class='card' style='max-width:900px;margin:auto;padding:24px'>
        <div style='display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap'>
          <div><h1>إسناد OP-{opportunity.id:04d}</h1><p><strong>{core.esc(opportunity.title)}</strong></p></div>
          <a class='btn btn-muted' href='/admin/company/opportunities'>رجوع</a>
        </div>
        <div class='alert' style='background:#fff7ed;color:#9a3412;border:1px solid #fed7aa'><strong>موافقة مطلوبة:</strong> لن يتم إرسال أي رسالة قبل ضغطك على زر التأكيد النهائي أدناه.</div>
        <form method='post' action='/admin/company/opportunities/{opportunity.id}/assign'>
          <label>المندوب</label>
          <select class='select' name='agent_id' required>{options}</select>
          <label style='margin-top:14px'>نص رسالة واتساب — قابل للتعديل</label>
          <textarea class='input' name='message' rows='14' style='resize:vertical' required>{core.esc(message)}</textarea>
          <label style='margin-top:14px;display:flex;gap:8px;align-items:center'><input type='checkbox' name='confirm_send' value='1' required> أؤكد إسناد هذه الفرصة وإرسال الرسالة الآن عبر WhatsLoop.</label>
          <button class='btn btn-blue' style='margin-top:14px;width:100%' type='submit' onclick='return confirm(&quot;تأكيد إرسال فرصة OP-{opportunity.id:04d} إلى المندوب المختار عبر واتساب؟&quot;);'>تأكيد الإسناد والإرسال</button>
        </form>
        <p class='muted' style='margin-top:14px'>لإضافة مندوب جديد: <a href='/admin/company/agents' style='color:#2446ba;font-weight:800'>دليل المندوبين</a></p>
      </section>
    </main>
    """
    return HTMLResponse(core.page_shell("إسناد فرصة", body, admin=True))


@core.app.post("/admin/company/opportunities/{opportunity_id}/assign", response_class=HTMLResponse)
async def opportunity_assign_send(opportunity_id: int, request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect

    opportunity = db.get(ai_company.CompanyOpportunity, opportunity_id)
    if not opportunity:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    form = parse_qs((await request.body()).decode("utf-8", errors="ignore"))
    agent_id_raw = _form_value(form, "agent_id")
    message = _form_value(form, "message")
    confirmed = _form_value(form, "confirm_send") == "1"
    if not confirmed:
        raise HTTPException(status_code=400, detail="Explicit send confirmation is required")
    try:
        agent_id = int(agent_id_raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Valid agent is required")
    agent = db.get(CompanyAgent, agent_id)
    if not agent or agent.status != "active":
        raise HTTPException(status_code=404, detail="Active agent not found")
    if not message:
        raise HTTPException(status_code=400, detail="Message is required")

    dispatch = OpportunityDispatch(
        opportunity_id=opportunity.id,
        agent_id=agent.id,
        message=message[:4000],
        status="sending",
    )
    db.add(dispatch)
    db.commit()
    db.refresh(dispatch)

    ok, provider_status = _send_whatsloop(agent.phone, message)
    dispatch.provider_status = provider_status[:500]
    if ok:
        dispatch.status = "sent"
        dispatch.sent_at = datetime.now(timezone.utc)
        opportunity.status = "assigned"
        opportunity.updated_at = datetime.now(timezone.utc)
        db.commit()
        core.log_event(
            db,
            "opportunity_whatsapp_sent",
            details=(
                f"opportunity=OP-{opportunity.id:04d}; agent={agent.name}; "
                f"phone={core.masked_phone(agent.phone)}"
            ),
        )
        result = (
            "<div class='alert alert-ok'><strong>تم الإسناد والإرسال بنجاح ✅</strong>"
            f"<div style='margin-top:8px'>OP-{opportunity.id:04d} → {core.esc(agent.name)}</div></div>"
        )
        code = 200
    else:
        dispatch.status = "failed"
        db.commit()
        core.log_event(
            db,
            "opportunity_whatsapp_failed",
            details=(
                f"opportunity=OP-{opportunity.id:04d}; agent={agent.name}; "
                f"phone={core.masked_phone(agent.phone)}; error={provider_status[:200]}"
            ),
        )
        result = (
            "<div class='alert alert-error'><strong>فشل إرسال WhatsApp.</strong>"
            f"<div style='margin-top:8px' dir='ltr'>{core.esc(provider_status)}</div></div>"
        )
        code = 502

    body = f"""
    <main class='wrap' style='padding:40px 0'>
      <section class='card' style='max-width:760px;margin:auto;padding:24px'>
        {result}
        <div style='display:flex;gap:8px;flex-wrap:wrap;margin-top:18px'>
          <a class='btn btn-blue' href='/admin/company/opportunities'>العودة للفرص</a>
          <a class='btn btn-muted' href='/admin/company'>Control Center</a>
        </div>
      </section>
    </main>
    """
    return HTMLResponse(core.page_shell("نتيجة إرسال الفرصة", body, admin=True), status_code=code)


@core.app.post("/admin/company/opportunities/{opportunity_id}/stage")
async def opportunity_update_stage(opportunity_id: int, request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect
    opportunity = db.get(ai_company.CompanyOpportunity, opportunity_id)
    if not opportunity:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    form = parse_qs((await request.body()).decode("utf-8", errors="ignore"))
    stage = _form_value(form, "stage").lower()
    if stage not in PIPELINE_STAGES:
        raise HTTPException(status_code=400, detail="Invalid stage")
    opportunity.status = stage
    opportunity.updated_at = datetime.now(timezone.utc)
    db.commit()
    core.log_event(db, "opportunity_stage_changed", details=f"OP-{opportunity.id:04d}; stage={stage}")
    return RedirectResponse("/admin/company/opportunities", status_code=303)


def _find_company_route():
    for route in core.app.routes:
        if isinstance(route, APIRoute) and route.path == "/admin/company" and "GET" in route.methods:
            return route
    return None


_company_route = _find_company_route()
if _company_route is not None:
    _original_company_dashboard = _company_route.dependant.call

    def _company_dashboard_with_dispatch(
        request: Request,
        db: Session = Depends(core.get_db),
    ):
        response = _original_company_dashboard(request, db)
        if not isinstance(response, HTMLResponse):
            return response
        active_agents = int(db.scalar(select(func.count(CompanyAgent.id)).where(CompanyAgent.status == "active")) or 0)
        assigned = int(
            db.scalar(
                select(func.count(ai_company.CompanyOpportunity.id)).where(
                    ai_company.CompanyOpportunity.status.in_(["assigned", "contacted", "replied", "negotiating"])
                )
            )
            or 0
        )
        section = f"""
        <section class='card' style='padding:22px;margin-bottom:18px'>
          <div style='display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap'>
            <div><h2 style='margin-bottom:4px'>Opportunity Dispatch · المندوبون</h2>
            <p class='muted' style='margin-top:0'>إسناد يدوي + مراجعة الرسالة + إرسال WhatsLoop بعد موافقتك فقط.</p></div>
            <div style='display:flex;gap:8px;flex-wrap:wrap'><a class='btn btn-blue' href='/admin/company/opportunities'>إدارة وإسناد الفرص</a><a class='btn btn-muted' href='/admin/company/agents'>المندوبون ({active_agents})</a></div>
          </div>
          <p style='margin-bottom:0'><strong>فرص تحت التنفيذ:</strong> {assigned}</p>
        </section>
        """
        html = response.body.decode("utf-8", errors="replace")
        marker = "</main>"
        html = html.replace(marker, section + marker, 1)
        response.body = html.encode("utf-8")
        response.headers["content-length"] = str(len(response.body))
        return response

    _company_route.endpoint = _company_dashboard_with_dispatch
    _company_route.dependant.call = _company_dashboard_with_dispatch
