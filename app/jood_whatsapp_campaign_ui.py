from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import application as core
from app.jood_company_ops import CompanyContact
from app.jood_whatsapp_campaign import JoodWhatsAppCampaign, JoodWhatsAppDispatch


def _admin_redirect(request: Request):
    try:
        core.require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)
    return None


@core.app.get("/admin/company/jood/whatsapp-campaigns", response_class=HTMLResponse)
def whatsapp_campaigns_page(
    request: Request,
    individual_sent: int = 0,
    started: int = 0,
    queued: int = 0,
    db: Session = Depends(core.get_db),
):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect

    campaigns = list(
        db.scalars(
            select(JoodWhatsAppCampaign)
            .order_by(JoodWhatsAppCampaign.created_at.desc(), JoodWhatsAppCampaign.id.desc())
            .limit(50)
        ).all()
    )
    recent_dispatches = list(
        db.scalars(
            select(JoodWhatsAppDispatch)
            .order_by(JoodWhatsAppDispatch.sent_at.desc(), JoodWhatsAppDispatch.id.desc())
            .limit(100)
        ).all()
    )
    contact_ids = {row.contact_id for row in recent_dispatches}
    contacts = {
        row.id: row
        for row in db.scalars(select(CompanyContact).where(CompanyContact.id.in_(contact_ids))).all()
    } if contact_ids else {}
    campaign_by_id = {campaign.id: campaign for campaign in campaigns}
    rows = []
    for campaign in campaigns:
        status_rows = db.execute(
            select(JoodWhatsAppDispatch.status, func.count(JoodWhatsAppDispatch.id))
            .where(JoodWhatsAppDispatch.campaign_id == campaign.id)
            .group_by(JoodWhatsAppDispatch.status)
        ).all()
        counts = {str(status): int(count) for status, count in status_rows}
        rows.append(
            "<tr>"
            f"<td><strong>{core.esc(campaign.name)}</strong><div class='muted'>{core.esc((campaign.goal or '')[:220])}</div></td>"
            f"<td>{core.esc(campaign.contact_type)}</td>"
            f"<td>{core.esc(campaign.status)}</td>"
            f"<td>{counts.get('queued', 0)}</td>"
            f"<td>{counts.get('sent', 0)}</td>"
            f"<td>{counts.get('replied', 0)}</td>"
            f"<td>{counts.get('failed', 0)}</td>"
            "<td>"
            + (
                f"<form method='post' action='/admin/company/jood/whatsapp-campaigns/{campaign.id}/retry'>"
                "<button class='btn btn-muted' type='submit'>إعادة الفاشل</button></form>"
                if counts.get("failed", 0)
                else "—"
            )
            + "</td>"
            "</tr>"
        )
    table_rows = "".join(rows) or "<tr><td colspan='8' class='muted'>لا توجد حملات واتساب حتى الآن.</td></tr>"
    result_rows = "".join(
        "<tr>"
        f"<td>{core.esc((contacts.get(row.contact_id).display_name if contacts.get(row.contact_id) else '') or (contacts.get(row.contact_id).business_name if contacts.get(row.contact_id) else '') or '—')}</td>"
        f"<td>{core.esc(campaign_by_id.get(row.campaign_id).name if campaign_by_id.get(row.campaign_id) else row.campaign_id)}</td>"
        f"<td>{core.esc(row.status)}</td>"
        f"<td>{core.esc((row.message or '—')[:220])}</td>"
        f"<td>{core.esc((row.provider_status or '—')[:180])}</td>"
        f"<td>{core.esc(core.fmt_dt(row.sent_at))}</td>"
        "</tr>"
        for row in recent_dispatches
    ) or "<tr><td colspan='6' class='muted'>لا توجد نتائج إرسال حتى الآن.</td></tr>"

    notice = ""
    if individual_sent:
        notice = "<div class='alert alert-ok'>تم إرسال رسالة جود بنجاح.</div>"
    elif started:
        notice = f"<div class='alert alert-ok'>بدأت الحملة تلقائيًا. تم وضع {queued} جهة في طابور الإرسال.</div>"

    body = f"""
    <main class='wrap' style='padding:28px 0 48px'>
      <div style='display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap'>
        <div><h1 style='margin-bottom:4px'>جود · حملات واتساب</h1>
        <p class='muted'>Customer أو Merchant من Company AI · نفس ذاكرة جود ونفس الـGuardrails.</p></div>
        <div style='display:flex;gap:8px'>
          <a class='btn btn-muted' href='/admin/company/jood/control'>مركز جود</a>
          <a class='btn btn-muted' href='/admin/company'>Company AI</a>
        </div>
      </div>
      {notice}

      <section class='card' style='padding:22px;margin:18px 0'>
        <h2>تواصل مع شخص واحد</h2>
        <form method='post' action='/admin/company/jood/whatsapp/send-now'>
          <div class='grid grid-mobile-1' style='grid-template-columns:repeat(3,1fr)'>
            <div><label>رقم الجوال *</label><input class='input' name='phone' dir='ltr' required placeholder='05xxxxxxxx'></div>
            <div><label>النوع</label><select class='select' name='contact_type'><option value='customer'>عميل</option><option value='merchant'>تاجر</option></select></div>
            <div><label>الاسم</label><input class='input' name='display_name'></div>
            <div><label>اسم النشاط</label><input class='input' name='business_name'></div>
            <div><label>المدينة</label><input class='input' name='city' placeholder='الرياض'></div>
            <div><label>ملاحظات معتمدة</label><input class='input' name='notes'></div>
          </div>
          <label style='margin-top:12px'>تعليمات خاصة <span class='muted'>(اختياري)</span></label>
          <textarea class='input' name='instruction' rows='3' placeholder='اتركها فارغة لتستخدم جود التوجيه العام تلقائيًا.'></textarea>
          <button class='btn btn-blue' style='margin-top:12px' type='submit'>تواصل الآن</button>
        </form>
      </section>

      <section class='card' style='padding:22px;margin:18px 0'>
        <h2>رفع قائمة وبدء حملة</h2>
        <p class='muted'>CSV أو Excel: رقم الجوال إلزامي، ويمكن إضافة الاسم، اسم النشاط، المدينة والملاحظات.</p>
        <form method='post' enctype='multipart/form-data' action='/admin/company/jood/whatsapp-campaigns/upload'>
          <div class='grid grid-mobile-1' style='grid-template-columns:1fr 1fr'>
            <div><label>اسم الحملة</label><input class='input' name='name' placeholder='استقطاب مطاعم الرياض'></div>
            <div><label>نوع القائمة</label><select class='select' name='contact_type'><option value='merchant'>تجار</option><option value='customer'>عملاء</option></select></div>
          </div>
          <label style='margin-top:12px'>ملف القائمة *</label>
          <input class='input' type='file' name='file' accept='.csv,.xlsx' required>
          <label style='margin-top:12px'>تعليمات خاصة بالحملة <span class='muted'>(اختياري)</span></label>
          <textarea class='input' name='instruction' rows='3' placeholder='اتركها فارغة لاستخدام توجيه جود العام.'></textarea>
          <button class='btn btn-blue' style='margin-top:12px' type='submit'>رفع وبدء الحملة</button>
        </form>
      </section>

      <section class='card' style='padding:22px'>
        <h2>الحملات</h2>
        <div class='table-wrap'><table><thead><tr><th>الحملة</th><th>النوع</th><th>الحالة</th><th>بالطابور</th><th>تم الإرسال</th><th>ردّ</th><th>فشل</th><th></th></tr></thead><tbody>{table_rows}</tbody></table></div>
      </section>
      <section class='card' style='padding:22px;margin-top:18px'>
        <h2>نتائج التواصل</h2>
        <div class='table-wrap'><table><thead><tr><th>الجهة</th><th>الحملة</th><th>النتيجة</th><th>رسالة جود</th><th>حالة المزود</th><th>الوقت</th></tr></thead><tbody>{result_rows}</tbody></table></div>
      </section>
      <p style='margin-top:14px'><a class='btn btn-muted' href='/admin/company/jood/whatsapp-settings'>تعديل توجيهات جود الافتراضية</a></p>
    </main>
    """
    return HTMLResponse(core.page_shell("جود · حملات واتساب", body, admin=True))
