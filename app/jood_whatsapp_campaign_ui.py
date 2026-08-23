from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import application as core
from app.jood_whatsapp_campaign import JoodWhatsAppCampaign, JoodWhatsAppDispatch


def _admin_redirect(request: Request):
    try:
        core.require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)
    return None


@core.app.get("/admin/company/jood/whatsapp-campaigns", response_class=HTMLResponse)
def whatsapp_campaigns_page(request: Request, db: Session = Depends(core.get_db)):
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
    rows = []
    for campaign in campaigns:
        sent_count = int(
            db.scalar(
                select(func.count(JoodWhatsAppDispatch.id)).where(
                    JoodWhatsAppDispatch.campaign_id == campaign.id,
                    JoodWhatsAppDispatch.status == "sent",
                )
            )
            or 0
        )
        rows.append(
            "<tr>"
            f"<td><strong>{core.esc(campaign.name)}</strong><div class='muted'>{core.esc((campaign.goal or '')[:220])}</div></td>"
            f"<td>{core.esc(campaign.contact_type)}</td>"
            f"<td>{core.esc(campaign.status)}</td>"
            f"<td>{sent_count}</td>"
            "<td>"
            f"<form method='post' action='/admin/company/jood/whatsapp-campaigns/{campaign.id}/next'>"
            "<button class='btn btn-blue' type='submit'>إرسال للجهة التالية</button>"
            "</form>"
            "</td>"
            "</tr>"
        )
    table_rows = "".join(rows) or "<tr><td colspan='5' class='muted'>لا توجد حملات واتساب حتى الآن.</td></tr>"

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

      <section class='card' style='padding:22px;margin:18px 0'>
        <h2>إنشاء حملة واتساب</h2>
        <form method='post' action='/admin/company/jood/control/whatsapp-campaigns'>
          <div class='grid grid-mobile-1' style='grid-template-columns:1fr 1fr'>
            <div><label>اسم الحملة</label><input class='input' name='name' placeholder='استقطاب مطاعم الرياض'></div>
            <div><label>نوع القائمة</label><select class='select' name='contact_type'><option value='merchant'>Merchant</option><option value='customer'>Customer</option></select></div>
          </div>
          <label style='margin-top:12px'>الهدف الذي تعطيه لجود</label>
          <textarea class='input' name='goal' rows='5' required placeholder='مثال: عرّفي التجار ببكجات وافتحي باب التعاون، بدون ذكر عمولة نهائية أو وعود مبيعات.'></textarea>
          <button class='btn btn-blue' style='margin-top:12px' type='submit'>إنشاء الحملة</button>
        </form>
        <p class='muted' style='margin-top:10px'>الإرسال الحالي يتم جهةً جهة من الطابور حتى نراقب الجودة ونمنع الإزعاج. Do Not Contact مستبعد برمجيًا.</p>
      </section>

      <section class='card' style='padding:22px'>
        <h2>الحملات</h2>
        <div class='table-wrap'><table><thead><tr><th>الحملة</th><th>النوع</th><th>الحالة</th><th>تم الإرسال</th><th>الإجراء</th></tr></thead><tbody>{table_rows}</tbody></table></div>
      </section>
    </main>
    """
    return HTMLResponse(core.page_shell("جود · حملات واتساب", body, admin=True))
