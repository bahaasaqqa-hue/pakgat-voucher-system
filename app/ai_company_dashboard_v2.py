"""Pakgat AI Company V2 visual/control experience.

This module is intentionally imported LAST. It keeps the existing working data
and routes, but replaces the CEO dashboard and systems map with the approved
Pakgat AI Control Center concept: compact executive dashboard, Arabic sidebar,
clear decision queue, operational cards and no invented metrics.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.routing import APIRoute
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.responses import Response

from app import application as core
from app import ai_company
from app import ai_company_sources
from app.ai_company_governance import CompanyApproval, generate_ceo_brief
from app.ai_company_hunter import CompanyLead
from app.ai_company_store_ops import StoreOpsIssue
from app.salla_data import SallaOrderSnapshot, SallaOrderItemSnapshot


SAUDI_TZ = timezone(timedelta(hours=3))


NAV_ITEMS = [
    ("الرئيسية", "/admin/company", "⌂"),
    ("الملخص التنفيذي", "/admin/company/brief", "▣"),
    ("الطلبات", "/admin/company/salla", "▤"),
    ("الزيارات", "/admin/company/visits", "◉"),
    ("الفرص الجديدة", "/admin/company/opportunities", "✦"),
    ("التحليلات", "/admin/company/analytics", "▥"),
    ("السوق والمنافسون", "/admin/company/competitors", "◎"),
    ("المنتجات والأسعار", "/admin/company/products", "◇"),
    ("الشركاء والتجار", "/admin/company/hunter", "♟"),
    ("السوشيال ميديا", "/admin/company/social", "◈"),
    ("SEO و Google", "/admin/company/seo", "⌕"),
    ("عمليات المتجر", "/admin/company/store-ops", "▦"),
    ("القسائم ودورة العميل", "/admin/company/crm", "◆"),
    ("التقنية والأمان", "/admin/company/technology", "⬡"),
    ("أنظمة الشركة", "/admin/company/systems", "▧"),
    ("ما هي شركة بكجات الذكية؟", "/admin/company/about", "?"),
]


V2_CSS = r"""
:root{--pak:#0d47d9;--pak2:#052c9e;--ink:#10233f;--muted:#71809b;--line:#dce6f7;--soft:#f6f9ff;--ok:#07965c;--warn:#ee8b12;--bad:#d73535}
body{background:#f5f8ff!important;color:var(--ink);font-family:Arial,Tahoma,sans-serif!important}
.ai-layout{min-height:100vh;display:grid;grid-template-columns:230px minmax(0,1fr);direction:ltr}
.ai-sidebar{background:linear-gradient(180deg,#0e4ee7 0%,#072f9f 100%);color:#fff;padding:18px 12px;position:sticky;top:0;height:100vh;overflow:auto;direction:rtl;z-index:5;box-shadow:8px 0 28px rgba(9,45,145,.12)}
.ai-logo{padding:9px 10px 18px;border-bottom:1px solid rgba(255,255,255,.18);margin-bottom:12px}.ai-logo strong{display:block;font-size:24px;letter-spacing:.2px}.ai-logo span{font-size:12px;opacity:.78}
.ai-nav{display:grid;gap:5px}.ai-nav a{display:flex;align-items:center;gap:10px;color:#fff;padding:10px 12px;border-radius:10px;font-size:14px;font-weight:800;opacity:.93}.ai-nav a:hover,.ai-nav a.active{background:rgba(255,255,255,.16);box-shadow:inset 0 0 0 1px rgba(255,255,255,.14);opacity:1}.ai-nav i{font-style:normal;width:18px;text-align:center}
.ai-sidebar-foot{margin-top:18px;border-top:1px solid rgba(255,255,255,.18);padding:16px 10px 8px;font-size:12px;opacity:.88}
.ai-workspace{direction:rtl;min-width:0}.ai-top{height:72px;background:#fff;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 22px;position:sticky;top:0;z-index:4}.ai-top-title{font-size:20px;font-weight:900;color:#0b2d75}.ai-top-actions{display:flex;align-items:center;gap:9px;flex-wrap:wrap}.ai-pill{border:1px solid var(--line);background:#fff;padding:8px 11px;border-radius:10px;font-size:12px;font-weight:800;color:#39506e}.ai-live{color:var(--ok);background:#ecfbf4}.ai-run{background:linear-gradient(135deg,#174ee9,#0638c4);color:#fff;border:0;border-radius:11px;padding:11px 17px;font-weight:900;cursor:pointer;box-shadow:0 7px 18px rgba(13,71,217,.22)}
.ai-workspace .wrap{width:100%!important;max-width:none!important;padding:20px 22px!important;margin:0!important}.topbar{display:none!important}
.ai-dashboard{display:grid;gap:14px}.ai-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.ai-kpi{background:#fff;border:1px solid var(--line);border-radius:15px;padding:17px;min-height:118px;box-shadow:0 8px 26px rgba(27,54,124,.06);position:relative}.ai-kpi .label{color:#405274;font-weight:800;font-size:14px}.ai-kpi .value{font-size:34px;font-weight:950;color:#082d79;margin-top:12px;line-height:1}.ai-kpi .sub{margin-top:8px;font-size:12px;color:var(--muted)}.ai-kpi.clickable:hover{border-color:#9eb9f4;transform:translateY(-1px)}
.ai-two{display:grid;grid-template-columns:1.05fr 1fr;gap:12px}.ai-four{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.ai-three{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.ai-panel{background:#fff;border:1px solid var(--line);border-radius:15px;padding:17px;box-shadow:0 8px 26px rgba(27,54,124,.055);min-width:0}.ai-panel h2{font-size:17px;margin:0 0 12px;color:#0e347e}.ai-panel-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:12px}.ai-panel-head h2{margin:0}.ai-link{font-size:12px;color:var(--pak);font-weight:900}.ai-list{display:grid;gap:9px}.ai-list-item{display:flex;gap:9px;align-items:flex-start;font-size:13px;line-height:1.6}.ai-dot{width:8px;height:8px;border-radius:50%;background:var(--pak);margin-top:7px;flex:0 0 auto}.ai-stat-row{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:8px 0;border-bottom:1px solid #edf2fb;font-size:13px}.ai-stat-row:last-child{border-bottom:0}.ai-number{font-weight:950;color:#0d3b99}.ai-empty{padding:13px;border:1px dashed #d6e1f4;border-radius:10px;color:var(--muted);font-size:13px;text-align:center;background:#fbfdff}.ai-status{display:inline-flex;align-items:center;border-radius:999px;padding:5px 9px;font-size:11px;font-weight:900}.ai-status.ok{background:#e9f9f1;color:#087a4d}.ai-status.pending{background:#fff5df;color:#a76500}.ai-status.bad{background:#ffeded;color:#b22424}.ai-approval{display:grid;grid-template-columns:1fr auto;gap:10px;padding:10px 0;border-bottom:1px solid #edf2fb}.ai-approval:last-child{border-bottom:0}.ai-approval-title{font-size:13px;font-weight:800}.ai-approval-meta{font-size:11px;color:var(--muted);margin-top:4px}.ai-approval-actions{display:flex;gap:6px;align-items:center}.ai-small-btn{border:0;border-radius:8px;padding:7px 10px;font-size:11px;font-weight:900;cursor:pointer}.ai-small-btn.primary{background:var(--pak);color:#fff}.ai-small-btn.ghost{background:#edf3ff;color:#1f4fc2}.ai-card-icon{width:36px;height:36px;border-radius:10px;background:#eaf1ff;display:grid;place-items:center;color:#174ed0;font-size:18px;font-weight:900;margin-bottom:10px}.ai-big{font-size:25px;font-weight:950;color:#0c3da5}.ai-note{font-size:12px;color:var(--muted);line-height:1.55;margin-top:6px}.ai-map{display:grid;grid-template-columns:repeat(8,minmax(0,1fr));gap:8px}.ai-map a{border:1px solid var(--line);background:#fff;border-radius:10px;padding:10px 7px;text-align:center;font-size:11px;font-weight:900;color:#153e98}.ai-map a:hover{background:#eef4ff}.ai-section-title{font-size:13px;color:#51617d;font-weight:900;margin:2px 0 -4px}.ai-wait{font-size:22px!important;line-height:1.15!important}.ai-about-hero{background:linear-gradient(135deg,#fafdff,#edf4ff);border:1px solid #d7e4fb;border-radius:20px;padding:28px;display:grid;grid-template-columns:1.25fr .75fr;gap:22px;align-items:center}.ai-about-hero h1{font-size:38px;margin:0 0 8px;color:#0a3caf}.ai-about-hero p{line-height:1.9;color:#334a70}.ai-about-badge{padding:22px;border-radius:18px;background:linear-gradient(135deg,#0c4ee8,#052f9e);color:#fff;text-align:center;font-size:28px;font-weight:950}.ai-flow{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;align-items:center}.ai-flow>div{background:#fff;border:1px solid var(--line);border-radius:13px;padding:15px;text-align:center;font-weight:900;color:#17469e}.ai-flow .arrow{border:0;background:transparent;font-size:24px;padding:0}.ai-simple-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.ai-info{background:#fff;border:1px solid var(--line);border-radius:14px;padding:16px}.ai-info h3{margin:0 0 7px;color:#103d9d}.ai-info p{margin:0;color:var(--muted);font-size:13px;line-height:1.7}
@media(max-width:1100px){.ai-four{grid-template-columns:repeat(2,1fr)}.ai-three{grid-template-columns:1fr 1fr}.ai-map{grid-template-columns:repeat(4,1fr)}}
@media(max-width:850px){.ai-layout{grid-template-columns:1fr}.ai-sidebar{position:relative;height:auto}.ai-nav{grid-template-columns:repeat(2,1fr)}.ai-workspace{min-width:0}.ai-top{position:relative;height:auto}.ai-kpis,.ai-two,.ai-four,.ai-three,.ai-simple-grid,.ai-about-hero{grid-template-columns:1fr}.ai-map{grid-template-columns:repeat(2,1fr)}.ai-flow{grid-template-columns:1fr}.ai-flow .arrow{transform:rotate(90deg)}.ai-workspace .wrap{padding:14px!important}}
"""


def _admin_redirect(request: Request):
    try:
        core.require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)
    return None


def _find_route(path: str, method: str = "GET"):
    for route in core.app.routes:
        if isinstance(route, APIRoute) and route.path == path and method in route.methods:
            return route
    return None


def _count(db: Session, model, *conds) -> int:
    stmt = select(func.count(model.id))
    if conds:
        stmt = stmt.where(*conds)
    return int(db.scalar(stmt) or 0)


def _source_state(db: Session, source: str) -> str:
    ai_company_sources.refresh_source_inventory(db)
    row = db.scalar(select(ai_company_sources.CompanySourceStatus).where(ai_company_sources.CompanySourceStatus.source == source))
    return row.status if row else "Needs Integration"


def _status_ar(value: str) -> str:
    return {
        "Connected": "متصل",
        "Readable": "قابل للقراءة",
        "Writable": "قابل للكتابة",
        "Needs Integration": "بانتظار الربط",
    }.get(value, value)


def _format_score(value) -> str:
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return str(value)


def _nav_html(path: str) -> str:
    links = []
    for label, href, icon in NAV_ITEMS:
        active = path == href or (href != "/admin/company" and path.startswith(href))
        links.append(f"<a class='{'active' if active else ''}' href='{href}'><i>{icon}</i><span>{core.esc(label)}</span></a>")
    return "".join(links)


def _layout_wrap(html: str, path: str) -> str:
    if "data-pakgat-ai-v2='1'" in html:
        return html
    # Remove the legacy voucher header from AI Company pages only.
    html = re.sub(r"<header class='topbar'>.*?</header>", "", html, count=1, flags=re.DOTALL)
    now = datetime.now(SAUDI_TZ)
    back_link = "<a class='ai-pill' href='/admin'>← رجوع إلى لوحة الإدارة</a>" if path.rstrip("/") == "/admin/company" else ""
    top = f"""
    <div class='ai-layout' data-pakgat-ai-v2='1'>
      <aside class='ai-sidebar'>
        <div class='ai-logo'><strong>بكجات AI</strong><span>شركة بكجات الذكية · مركز التحكم</span></div>
        <nav class='ai-nav'>{_nav_html(path)}</nav>
        <div class='ai-sidebar-foot'>PA · Pakgat AI<br>مدير الشركة الذكي</div>
      </aside>
      <section class='ai-workspace'>
        <div class='ai-top'>
          <div class='ai-top-title'>Pakgat AI Control Center</div>
          <div class='ai-top-actions'>
            {back_link}
            <span class='ai-pill ai-live'>● مباشر</span>
            <span class='ai-pill'>⌖ السعودية</span>
            <span class='ai-pill'>{now.strftime('%Y-%m-%d · %H:%M')}</span>
            <form method='post' action='/admin/company/run-company' style='margin:0'><button class='ai-run' type='submit'>🚀 شغّل الشركة</button></form>
          </div>
        </div>
    """
    close = "</section></div>"
    html = html.replace("<body>", "<body>" + top, 1)
    html = html.replace("</body>", close + "</body>", 1)
    html = html.replace("</head>", f"<style>{V2_CSS}</style></head>", 1)
    return html


def _kpi(label: str, value: str, sub: str, href: str | None = None, wait: bool = False) -> str:
    tag1, tag2 = (f"<a href='{href}'", "</a>") if href else ("<section", "</section>")
    cls = "ai-kpi clickable" if href else "ai-kpi"
    vcls = "value ai-wait" if wait else "value"
    return f"{tag1} class='{cls}'><div class='label'>{core.esc(label)}</div><div class='{vcls}'>{core.esc(value)}</div><div class='sub'>{core.esc(sub)}</div>{tag2}"


def company_dashboard_v2(request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect

    snapshot = ai_company.collect_company_snapshot(db)
    orders = _count(db, SallaOrderSnapshot)
    product_lines = _count(db, SallaOrderItemSnapshot)
    new_opps = _count(db, ai_company.CompanyOpportunity, ai_company.CompanyOpportunity.status == "new")
    pending_approvals = _count(db, CompanyApproval, CompanyApproval.status == "pending")
    open_alerts = _count(db, ai_company.CompanyAlert, ai_company.CompanyAlert.status == "open")
    store_issues = _count(db, StoreOpsIssue, StoreOpsIssue.status == "open")
    open_tasks = _count(db, ai_company.CompanyTask, ai_company.CompanyTask.status == "open")
    leads_found = _count(db, CompanyLead)
    leads_qualified = _count(db, CompanyLead, CompanyLead.status == "qualified")
    leads_contacted = _count(db, CompanyLead, CompanyLead.status == "contacted")
    leads_negotiating = _count(db, CompanyLead, CompanyLead.status == "negotiating")
    leads_live = _count(db, CompanyLead, CompanyLead.status == "live")
    supplier_leads = _count(db, CompanyLead, CompanyLead.lead_type == "supplier")

    approvals = list(db.scalars(select(CompanyApproval).where(CompanyApproval.status == "pending").order_by(CompanyApproval.created_at.desc()).limit(3)).all())
    approval_html = "".join(
        f"""<div class='ai-approval'><div><div class='ai-approval-title'>{core.esc(a.title)}</div><div class='ai-approval-meta'>{core.esc(a.priority)} · {core.esc(a.source)} · {core.esc(a.approval_level)}</div></div><div class='ai-approval-actions'><form method='post' action='/admin/company/governance/{a.id}/approve' style='margin:0'><button class='ai-small-btn primary'>موافقة</button></form><a class='ai-small-btn ghost' href='/admin/company/governance'>مراجعة</a></div></div>"""
        for a in approvals
    ) or "<div class='ai-empty'>لا توجد قرارات بانتظار الموافقة.</div>"

    seo_state = _source_state(db, "Google Search Console")
    ga_state = _source_state(db, "Google Analytics")
    oauth_state = _source_state(db, "Salla OAuth / Merchant API")
    whats_state = _source_state(db, "WhatsLoop")
    salla_state = _source_state(db, "Salla Webhooks")
    connected = len([s for s in [whats_state, salla_state, _source_state(db, "Google Compute Engine"), _source_state(db, "PostgreSQL")] if s in {"Connected", "Readable", "Writable"}])

    brief_items = [
        f"صحة الشركة الحالية {_format_score(snapshot['overall_score'])}/100 والتقنية {_format_score(snapshot['technology_score'])}/100.",
        f"{new_opps} فرص جديدة · {pending_approvals} قرارات تحتاج موافقة · {open_alerts} تنبيهات مفتوحة.",
        f"{orders} طلبات مرصودة من أحداث سلة · {snapshot['vouchers']['total']} قسائم إجمالية.",
        ("Google Analytics وSearch Console بانتظار الربط؛ لذلك لا نعرض أرقام زيارات أو SEO غير حقيقية." if ga_state == "Needs Integration" or seo_state == "Needs Integration" else "مصادر Google متصلة ويمكن استخدامها في التحليل."),
    ]
    brief_html = "".join(f"<div class='ai-list-item'><span class='ai-dot'></span><span>{core.esc(x)}</span></div>" for x in brief_items)

    body = f"""
    <main class='wrap'>
      <div class='ai-dashboard'>
        <div class='ai-kpis'>
          {_kpi('صحة الشركة', f"{_format_score(snapshot['overall_score'])}/100", f"التقنية {_format_score(snapshot['technology_score'])}/100")}
          {_kpi('الطلبات', str(orders), 'طلبات مرصودة من أحداث سلة', '/admin/company/salla')}
          {_kpi('الزيارات', 'بانتظار الربط' if ga_state == 'Needs Integration' else 'متصل', 'Google Analytics', '/admin/company/visits', ga_state == 'Needs Integration')}
          {_kpi('الفرص الجديدة', str(new_opps), 'اضغط لعرض الفرص والإسناد', '/admin/company/opportunities')}
        </div>

        <div class='ai-two'>
          <section class='ai-panel'>
            <div class='ai-panel-head'><h2>▣ الملخص التنفيذي</h2><a class='ai-link' href='/admin/company/brief'>عرض الملخص الكامل</a></div>
            <div class='ai-list'>{brief_html}</div>
          </section>
          <section class='ai-panel'>
            <div class='ai-panel-head'><h2>⚠ قرارات تحتاج موافقة</h2><a class='ai-link' href='/admin/company/governance'>{pending_approvals} بانتظار القرار</a></div>
            {approval_html}
          </section>
        </div>

        <div class='ai-four'>
          <a class='ai-panel' href='/admin/company/competitors'>
            <div class='ai-card-icon'>◎</div><h2>مراقبة السوق والمنافسين</h2>
            <div class='ai-big'>8 مصادر</div><div class='ai-note'>Cobone · وفرها · FOZ · CashUp · سيفور · SDC · نون · أمازون</div>
          </a>
          <a class='ai-panel' href='/admin/company/products'>
            <div class='ai-card-icon'>◇</div><h2>ذكاء المنتجات والتسعير</h2>
            <div class='ai-big'>{product_lines}</div><div class='ai-note'>بنود منتجات مرصودة من الطلبات. بيانات السوق الأوسع تدخل تدريجيًا مع الرادار.</div>
          </a>
          <a class='ai-panel' href='/admin/company/hunter'>
            <div class='ai-card-icon'>♟</div><h2>باحث التجار والموردين</h2>
            <div class='ai-stat-row'><span>تم العثور</span><span class='ai-number'>{leads_found}</span></div>
            <div class='ai-stat-row'><span>مؤهل</span><span class='ai-number'>{leads_qualified}</span></div>
            <div class='ai-stat-row'><span>تواصل / تفاوض / مباشر</span><span class='ai-number'>{leads_contacted} / {leads_negotiating} / {leads_live}</span></div>
          </a>
          <a class='ai-panel' href='/admin/company/crm'>
            <div class='ai-card-icon'>◆</div><h2>القسائم وواتساب</h2>
            <div class='ai-stat-row'><span>صادرة</span><span class='ai-number'>{snapshot['vouchers']['total']}</span></div>
            <div class='ai-stat-row'><span>نشطة</span><span class='ai-number'>{snapshot['vouchers']['active']}</span></div>
            <div class='ai-stat-row'><span>مستخدمة</span><span class='ai-number'>{snapshot['vouchers']['redeemed']}</span></div>
          </a>
        </div>

        <div class='ai-three'>
          <a class='ai-panel' href='/admin/company/seo'>
            <div class='ai-panel-head'><h2>⌕ SEO والكتالوج</h2><span class='ai-status {'ok' if seo_state != 'Needs Integration' else 'pending'}'>{_status_ar(seo_state)}</span></div>
            <div class='ai-stat-row'><span>Search Console</span><span>{_status_ar(seo_state)}</span></div>
            <div class='ai-stat-row'><span>Analytics</span><span>{_status_ar(ga_state)}</span></div>
            <div class='ai-stat-row'><span>مشاكل المتجر المفتوحة</span><span class='ai-number'>{store_issues}</span></div>
          </a>
          <a class='ai-panel' href='/admin/company/hunter'>
            <div class='ai-card-icon'>▦</div><h2>مراقبة التوريد</h2>
            <div class='ai-big'>{supplier_leads}</div><div class='ai-note'>موردون داخل Pipeline. أي تواصل أو شراء يبقى بانتظار الموافقة.</div>
          </a>
          <a class='ai-panel' href='/admin/company/technology'>
            <div class='ai-panel-head'><h2>▣ التقنية والأنظمة</h2><span class='ai-status ok'>مباشر</span></div>
            <div class='ai-stat-row'><span>Google VM + PostgreSQL</span><span class='ai-status ok'>يعمل</span></div>
            <div class='ai-stat-row'><span>Salla Webhooks</span><span class='ai-status {'ok' if salla_state=='Connected' else 'pending'}'>{_status_ar(salla_state)}</span></div>
            <div class='ai-stat-row'><span>WhatsLoop</span><span class='ai-status {'ok' if whats_state=='Connected' else 'pending'}'>{_status_ar(whats_state)}</span></div>
            <div class='ai-note'>{connected} مكونات تشغيل أساسية متاحة حاليًا · {open_tasks} مهام مفتوحة.</div>
          </a>
        </div>

        <section class='ai-panel'>
          <div class='ai-panel-head'><h2>خريطة الأقسام</h2><a class='ai-link' href='/admin/company/systems'>عرض الأنظمة الـ12</a></div>
          <div class='ai-map'>
            <a href='/admin/company/brief'>الإدارة التنفيذية</a><a href='/admin/company/analytics'>التحليلات</a><a href='/admin/company/competitors'>السوق والمنافسون</a><a href='/admin/company/products'>المنتجات والأسعار</a><a href='/admin/company/hunter'>الشركاء والتجار</a><a href='/admin/company/social'>السوشيال ميديا</a><a href='/admin/company/seo'>SEO وGoogle</a><a href='/admin/company/store-ops'>عمليات المتجر</a>
          </div>
        </section>
      </div>
    </main>
    """
    return HTMLResponse(core.page_shell("شركة بكجات الذكية — مركز التحكم", body, admin=True))


def systems_page_v2(request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect
    cards = [
        ("01", "القيادة التنفيذية", "يعمل", "/admin/company/brief", "الملخص التنفيذي، الأولويات، القرارات والموافقات."),
        ("02", "التقارير ومركز البيانات", "يعمل جزئيًا", "/admin/company/analytics", "بيانات سلة والقسائم والمصادر المتصلة؛ Google ينتظر الربط."),
        ("03", "السوق والمنافسون", "يعمل جزئيًا", "/admin/company/competitors", "قائمة المنافسين والرادار؛ الإدخال التلقائي الكامل إلى Data Hub قيد الاستكمال."),
        ("04", "المنتجات والأسعار", "يعمل جزئيًا", "/admin/company/products", "بيانات المنتجات المرصودة والفرص؛ نطاقات السوق والهامش قيد التوسعة."),
        ("05", "الشركاء والتجار", "يعمل", "/admin/company/hunter", "Merchant Hunter + Supplier Hunter + Pipeline وموافقات التواصل."),
        ("06", "النمو والمبيعات", "يعمل جزئيًا", "/admin/company/analytics", "Orders وRevenue وAOV؛ التحويل والاحتفاظ ينتظران مصادر إضافية."),
        ("07", "عمليات المتجر", "يعمل جزئيًا", "/admin/company/store-ops", "مشاكل العرض والكتالوج من البيانات المتصلة؛ القراءة الكاملة تنتظر Salla OAuth."),
        ("08", "SEO وGoogle", "بانتظار الربط", "/admin/company/seo", "Search Console وGA4 غير مربوطين بعد."),
        ("09", "البراند والاستوديو الإبداعي", "هيكل جاهز", "/admin/company/brand", "الهوية، صور المنتجات، البنرات والأصول الإبداعية."),
        ("10", "السوشيال وتوليد الطلب", "هيكل جاهز", "/admin/company/social", "المحتوى والحملات وربط الأداء بالمبيعات بعد ربط مصادره."),
        ("11", "القسائم ودورة العميل", "يعمل جزئيًا", "/admin/company/crm", "Voucher + QR + WhatsApp تعمل؛ Retention وRepeat Customer قيد الاستكمال."),
        ("12", "التقنية والأمان", "يعمل جزئيًا", "/admin/company/technology", "Google VM، PostgreSQL، المراقبة والنسخ الاحتياطي؛ Security Watch يتوسع تدريجيًا."),
    ]
    cards_html = "".join(
        f"<a class='ai-info' href='{url}'><span class='ai-status {'ok' if 'يعمل' in status and 'جزئي' not in status else 'pending'}'>{core.esc(num)} · {core.esc(status)}</span><h3>{core.esc(name)}</h3><p>{core.esc(detail)}</p><div class='ai-link' style='margin-top:10px'>دخول القسم ←</div></a>"
        for num, name, status, url, detail in cards
    )
    body = f"<main class='wrap'><div class='ai-panel-head'><div><h1 style='margin:0;color:#0b3a9c'>أنظمة شركة بكجات الذكية</h1><p class='muted'>الخريطة الواضحة للـ12 قسمًا — بدون مصطلحات تقنية مبهمة.</p></div><a class='ai-link' href='/admin/company'>العودة للرئيسية</a></div><div class='ai-simple-grid'>{cards_html}</div></main>"
    return HTMLResponse(core.page_shell("أنظمة شركة بكجات الذكية", body, admin=True))


def about_page(request: Request):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect
    inputs = ["سلة / Pakgat Store", "نظام القسائم", "WhatsLoop", "GitHub", "Google Analytics & Search Console", "Amazon.sa", "Noon", "Cobone", "Waffarha", "بيانات السوق والمنافسين"]
    input_html = "".join(f"<div class='ai-info'><h3>{core.esc(x)}</h3><p>مصدر بيانات أو تشغيل داخل منظومة بكجات.</p></div>" for x in inputs)
    outputs = ["ملخص تنفيذي يومي", "تنبيهات عن المنافسين والأسعار", "اقتراحات منتجات وفرص جديدة", "فرص تجار وموردين", "توصيات للعروض والخصومات", "مؤشرات أداء المتجر والقسائم", "مشاكل تقنية أو تشغيلية تحتاج قرار"]
    output_html = "".join(f"<div class='ai-info'><h3>{core.esc(x)}</h3><p>يظهر للإدارة عند توفر البيانات اللازمة، بدون اختراع أرقام.</p></div>" for x in outputs)
    body = f"""
    <main class='wrap'>
      <section class='ai-about-hero'><div><h1>شركة Pakgat AI</h1><p><strong>منظومة تشغيل ذكية مخصصة لـ Pakgat.com فقط.</strong><br>تجمع بيانات الشركة والسوق، تشغّل الأقسام، تكتشف المشاكل والفرص، ترتب الأولويات، ثم تجهز القرارات والتنفيذ للإدارة.</p><span class='ai-status ok'>العميل الوحيد: Pakgat.com</span></div><div class='ai-about-badge'>Pakgat<br>AI Company</div></section>
      <h2 style='color:#0c3ca4;margin-top:24px'>المدخلات</h2><div class='ai-simple-grid'>{input_html}</div>
      <h2 style='color:#0c3ca4;margin-top:24px'>كيف تعمل؟</h2><div class='ai-flow'><div>المدخلات</div><div class='arrow'>←</div><div>تحليل + اكتشاف + توصيات</div><div class='arrow'>←</div><div>لوحة القيادة والقرارات</div></div>
      <h2 style='color:#0c3ca4;margin-top:24px'>المخرجات اليومية</h2><div class='ai-simple-grid'>{output_html}</div>
      <h2 style='color:#0c3ca4;margin-top:24px'>خطة التنفيذ</h2><div class='ai-four'><div class='ai-info'><h3>1 · التأسيس</h3><p>الأقسام، الحوكمة والأولويات.</p></div><div class='ai-info'><h3>2 · Data Hub + Dashboard</h3><p>تجميع البيانات ومركز القيادة.</p></div><div class='ai-info'><h3>3 · التفعيل</h3><p>الرادارات، SEO، السوق، التجار والمنتجات.</p></div><div class='ai-info'><h3>4 · شبه ذاتي</h3><p>AUTO للأعمال الآمنة وموافقات واضحة للباقي.</p></div></div>
    </main>"""
    return HTMLResponse(core.page_shell("ما هي شركة بكجات الذكية؟", body, admin=True))


def simple_status_page(request: Request, title: str, intro: str, rows: list[tuple[str, str, str]], links: list[tuple[str, str]] | None = None):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect
    rows_html = "".join(f"<div class='ai-stat-row'><span>{core.esc(a)}</span><span class='ai-status {'ok' if c=='ok' else 'pending'}'>{core.esc(b)}</span></div>" for a,b,c in rows)
    links_html = "".join(f"<a class='btn btn-blue' href='{href}'>{core.esc(label)}</a> " for label,href in (links or []))
    body = f"<main class='wrap'><section class='ai-panel'><h1 style='margin-top:0;color:#0b3a9c'>{core.esc(title)}</h1><p class='muted' style='line-height:1.8'>{core.esc(intro)}</p>{rows_html}<div style='margin-top:16px'>{links_html}</div></section></main>"
    return HTMLResponse(core.page_shell(title, body, admin=True))


@core.app.get("/admin/company/visits", response_class=HTMLResponse)
def visits_page(request: Request, db: Session = Depends(core.get_db)):
    ga = _source_state(db, "Google Analytics")
    return simple_status_page(request, "الزيارات", "لن نعرض رقم زيارات تقديري. هذا القسم سيتغذى من GA4 عند ربطه.", [("Google Analytics", _status_ar(ga), "ok" if ga != "Needs Integration" else "pending"), ("الجلسات / المستخدمون / التحويل", "بانتظار GA4", "pending")], [("مصادر البيانات", "/admin/company/sources")])


@core.app.get("/admin/company/analytics", response_class=HTMLResponse)
def analytics_page(request: Request, db: Session = Depends(core.get_db)):
    orders = _count(db, SallaOrderSnapshot)
    return simple_status_page(request, "التحليلات والتقارير", "يجمع هذا القسم مؤشرات التشغيل من المصادر المتصلة فقط.", [("طلبات مرصودة", str(orders), "ok"), ("المبيعات والنمو", "بيانات جزئية متاحة", "ok"), ("التحويل والاحتفاظ", "بانتظار مصادر إضافية", "pending")], [("تفاصيل النمو والمنتجات", "/admin/company/growth"), ("مصادر البيانات", "/admin/company/sources")])


@core.app.get("/admin/company/products", response_class=HTMLResponse)
def products_page(request: Request, db: Session = Depends(core.get_db)):
    items = _count(db, SallaOrderItemSnapshot)
    return simple_status_page(request, "المنتجات والأسعار", "الهدف: Hot / Growing / Slow / Dormant، نطاق السوق، هامش بكجات وOpportunity Score. الآن نعرض فقط ما تدعمه البيانات المتصلة.", [("بنود منتجات مرصودة", str(items), "ok"), ("بيانات أسعار السوق", "قيد الربط مع الرادار", "pending"), ("هامش الربح الآلي", "يحتاج سعر شراء/توريد موثوق", "pending")], [("تفاصيل Growth & Products", "/admin/company/growth"), ("السوق والمنافسون", "/admin/company/competitors")])


@core.app.get("/admin/company/seo", response_class=HTMLResponse)
def seo_page(request: Request, db: Session = Depends(core.get_db)):
    sc = _source_state(db, "Google Search Console")
    ga = _source_state(db, "Google Analytics")
    return simple_status_page(request, "SEO وGoogle", "Keywords، Impressions، CTR، Positions، Indexing، Schema وGEO ستظهر هنا عند اتصال مصادر Google الفعلية.", [("Search Console", _status_ar(sc), "ok" if sc != "Needs Integration" else "pending"), ("Google Analytics", _status_ar(ga), "ok" if ga != "Needs Integration" else "pending"), ("SEO Watch", "لا يختلق بيانات قبل الربط", "ok")], [("مصادر البيانات", "/admin/company/sources")])


@core.app.get("/admin/company/social", response_class=HTMLResponse)
def social_page(request: Request):
    return simple_status_page(request, "السوشيال ميديا وتوليد الطلب", "القسم مخصص لاختيار العروض المناسبة، تجهيز Concepts/Captions/Reels/Stories وربط الأداء بالمتجر. لن نعتبره مفعّلًا قبل ربط قنوات القياس والنشر.", [("استراتيجية المحتوى", "الهيكل جاهز", "ok"), ("قياس الأداء", "بانتظار Analytics والقنوات", "pending"), ("النشر التلقائي", "يحتاج موافقة وربط", "pending")], [("ما هي شركة بكجات الذكية؟", "/admin/company/about")])


@core.app.get("/admin/company/brand", response_class=HTMLResponse)
def brand_page(request: Request):
    return simple_status_page(request, "البراند والاستوديو الإبداعي", "هوية Pakgat، صور المنتجات، البنرات، ونبرة المحتوى. الأتمتة الإبداعية تبقى تحت موافقة الإدارة قبل النشر.", [("هوية بكجات", "مرجع معتمد", "ok"), ("توليد الأصول", "جاهز للتفعيل تدريجيًا", "pending"), ("النشر", "موافقة مطلوبة", "pending")])


@core.app.get("/admin/company/crm", response_class=HTMLResponse)
def crm_page(request: Request, db: Session = Depends(core.get_db)):
    snap = ai_company.collect_company_snapshot(db)
    return simple_status_page(request, "القسائم ودورة العميل", "Order → Voucher → WhatsApp → Redemption → Merchant confirmation → Retention.", [("القسائم الصادرة", str(snap['vouchers']['total']), "ok"), ("القسائم المستخدمة", str(snap['vouchers']['redeemed']), "ok"), ("WhatsLoop", "جاهز" if snap['integrations']['whatsloop'] else "بانتظار الربط", "ok" if snap['integrations']['whatsloop'] else "pending"), ("Retention / Repeat Customer", "قيد الاستكمال", "pending")], [("تفاصيل سلة", "/admin/company/salla")])


@core.app.get("/admin/company/technology", response_class=HTMLResponse)
def technology_page(request: Request, db: Session = Depends(core.get_db)):
    salla = _source_state(db, "Salla Webhooks")
    whats = _source_state(db, "WhatsLoop")
    return simple_status_page(request, "التقنية والأمان", "حالة البنية التي تشغل Pakgat AI Company على Google، مع فصل ما يعمل فعليًا عما يزال قيد الربط.", [("Google Compute Engine", "يعمل", "ok"), ("PostgreSQL Data Hub", "يعمل", "ok"), ("Salla Webhooks", _status_ar(salla), "ok" if salla == "Connected" else "pending"), ("WhatsLoop", _status_ar(whats), "ok" if whats == "Connected" else "pending"), ("نسخ PostgreSQL اليومية", "مُجهّزة في النشر", "ok"), ("Security Watch المتقدم", "قيد الاستكمال", "pending")], [("مصادر البيانات", "/admin/company/sources")])


# Replace the two legacy entry pages with the approved V2 experience.
_dashboard_route = _find_route("/admin/company", "GET")
if _dashboard_route is not None:
    _dashboard_route.endpoint = company_dashboard_v2
    _dashboard_route.dependant.call = company_dashboard_v2

_systems_route = _find_route("/admin/company/systems", "GET")
if _systems_route is not None:
    _systems_route.endpoint = systems_page_v2
    _systems_route.dependant.call = systems_page_v2


@core.app.get("/admin/company/about", response_class=HTMLResponse)
def company_about(request: Request):
    return about_page(request)


# Final visual shell for every AI Company page, including older working detail
# pages such as Salla, opportunities, Hunter, Store Ops and governance.
@core.app.middleware("http")
async def pakgat_ai_v2_shell(request: Request, call_next):
    response = await call_next(request)
    if not request.url.path.startswith("/admin/company"):
        return response
    if "text/html" not in response.headers.get("content-type", "").lower():
        return response

    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk)
    html = b"".join(chunks).decode("utf-8", errors="replace")
    html = _layout_wrap(html, request.url.path)
    headers = dict(response.headers)
    headers.pop("content-length", None)
    return Response(content=html, status_code=response.status_code, headers=headers, media_type="text/html", background=response.background)
