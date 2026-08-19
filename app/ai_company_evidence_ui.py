"""Opportunity evidence UI and WhatsApp message enrichment.

Adds source links (and images when a scanner provides one) without changing the
core opportunity table.  The CEO/agent can reach the original offer/product
before acting on a recommendation.
"""

from __future__ import annotations

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import ai_company
from app import ai_company_dispatch as dispatch
from app import ai_company_opportunity_compact as compact
from app import application as core
from app.ai_company_evidence import evidence_for, primary_evidence, sync_known_evidence


def _source_block(db: Session, opportunity_id: int, compact_mode: bool = False) -> str:
    rows = evidence_for(db, opportunity_id)
    if not rows:
        return ""
    primary = rows[0]
    links = " ".join(
        f"<a class='btn btn-muted' style='padding:8px 11px' target='_blank' rel='noopener' href='{core.esc(e.source_url)}'>{core.esc(e.link_label)}</a>"
        for e in rows[:3]
    )
    image = ""
    if primary.image_url:
        image = (
            f"<img src='{core.esc(primary.image_url)}' alt='صورة الفرصة' loading='lazy' "
            "style='max-width:180px;max-height:130px;object-fit:contain;border:1px solid #e1e8f5;border-radius:12px;background:#fff'>"
        )
    note = ""
    if primary.note and not compact_mode:
        note = f"<div class='muted' style='margin-top:7px'>{core.esc(primary.note)}</div>"
    return f"<div style='display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:10px'>{image}{links}</div>{note}"


def _compact_dashboard_section(db: Session) -> str:
    compact.sync_focused_feed(db)
    sync_known_evidence(db)
    latest = list(
        db.scalars(
            select(ai_company.CompanyOpportunity)
            .where(ai_company.CompanyOpportunity.status == "new")
            .order_by(ai_company.CompanyOpportunity.created_at.desc(), ai_company.CompanyOpportunity.id.desc())
            .limit(4)
        ).all()
    )
    new_count = int(
        db.scalar(
            select(func.count(ai_company.CompanyOpportunity.id)).where(
                ai_company.CompanyOpportunity.status == "new"
            )
        )
        or 0
    )
    cards = "".join(
        f"""
        <article style='border:1px solid #e1e8f5;border-radius:14px;padding:15px;background:#f8faff'>
          <div style='display:flex;justify-content:space-between;gap:8px;align-items:center;flex-wrap:wrap'>
            <div>{compact._source_badge(o.source)} <strong style='margin-inline-start:6px'>{core.esc(o.priority)}</strong></div>
            <div style='font-weight:900'>{core.esc(f'{o.score:.0f}' if o.score is not None else '—')}</div>
          </div>
          <h3 style='margin:10px 0 6px;font-size:18px'>{core.esc(o.title)}</h3>
          <p class='muted' style='margin:0 0 8px;line-height:1.7'>{core.esc(compact._short(o.details or ''))}</p>
          {_source_block(db, o.id, compact_mode=True)}
          <div style='margin-top:10px'><a class='btn btn-blue' href='/admin/company/opportunities/{o.id}/assign'>فتح وإسناد</a></div>
        </article>
        """
        for o in latest
    )
    if not cards:
        cards = "<div class='muted' style='padding:12px 0'>لا توجد فرص جديدة الآن.</div>"
    return f"""
    <section class='card' style='padding:22px;margin-bottom:18px'>
      <div style='display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap'>
        <div><h2 style='margin-bottom:4px'>أحدث الفرص</h2><p class='muted' style='margin:0'>آخر 4 فرص جديدة فقط · مع رابط المصدر قبل الإسناد</p></div>
        <div style='display:flex;gap:8px;align-items:center;flex-wrap:wrap'>
          <span class='badge badge-active'>{new_count} جديدة</span>
          <a class='btn btn-blue' href='/admin/company/opportunities'>كل الفرص والإسناد</a>
        </div>
      </div>
      <div class='grid grid-mobile-1' style='grid-template-columns:repeat(2,1fr);margin-top:16px'>{cards}</div>
    </section>
    """


def _opportunity_rows(rows, allow_assign: bool, archive_button: bool = True) -> str:
    rendered = []
    for o in rows:
        action = ""
        if allow_assign:
            action += f"<a class='btn btn-blue' href='/admin/company/opportunities/{o.id}/assign'>إسناد</a> "
        if o.status in compact.EXECUTION_STATUSES:
            action += f"""
            <form method='post' action='/admin/company/opportunities/{o.id}/stage' style='display:inline-flex;gap:6px;align-items:center;flex-wrap:wrap'>
              <select class='select' name='stage' style='width:auto;padding:8px 10px'>
                <option value='contacted'>تم التواصل</option><option value='replied'>تم الرد</option>
                <option value='negotiating'>قيد التفاوض</option><option value='won'>ناجحة</option><option value='lost'>غير ناجحة</option>
              </select><button class='btn btn-muted' type='submit'>تحديث</button>
            </form> """
        if archive_button and o.status not in compact.ARCHIVE_STATUSES:
            action += f"""<form method='post' action='/admin/company/opportunities/{o.id}/archive' style='display:inline'>
              <button class='btn btn-muted' type='submit' onclick="return confirm('أرشفة هذه الفرصة؟');">أرشفة</button></form>"""
        source_links = _source_block(core.SessionLocal() if False else db_placeholder, o.id)  # replaced below
        rendered.append((o, action))

    # Build with one DB session for evidence lookup. This function is called from
    # an active request context but does not receive db, so use a short local session.
    html_rows = []
    with core.SessionLocal() as evidence_db:
        for o, action in rendered:
            source_links = _source_block(evidence_db, o.id)
            html_rows.append(
                "<tr>"
                f"<td>OP-{o.id:04d}</td><td>{core.esc(o.priority)}</td><td>{compact._source_badge(o.source)}</td>"
                f"<td><strong>{core.esc(o.title)}</strong>{source_links}"
                f"<details style='margin-top:7px'><summary class='muted' style='cursor:pointer'>عرض التفاصيل</summary>"
                f"<div style='margin-top:7px;line-height:1.7'>{core.esc(o.details or '—')}</div></details></td>"
                f"<td>{core.esc(f'{o.score:.0f}' if o.score is not None else '—')}</td>"
                f"<td>{core.esc(compact.STATUS_AR.get(o.status, o.status))}</td><td>{action or '—'}</td></tr>"
            )
    return "".join(html_rows)


# Replace compact generators. The route wrappers already installed by the compact
# module resolve these names from its module globals at request time.
compact._compact_dashboard_section = _compact_dashboard_section

# Rebuild row helper without changing the route itself.
def _rows_with_links(rows, allow_assign: bool, archive_button: bool = True) -> str:
    rendered = []
    with core.SessionLocal() as evidence_db:
        for o in rows:
            action = ""
            if allow_assign:
                action += f"<a class='btn btn-blue' href='/admin/company/opportunities/{o.id}/assign'>إسناد</a> "
            if o.status in compact.EXECUTION_STATUSES:
                action += f"""<form method='post' action='/admin/company/opportunities/{o.id}/stage' style='display:inline-flex;gap:6px;align-items:center;flex-wrap:wrap'>
                  <select class='select' name='stage' style='width:auto;padding:8px 10px'><option value='contacted'>تم التواصل</option><option value='replied'>تم الرد</option><option value='negotiating'>قيد التفاوض</option><option value='won'>ناجحة</option><option value='lost'>غير ناجحة</option></select><button class='btn btn-muted' type='submit'>تحديث</button></form> """
            if archive_button and o.status not in compact.ARCHIVE_STATUSES:
                action += f"""<form method='post' action='/admin/company/opportunities/{o.id}/archive' style='display:inline'><button class='btn btn-muted' type='submit' onclick="return confirm('أرشفة هذه الفرصة؟');">أرشفة</button></form>"""
            rendered.append(
                "<tr>"
                f"<td>OP-{o.id:04d}</td><td>{core.esc(o.priority)}</td><td>{compact._source_badge(o.source)}</td>"
                f"<td><strong>{core.esc(o.title)}</strong>{_source_block(evidence_db, o.id)}"
                f"<details style='margin-top:7px'><summary class='muted' style='cursor:pointer'>عرض التفاصيل</summary><div style='margin-top:7px;line-height:1.7'>{core.esc(o.details or '—')}</div></details></td>"
                f"<td>{core.esc(f'{o.score:.0f}' if o.score is not None else '—')}</td><td>{core.esc(compact.STATUS_AR.get(o.status, o.status))}</td><td>{action or '—'}</td></tr>"
            )
    return "".join(rendered)

compact._opportunity_rows = _rows_with_links


# Enrich the editable WhatsApp draft with the original source URL and tailor the
# action text to the kind of opportunity.
_original_default_message = dispatch._default_message


def _default_message_with_source(opportunity: ai_company.CompanyOpportunity) -> str:
    score = f"{opportunity.score:.1f}" if opportunity.score is not None else "—"
    details = (opportunity.details or "لا توجد تفاصيل إضافية.").strip()
    with core.SessionLocal() as db:
        evidence = primary_evidence(db, opportunity.id)
    source_line = ""
    if evidence:
        source_line = f"\nرابط المصدر: {evidence.source_url}\n"
    if opportunity.source.startswith(("نون", "أمازون")):
        action = (
            "المطلوب: افتح الرابط وتحقق من السعر والتوفر وإشارة الطلب الحالية. "
            "إذا كانت فرصة إعادة بيع مناسبة، احسب هامش بكجات وتكلفة الشراء والتوصيل قبل اعتمادها. "
            "لا تتواصل مع العلامة التجارية إلا إذا قررت الإدارة تحويلها إلى فرصة توريد مباشرة."
        )
    else:
        action = (
            "المطلوب: افتح رابط المصدر، راجع العرض والتاجر وشروطه الحالية، ثم قيّم إمكانية تقديم عرض مماثل أو أفضل على بكجات. "
            "أي تواصل خارجي يتم بعد اعتماد الإدارة."
        )
    return (
        "📌 فرصة جديدة من بكجات\n\n"
        f"رقم الفرصة: OP-{opportunity.id:04d}\nالمصدر: {opportunity.source}\nالأولوية: {opportunity.priority}\n"
        f"الفرصة: {opportunity.title}\nتقييم الفرصة: {score}\n{source_line}\nالتفاصيل:\n{details}\n\n{action}\n\nشركة بكجات الذكية"
    )

dispatch._default_message = _default_message_with_source


# Inject evidence into the assignment page itself so the CEO or agent can open
# the source before confirming WhatsApp dispatch.
_assign_route = None
for route in core.app.routes:
    if isinstance(route, APIRoute) and route.path == "/admin/company/opportunities/{opportunity_id}/assign" and "GET" in route.methods:
        _assign_route = route
        break

if _assign_route is not None:
    _original_assign_call = _assign_route.dependant.call

    def _assign_with_evidence(opportunity_id: int, request: Request, db: Session = Depends(core.get_db)):
        response = _original_assign_call(opportunity_id, request, db)
        if not isinstance(response, HTMLResponse):
            return response
        block = _source_block(db, opportunity_id)
        if block:
            html = response.body.decode("utf-8", errors="replace")
            marker = "<div class='alert' style='background:#fff7ed"
            html = html.replace(marker, f"<div class='card' style='padding:14px;margin:14px 0'><strong>المصدر الأصلي</strong>{block}</div>" + marker, 1)
            response.body = html.encode("utf-8")
            response.headers["content-length"] = str(len(response.body))
        return response

    _assign_route.endpoint = _assign_with_evidence
    _assign_route.dependant.call = _assign_with_evidence
