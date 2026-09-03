"""Pilot opportunity scan for Pakgat AI Company.

This is a controlled test feed built from a manual public-web scan performed on
19 Aug 2026. It is intentionally NOT presented as the final autonomous market
radar. The goal is to populate realistic opportunities so the CEO can test the
opportunity, assignment and WhatsApp workflow before the full scanners are
connected.

The scan is idempotent by source + title: running it again does not duplicate an
existing opportunity regardless of its pipeline stage.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.routing import APIRoute
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import application as core
from app import ai_company


SCAN_DATE = "19-08-2026"

# Curated from public sources checked on 19 Aug 2026. Keep the source name and
# evidence summary visible so a field agent can verify availability before any
# merchant contact. Scores are Pakgat test-priority scores, not external ratings.
PILOT_OPPORTUNITIES = [
    {
        "priority": "P1",
        "source": "وزارة التجارة · موسم تخفيضات 2026",
        "title": "حملة استقطاب تجار موسم تخفيضات 2026",
        "score": 95.0,
        "details": (
            "وزارة التجارة أعلنت موسم تخفيضات 2026 من 1 أغسطس حتى 31 أكتوبر 2026. "
            "الفرصة: استهداف تجار الرياض الذين لديهم تخفيضات نظامية وعرض إدراج كوبونات/بكجات على بكجات. "
            "المطلوب من المندوب: بناء قائمة 10 تجار ذوي عروض قوية في السيارات والجمال والمطاعم والعيادات ثم التواصل بعد موافقة الإدارة. "
            f"تاريخ الفحص: {SCAN_DATE}. تحقق من استمرار العرض قبل التنفيذ."
        ),
    },
    {
        "priority": "P1",
        "source": "American Express Saudi · Auto Chapeau",
        "title": "استهداف Auto Chapeau كشريك عروض سيارات",
        "score": 91.0,
        "details": (
            "تم رصد عرض خصم 25% لـ Auto Chapeau ضمن عروض American Express السعودية حتى 30 أغسطس 2026. "
            "وجود خصم قائم يدل على قابلية النشاط للشراكات الترويجية. الفرصة: التفاوض على كوبون حصري لبكجات أو عرض أقوى لفترة محدودة. "
            f"تاريخ الفحص: {SCAN_DATE}. يجب على المندوب التحقق من العرض والفرع قبل التواصل."
        ),
    },
    {
        "priority": "P1",
        "source": "Riyad Bank · Drs Lounge Clinics",
        "title": "استهداف Drs Lounge Clinics كشريك عيادات",
        "score": 89.0,
        "details": (
            "تم رصد خصم 30% لدى Drs Lounge Clinics ضمن عروض بنك الرياض حتى 1 أكتوبر 2026. "
            "الفرصة: عرض كوبون/بكج حصري على بكجات يستهدف عملاء الرياض مع مقارنة قيمة العرض الحالي وإمكانية إضافة خدمة أو ميزة حصرية. "
            f"تاريخ الفحص: {SCAN_DATE}. تحقق من الشروط الحالية قبل التواصل."
        ),
    },
    {
        "priority": "P2",
        "source": "Riyad Bank · Arriyadh Roaster",
        "title": "استهداف Arriyadh Roaster كشريك مقاهي",
        "score": 84.0,
        "details": (
            "تم رصد خصم 15% لدى Arriyadh Roaster ضمن عروض بنك الرياض حتى 1 ديسمبر 2026. "
            "الفرصة: اختبار بكج قهوة/ضيافة أو كوبون حصري مناسب للأفراد والهدايا والشركات. "
            f"تاريخ الفحص: {SCAN_DATE}. تحقق من الفروع والتغطية قبل التواصل."
        ),
    },
    {
        "priority": "P2",
        "source": "Four Seasons Riyadh",
        "title": "فرصة بكج ضيافة وسبا فاخر في الرياض",
        "score": 80.0,
        "details": (
            "فورسيزونز الرياض يعرض حالياً ليالي صيف الرياض بخصم 20% على الغرف و10% على المأكولات والمشروبات و20% على علاجات السبا لتواريخ مختارة حتى 10 أكتوبر 2026. "
            "الفرصة: استخدام العرض كمرجع لفئة الضيافة الفاخرة واستكشاف شراكة أو باقة سبا/مطاعم/إقامة قابلة للبيع كهدية أو B2B. "
            f"تاريخ الفحص: {SCAN_DATE}. هذه فرصة استكشاف وليست اتفاقاً قائماً."
        ),
    },
    {
        "priority": "P1",
        "source": "Platinumlist Riyadh · BattleKart",
        "title": "استهداف BattleKart لعرض ترفيهي حصري",
        "score": 87.0,
        "details": (
            "تم رصد BattleKart Ladies Night في الرياض بسعر 79 ريال وممتد حتى 28 سبتمبر 2026. "
            "الفرصة: التواصل لعرض كوبون حصري أو باقة ثنائية/جماعية على بكجات ضمن فئة الترفيه. "
            f"تاريخ الفحص: {SCAN_DATE}. تحقق من التوفر والتواريخ قبل التواصل."
        ),
    },
    {
        "priority": "P2",
        "source": "Platinumlist Riyadh · Fontana Circus",
        "title": "فرصة شراكة أو توزيع لفعالية سيرك فونتانا",
        "score": 83.0,
        "details": (
            "دليل فعاليات الرياض في سبتمبر يعرض سيرك فونتانا من 16 سبتمبر إلى 3 أكتوبر 2026 بسعر يبدأ من 110 ريال وموسوماً بالأعلى مبيعاً. "
            "الفرصة: دراسة اتفاق توزيع/كوبون أو باقة عائلية موسمية عبر بكجات. "
            f"تاريخ الفحص: {SCAN_DATE}. التحقق من الجهة المنظمة وشروط التوزيع مطلوب قبل أي تواصل."
        ),
    },
]


def _admin_redirect(request: Request):
    try:
        core.require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)
    return None


def run_pilot_scan(db: Session) -> tuple[int, int]:
    created = 0
    skipped = 0
    now = datetime.now(timezone.utc)

    for item in PILOT_OPPORTUNITIES:
        existing = db.scalar(
            select(ai_company.CompanyOpportunity).where(
                ai_company.CompanyOpportunity.source == item["source"],
                ai_company.CompanyOpportunity.title == item["title"],
            )
        )
        if existing:
            skipped += 1
            continue

        db.add(
            ai_company.CompanyOpportunity(
                priority=item["priority"],
                source=item["source"],
                title=item["title"],
                details=item["details"][:1500],
                score=float(item["score"]),
                status="new",
                created_at=now,
                updated_at=now,
            )
        )
        created += 1

    db.commit()
    core.log_event(
        db,
        "pilot_opportunity_scan",
        details=f"scan_date={SCAN_DATE}; created={created}; skipped={skipped}",
    )
    return created, skipped


@core.app.get("/admin/company/pilot-scan", response_class=HTMLResponse)
def pilot_scan_page(request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect

    rows = "".join(
        "<tr>"
        f"<td>{core.esc(item['priority'])}</td>"
        f"<td>{core.esc(item['source'])}</td>"
        f"<td><strong>{core.esc(item['title'])}</strong><div class='muted' style='margin-top:5px'>{core.esc(item['details'])}</div></td>"
        f"<td>{item['score']:.0f}</td>"
        "</tr>"
        for item in PILOT_OPPORTUNITIES
    )

    body = f"""
    <main class='wrap' style='padding:28px 0 48px'>
      <div style='display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap'>
        <div><h1 style='margin-bottom:4px'>فحص الفرص التجريبي</h1>
        <p class='muted'>نتائج واقعية من فحص عام بتاريخ {SCAN_DATE} لاختبار مسار الفرصة → الإسناد → واتساب.</p></div>
        <a class='btn btn-muted' href='/admin/company'>العودة إلى مركز التحكم</a>
      </div>
      <div class='alert' style='background:#fff7ed;color:#9a3412;border:1px solid #fed7aa;margin-top:18px'>
        <strong>مهم:</strong> هذا فحص تجريبي يدوي وليس الرادار الآلي النهائي. أي عرض أو جهة يجب التحقق منها قبل التواصل أو الالتزام التجاري.
      </div>
      <section class='card' style='padding:22px;margin-bottom:18px'>
        <div class='table-wrap'><table><thead><tr><th>الأولوية</th><th>المصدر</th><th>الفرصة</th><th>الدرجة</th></tr></thead><tbody>{rows}</tbody></table></div>
      </section>
      <form method='post' action='/admin/company/pilot-scan' onsubmit="return confirm('إضافة نتائج الفحص التجريبي إلى قائمة الفرص؟');">
        <button class='btn btn-blue' type='submit'>إضافة هذه الفرص إلى مركز التحكم</button>
      </form>
    </main>
    """
    return HTMLResponse(core.page_shell("فحص الفرص التجريبي", body, admin=True))


@core.app.post("/admin/company/pilot-scan")
def pilot_scan_run(request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect
    run_pilot_scan(db)
    return RedirectResponse("/admin/company", status_code=303)


def _find_company_route():
    for route in core.app.routes:
        if isinstance(route, APIRoute) and route.path == "/admin/company" and "GET" in route.methods:
            return route
    return None


_company_route = _find_company_route()
if _company_route is not None:
    _original_dashboard = _company_route.dependant.call

    def _dashboard_with_pilot_scan(request: Request, db: Session = Depends(core.get_db)):
        response = _original_dashboard(request, db)
        if not isinstance(response, HTMLResponse):
            return response
        html = response.body.decode("utf-8", errors="replace")
        panel = f"""
        <section class='card' style='padding:18px 22px;margin-bottom:18px;background:#f8faff'>
          <div style='display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap'>
            <div><strong>فحص الفرص التجريبي</strong><div class='muted'>جاهز بـ {len(PILOT_OPPORTUNITIES)} فرص واقعية لاختبار النظام قبل تشغيل الرادارات الآلية.</div></div>
            <a class='btn btn-blue' href='/admin/company/pilot-scan'>عرض وتشغيل الفحص</a>
          </div>
        </section>
        """
        marker = "<section class='card' style='padding:22px;margin-bottom:18px'>\n        <h2>Voucher & CRM</h2>"
        if marker in html:
            html = html.replace(marker, panel + marker, 1)
        else:
            html = html.replace("</main>", panel + "</main>", 1)
        response.body = html.encode("utf-8")
        response.headers["content-length"] = str(len(response.body))
        return response

    _company_route.endpoint = _dashboard_with_pilot_scan
    _company_route.dependant.call = _dashboard_with_pilot_scan


def main() -> None:
    with core.SessionLocal() as db:
        created, skipped = run_pilot_scan(db)
    print(f"Pakgat pilot scan loaded: created={created}, skipped={skipped}")


if __name__ == "__main__":
    main()
