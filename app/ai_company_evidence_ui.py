"""Additive opportunity evidence UI and WhatsApp message enrichment.

This module deliberately does not replace the operational opportunity renderer.
It decorates rendered opportunity/assignment responses with source evidence and
keeps the dispatch message enrichment isolated from the workflow renderer.
"""
from __future__ import annotations

import re

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from app import ai_company
from app import ai_company_dispatch as dispatch
from app import application as core
from app.ai_company_evidence import evidence_for, primary_evidence


_OPP_ID_RE = re.compile(r"<div class='opp-id'>OP-(\d+)</div>")


def _source_block(db: Session, opportunity_id: int, compact_mode: bool = False) -> str:
    rows = evidence_for(db, opportunity_id)
    if not rows:
        return ""
    primary = rows[0]
    links = " ".join(
        f"<a class='btn btn-muted' style='padding:8px 11px' target='_blank' rel='noopener' "
        f"href='{core.esc(e.source_url)}'>{core.esc(e.link_label)}</a>"
        for e in rows[:3]
    )
    image = ""
    if primary.image_url:
        image = (
            f"<img src='{core.esc(primary.image_url)}' alt='صورة الفرصة' loading='lazy' "
            "style='max-width:180px;max-height:130px;object-fit:contain;"
            "border:1px solid #e1e8f5;border-radius:12px;background:#fff'>"
        )
    note = ""
    if primary.note and not compact_mode:
        note = f"<div class='muted' style='margin-top:7px'>{core.esc(primary.note)}</div>"
    return (
        "<div class='opp-source-evidence' style='display:flex;gap:8px;align-items:center;"
        f"flex-wrap:wrap;margin-top:8px'>{image}{links}</div>{note}"
    )


def _find_route(path: str, method: str = "GET"):
    for route in core.app.routes:
        if isinstance(route, APIRoute) and route.path == path and method in route.methods:
            return route
    return None


def _inject_opportunity_evidence(html: str, db: Session) -> str:
    """Add source blocks to the new renderer without replacing its call signature."""
    opportunity_ids = list(dict.fromkeys(int(value) for value in _OPP_ID_RE.findall(html)))
    for opportunity_id in opportunity_ids:
        block = _source_block(db, opportunity_id, compact_mode=True)
        if not block:
            continue
        marker = f"<div class='opp-id'>OP-{opportunity_id:04d}</div>"
        html = html.replace(marker, marker + block, 1)
    return html


def _default_message_with_source(opportunity: ai_company.CompanyOpportunity) -> str:
    score = f"{opportunity.score:.1f}" if opportunity.score is not None else "—"
    details = (opportunity.details or "لا توجد تفاصيل إضافية.").strip()
    with core.SessionLocal() as db:
        evidence = primary_evidence(db, opportunity.id)
    source_line = f"\nرابط المصدر: {evidence.source_url}\n" if evidence else ""
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
        f"رقم الفرصة: OP-{opportunity.id:04d}\n"
        f"المصدر: {opportunity.source}\n"
        f"الأولوية: {opportunity.priority}\n"
        f"الفرصة: {opportunity.title}\n"
        f"تقييم الفرصة: {score}\n"
        f"{source_line}\n"
        f"التفاصيل:\n{details}\n\n"
        f"{action}\n\nشركة بكجات الذكية"
    )


# Message enrichment is intentionally independent from the opportunity renderer.
dispatch._default_message = _default_message_with_source


_assign_route = _find_route("/admin/company/opportunities/{opportunity_id}/assign", "GET")
if _assign_route is not None:
    _original_assign_call = _assign_route.dependant.call

    def _assign_with_evidence(
        opportunity_id: int,
        request: Request,
        db: Session = Depends(core.get_db),
    ):
        response = _original_assign_call(opportunity_id, request, db)
        if not isinstance(response, HTMLResponse):
            return response
        block = _source_block(db, opportunity_id)
        if block:
            html = response.body.decode("utf-8", errors="replace")
            marker = "<div class='alert' style='background:#fff7ed"
            html = html.replace(
                marker,
                "<div class='card' style='padding:14px;margin:14px 0'>"
                f"<strong>المصدر الأصلي</strong>{block}</div>" + marker,
                1,
            )
            response.body = html.encode("utf-8")
            response.headers["content-length"] = str(len(response.body))
        return response

    _assign_route.endpoint = _assign_with_evidence
    _assign_route.dependant.call = _assign_with_evidence


_opportunities_route = _find_route("/admin/company/opportunities", "GET")
if _opportunities_route is not None:
    _original_opportunities_call = _opportunities_route.dependant.call

    def _opportunities_with_evidence(
        request: Request,
        db: Session = Depends(core.get_db),
    ):
        response = _original_opportunities_call(request, db)
        if not isinstance(response, HTMLResponse):
            return response
        html = response.body.decode("utf-8", errors="replace")
        html = _inject_opportunity_evidence(html, db)
        response.body = html.encode("utf-8")
        response.headers["content-length"] = str(len(response.body))
        return response

    _opportunities_route.endpoint = _opportunities_with_evidence
    _opportunities_route.dependant.call = _opportunities_with_evidence
