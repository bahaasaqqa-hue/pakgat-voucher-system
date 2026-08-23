from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import application as core
from app.jood_company_ops import CompanyContact, JoodCallCampaign, JoodCallLog


def _admin_redirect(request: Request):
    try:
        core.require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)
    return None


@core.app.get("/admin/company/jood/control", response_class=HTMLResponse)
def jood_control_center(request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect

    contacts = list(
        db.scalars(
            select(CompanyContact)
            .order_by(CompanyContact.updated_at.desc(), CompanyContact.id.desc())
            .limit(150)
        ).all()
    )
    campaigns = list(
        db.scalars(
            select(JoodCallCampaign)
            .order_by(JoodCallCampaign.created_at.desc(), JoodCallCampaign.id.desc())
            .limit(30)
        ).all()
    )
    logs = list(
        db.scalars(
            select(JoodCallLog)
            .order_by(JoodCallLog.ended_at.desc(), JoodCallLog.id.desc())
            .limit(50)
        ).all()
    )

    contact_rows = "".join(
        "<tr>"
        f"<td><strong>{core.esc(c.display_name or c.business_name or '—')}</strong>"
        f"<div class='muted'>{core.esc(c.business_name or '')}</div></td>"
        f"<td>{core.esc(c.contact_type)}</td>"
        f"<td dir='ltr'>{core.esc(core.masked_phone(c.phone))}</td>"
        f"<td>{core.esc(c.city or '—')}</td>"
        f"<td>{core.esc(c.merchant_stage or '—')}</td>"
        f"<td>{core.esc(c.status)}</td>"
        "<td style='white-space:nowrap'>"
        f"<a class='btn btn-blue' href='/admin/company/jood/contacts/{c.id}/whatsapp'>واتساب بواسطة جود</a> "
        f"<a class='btn btn-muted' href='/admin/company/jood/contacts/{c.id}/call'>اتصال بواسطة جود</a>"
        "</td></tr>"
        for c in contacts
    ) or "<tr><td colspan='7' class='muted'>لا توجد جهات اتصال بعد.</td></tr>"

    campaign_rows = "".join(
        "<tr>"
        f"<td><strong>{core.esc(c.name)}</strong><div class='muted'>{core.esc((c.goal or '')[:160])}</div></td>"
        f"<td>{core.esc(c.contact_type)}</td>"
        f"<td>{core.esc(core.fmt_dt(c.start_at))}</td>"
        f"<td>{core.esc(core.fmt_dt(c.end_at))}</td>"
        f"<td>{core.esc(c.status)}</td>"
        "<td>30 ثانية</td>"
        f"<td><a class='btn btn-blue' href='/admin/company/jood/campaigns/{c.id}/next'>الاتصال التالي</a></td>"
        "</tr>"
        for c in campaigns
    ) or "<tr><td colspan='7' class='muted'>لا توجد حملات اتصال بعد.</td></tr>"

    log_rows = "".join(
        "<tr>"
        f"<td>{core.esc(log.contact_name or '—')}</td>"
        f"<td>{core.esc(log.contact_type)}</td>"
        f"<td>{core.esc(log.outcome)}</td>"
        f"<td>{log.duration_seconds} ث</td>"
        f"<td>{core.esc((log.summary or '—')[:240])}</td>"
        f"<td>{core.esc(core.fmt_dt(log.ended_at))}</td>"
        f"<td><a class='btn btn-muted' href='/admin/company/jood/calls/{log.id}'>فتح السجل</a></td>"
        "</tr>"
        for log in logs
    ) or "<tr><td colspan='7' class='muted'>لا توجد مكالمات مسجلة بعد.</td></tr>"

    body = f"""
    <main class='wrap' style='padding:28px 0 48px'>
      <div style='display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap'>
        <div><h1 style='margin-bottom:4px'>جود · Company AI</h1>
        <p class='muted'>نفس الذكاء والذاكرة: WhatsApp + Voice · Customer + Merchant</p></div>
        <div style='display:flex;gap:8px;flex-wrap:wrap'>
          <a class='btn btn-muted' href='/admin/company/whatsloop'>WhatsLoop Inbox</a>
          <a class='btn btn-muted' href='/admin/company'>Control Center</a>
        </div>
      </div>

      <div class='grid grid-mobile-1' style='grid-template-columns:repeat(4,1fr);margin:18px 0'>
        <section class='card' style='padding:18px'><div class='muted'>Contacts</div><div style='font-size:30px;font-weight:900'>{len(contacts)}</div></section>
        <section class='card' style='padding:18px'><div class='muted'>Customers</div><div style='font-size:30px;font-weight:900'>{sum(1 for c in contacts if c.contact_type == 'customer')}</div></section>
        <section class='card' style='padding:18px'><div class='muted'>Merchants</div><div style='font-size:30px;font-weight:900'>{sum(1 for c in contacts if c.contact_type == 'merchant')}</div></section>
        <section class='card' style='padding:18px'><div class='muted'>Call Logs</div><div style='font-size:30px;font-weight:900'>{len(logs)}</div></section>
      </div>

      <section class='card' style='padding:22px;margin-bottom:18px'>
        <h2>إضافة Customer / Merchant</h2>
        <form method='post' action='/admin/company/jood/contacts'>
          <div class='grid grid-mobile-1' style='grid-template-columns:repeat(3,1fr)'>
            <div><label>رقم الجوال</label><input class='input' name='phone' dir='ltr' required placeholder='05xxxxxxxx'></div>
            <div><label>النوع</label><select class='select' name='contact_type'><option value='customer'>Customer</option><option value='merchant'>Merchant</option></select></div>
            <div><label>الاسم</label><input class='input' name='display_name'></div>
            <div><label>اسم النشاط</label><input class='input' name='business_name'></div>
            <div><label>المدينة</label><input class='input' name='city' placeholder='الرياض'></div>
            <div><label>ملاحظات / سياق معتمد</label><input class='input' name='notes'></div>
          </div>
          <button class='btn btn-blue' style='margin-top:12px' type='submit'>حفظ الجهة</button>
        </form>
      </section>

      <section class='card' style='padding:22px;margin-bottom:18px'>
        <h2>Contacts · إجراءات جود</h2>
        <div class='table-wrap'><table><thead><tr><th>الاسم/النشاط</th><th>النوع</th><th>الهاتف</th><th>المدينة</th><th>Stage</th><th>Status</th><th>الإجراء</th></tr></thead><tbody>{contact_rows}</tbody></table></div>
      </section>

      <section class='card' style='padding:22px;margin-bottom:18px'>
        <h2>إنشاء Call Window</h2>
        <p class='muted'>الأوقات تُدخل بتوقيت الرياض. المهلة بين المكالمات ثابتة 30 ثانية. v1: الاتصال يبدأ يدويًا من Phone Link، وبعد الرد تتولى جود الحوار.</p>
        <form method='post' action='/admin/company/jood/campaigns'>
          <div class='grid grid-mobile-1' style='grid-template-columns:repeat(2,1fr)'>
            <div><label>اسم الحملة</label><input class='input' name='name' placeholder='استقطاب تجار مطاعم'></div>
            <div><label>نوع القائمة</label><select class='select' name='contact_type'><option value='merchant'>Merchant</option><option value='customer'>Customer</option></select></div>
            <div><label>من</label><input class='input' name='start_at' type='datetime-local' required></div>
            <div><label>إلى</label><input class='input' name='end_at' type='datetime-local' required></div>
          </div>
          <label style='margin-top:12px'>هدف جود من المكالمات</label>
          <textarea class='input' name='goal' rows='4' required placeholder='مثال: عرّفي التاجر ببكجات، افهمي اهتمامه، واجمعي بيانات المسؤول بدون تفاوض على عمولة نهائية.'></textarea>
          <input type='hidden' name='transcript_enabled' value='1'>
          <button class='btn btn-blue' style='margin-top:12px' type='submit'>إنشاء نافذة الاتصال</button>
        </form>
      </section>

      <section class='card' style='padding:22px;margin-bottom:18px'>
        <h2>Call Campaigns</h2>
        <div class='table-wrap'><table><thead><tr><th>الحملة</th><th>النوع</th><th>من</th><th>إلى</th><th>الحالة</th><th>Cooldown</th><th>الإجراء</th></tr></thead><tbody>{campaign_rows}</tbody></table></div>
      </section>

      <section class='card' style='padding:22px'>
        <h2>Call Log</h2>
        <div class='table-wrap'><table><thead><tr><th>الجهة</th><th>النوع</th><th>النتيجة</th><th>المدة</th><th>الملخص</th><th>الوقت</th><th></th></tr></thead><tbody>{log_rows}</tbody></table></div>
      </section>
    </main>
    """
    return HTMLResponse(core.page_shell("جود · Company AI", body, admin=True))


@core.app.get("/admin/company/jood/calls/{log_id}", response_class=HTMLResponse)
def jood_call_log_detail(log_id: int, request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect
    log = db.get(JoodCallLog, log_id)
    if not log:
        raise HTTPException(status_code=404, detail="Call log not found")
    body = f"""
    <main class='wrap' style='padding:28px 0 48px'>
      <section class='card' style='max-width:980px;margin:auto;padding:24px'>
        <div style='display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap'>
          <div><h1>Call Log #{log.id}</h1><p class='muted'>{core.esc(log.contact_name or '—')} · {core.esc(log.contact_type)} · {core.esc(log.outcome)}</p></div>
          <a class='btn btn-muted' href='/admin/company/jood/control'>رجوع</a>
        </div>
        <h3>الملخص</h3><div class='alert'>{core.esc(log.summary or '—')}</div>
        <div class='grid grid-mobile-1' style='grid-template-columns:repeat(3,1fr);margin:14px 0'>
          <div><strong>المدة</strong><div>{log.duration_seconds} ثانية</div></div>
          <div><strong>Human Follow-up</strong><div>{'نعم' if log.human_follow_up else 'لا'}</div></div>
          <div><strong>Do Not Contact</strong><div>{'نعم' if log.do_not_contact else 'لا'}</div></div>
        </div>
        <h3>Transcript</h3>
        <pre style='white-space:pre-wrap;direction:rtl;background:#f8fafc;padding:16px;border-radius:12px'>{core.esc(log.transcript or 'غير محفوظ')}</pre>
      </section>
    </main>
    """
    return HTMLResponse(core.page_shell(f"Call Log #{log.id}", body, admin=True))
