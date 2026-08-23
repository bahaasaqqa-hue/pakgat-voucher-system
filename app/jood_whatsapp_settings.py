from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import parse_qs

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import DateTime, Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app import application as core


CUSTOMER_DEFAULT_OUTREACH_PROMPT = """تواصلي مع العميل بصفتك جود من منصة باكيجات. رحبي به باختصار، افهمي احتياجه، وقدمي فقط عرضًا أو فئة معتمدة ومناسبة. ساعديه على اتخاذ الخطوة التالية أو الشراء، ولا تختلقي سعرًا أو رابطًا أو توفرًا غير موجود في السياق."""

MERCHANT_DEFAULT_OUTREACH_PROMPT = """تواصلي مع التاجر بصفتك جود، مسؤولة تطوير الشراكات والمبيعات في منصة باكيجات. عرّفي بالمنصة باختصار، افتحي باب التعاون، وافهمي النشاط والمدينة والخدمات والعرض الممكن تقديمه. لا تلتزمي بعمولة نهائية أو مبيعات مضمونة، وحولي المهتم للفريق المختص عند الحاجة."""


class JoodWhatsAppSetting(core.Base):
    __tablename__ = "jood_whatsapp_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


def default_prompt_for_type(contact_type: str) -> str:
    return (
        MERCHANT_DEFAULT_OUTREACH_PROMPT
        if str(contact_type or "").strip().lower() == "merchant"
        else CUSTOMER_DEFAULT_OUTREACH_PROMPT
    )


def default_outreach_prompt(db: Session, contact_type: str) -> str:
    mode = "merchant" if str(contact_type or "").strip().lower() == "merchant" else "customer"
    row = db.scalar(select(JoodWhatsAppSetting).where(JoodWhatsAppSetting.key == f"{mode}_outreach_prompt"))
    return str(row.value).strip() if row and str(row.value).strip() else default_prompt_for_type(mode)


def compose_outreach_instruction(contact_type: str, default_prompt: str, override: str = "") -> str:
    base = str(default_prompt or "").strip() or default_prompt_for_type(contact_type)
    special = str(override or "").strip()
    if not special:
        return base
    return f"{base}\n\nتعليمات خاصة لهذه الجهة أو الحملة:\n{special}"


def resolved_outreach_instruction(db: Session, contact_type: str, override: str = "") -> str:
    return compose_outreach_instruction(contact_type, default_outreach_prompt(db, contact_type), override)


def _admin_redirect(request: Request):
    try:
        core.require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)
    return None


@core.app.get("/admin/company/jood/whatsapp-settings", response_class=HTMLResponse)
def whatsapp_settings_page(request: Request, saved: int = 0, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect
    customer = default_outreach_prompt(db, "customer")
    merchant = default_outreach_prompt(db, "merchant")
    notice = "<div class='alert alert-ok'>تم حفظ توجيهات جود.</div>" if saved else ""
    body = f"""
    <main class='wrap' style='padding:28px 0 48px'><section class='card' style='padding:24px'>
      <h1>إعدادات واتساب جود</h1>{notice}
      <p class='muted'>تُحفظ مرة واحدة وتستخدم تلقائيًا. تعليمات العميل أو الحملة الخاصة اختيارية.</p>
      <form method='post' action='/admin/company/jood/whatsapp-settings'>
        <label>التوجيه الافتراضي للعملاء</label>
        <textarea class='input' name='customer_prompt' rows='7' required>{core.esc(customer)}</textarea>
        <label style='margin-top:14px'>التوجيه الافتراضي للتجار</label>
        <textarea class='input' name='merchant_prompt' rows='7' required>{core.esc(merchant)}</textarea>
        <button class='btn btn-blue' style='margin-top:14px' type='submit'>حفظ التوجيهات</button>
      </form>
    </section></main>"""
    return HTMLResponse(core.page_shell("إعدادات واتساب جود", body, admin=True))


@core.app.post("/admin/company/jood/whatsapp-settings")
async def whatsapp_settings_save(request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect
    form = parse_qs((await request.body()).decode("utf-8", errors="ignore"))
    values = {
        "customer_outreach_prompt": str((form.get("customer_prompt") or [""])[0]).strip(),
        "merchant_outreach_prompt": str((form.get("merchant_prompt") or [""])[0]).strip(),
    }
    if not all(values.values()):
        raise HTTPException(status_code=400, detail="Both default prompts are required")
    for key, value in values.items():
        row = db.scalar(select(JoodWhatsAppSetting).where(JoodWhatsAppSetting.key == key))
        if row:
            row.value = value[:12000]
            row.updated_at = datetime.now(timezone.utc)
        else:
            db.add(JoodWhatsAppSetting(key=key, value=value[:12000]))
    db.commit()
    return RedirectResponse("/admin/company/jood/whatsapp-settings?saved=1", status_code=303)

