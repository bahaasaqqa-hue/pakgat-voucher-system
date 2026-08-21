"""Pakgat AI Mission Control home experience for /admin/company.

Imported after ai_company_dashboard_v2. Replaces only the protected company home
route and decorates the existing V2 shell with a factual AI Core. No storefront
or Salla integration behavior is changed here.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.routing import APIRoute
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import ai_company
from app import ai_company_dashboard_v2 as v2
from app import ai_company_sources
from app import application as core
from app.ai_company_governance import CompanyApproval, CompanyDecision
from app.ai_company_mission_control import (
    approval_weight,
    freshness_label,
    opportunity_attention_score,
    resolve_command,
    sparkline_points,
)
from app.ai_company_readiness import summarize_system_statuses
from app.ai_company_run_company import run_connected_company_cycle
from app.salla_data import SallaOrderSnapshot


MISSION_CSS = r"""
:root{--mc-ink:#0f172a;--mc-bg:#f8fafc;--mc-line:#e2e8f0;--mc-blue:#2563eb;--mc-violet:#7c3aed;--mc-ok:#059669;--mc-muted:#64748b}
body{background:var(--mc-bg)!important}.ai-sidebar{background:linear-gradient(180deg,#0f172a 0%,#111c35 60%,#0b1223 100%)!important;box-shadow:10px 0 30px rgba(15,23,42,.14)!important}.ai-workspace{background:var(--mc-bg)}
.mc-ai-core{padding:16px 12px 18px;border-bottom:1px solid rgba(255,255,255,.12);margin-bottom:12px}.mc-core-head{display:flex;align-items:center;gap:11px}.mc-core-orb{position:relative;width:42px;height:42px;border-radius:14px;display:grid;place-items:center;background:radial-gradient(circle at 35% 30%,#60a5fa,#2563eb 45%,#6d28d9);box-shadow:0 0 0 1px rgba(255,255,255,.18),0 0 26px rgba(59,130,246,.42)}.mc-core-orb:before,.mc-core-orb:after{content:"";position:absolute;inset:-5px;border-radius:18px;border:1px solid rgba(96,165,250,.38);animation:aiCorePulse 2.8s ease-out infinite}.mc-core-orb:after{inset:-10px;animation-delay:1.1s;opacity:.45}.mc-core-orb svg{width:23px;height:23px;stroke:#fff;fill:none;stroke-width:1.8;position:relative;z-index:2}.mc-core-copy strong{display:block;font-size:19px;color:#fff}.mc-core-copy span{font-size:11px;color:#a8b7d6}.mc-core-state{display:flex;align-items:center;justify-content:space-between;margin-top:12px;padding:8px 10px;border:1px solid rgba(255,255,255,.1);border-radius:10px;background:rgba(255,255,255,.055);font-size:11px}.mc-core-state b{color:#86efac}.mc-core-state em{font-style:normal;color:#cbd5e1}@keyframes aiCorePulse{0%{transform:scale(.92);opacity:.8}70%{transform:scale(1.13);opacity:0}100%{transform:scale(1.13);opacity:0}}
.mc-operator{margin-top:18px;border-top:1px solid rgba(255,255,255,.12);padding:14px 9px 4px}.mc-operator-card{display:flex;gap:9px;align-items:center;padding:10px;border-radius:12px;background:rgba(255,255,255,.055);border:1px solid rgba(255,255,255,.08)}.mc-avatar{width:34px;height:34px;border-radius:10px;background:linear-gradient(135deg,#2563eb,#7c3aed);display:grid;place-items:center;font-weight:950;color:#fff}.mc-operator-card strong{font-size:12px;display:block;color:#fff}.mc-operator-card span{font-size:10px;color:#94a3b8}.mc-live-dot{width:7px;height:7px;border-radius:50%;background:#22c55e;box-shadow:0 0 10px rgba(34,197,94,.8);display:inline-block;margin-left:5px}
.mc-home{display:grid;gap:15px}.mc-command{position:relative;background:linear-gradient(135deg,#0f172a 0%,#172554 65%,#312e81 100%);border:1px solid rgba(99,102,241,.35);border-radius:22px;padding:20px;box-shadow:0 18px 40px rgba(15,23,42,.14);overflow:hidden;color:#fff}.mc-command:after{content:"";position:absolute;width:260px;height:260px;border-radius:50%;background:radial-gradient(circle,rgba(59,130,246,.18),transparent 70%);left:-80px;top:-120px}.mc-command-head{display:flex;align-items:center;justify-content:space-between;gap:14px;position:relative;z-index:1}.mc-command-title{display:flex;align-items:center;gap:10px}.mc-command-title .spark{width:34px;height:34px;border-radius:11px;display:grid;place-items:center;background:rgba(59,130,246,.16);border:1px solid rgba(96,165,250,.25);color:#bfdbfe;font-size:18px}.mc-command h1{font-size:18px;margin:0}.mc-command p{margin:3px 0 0;color:#a9b9d7;font-size:11px}.mc-command form{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;margin-top:14px;position:relative;z-index:1}.mc-command input{width:100%;border:1px solid rgba(148,163,184,.28);background:rgba(255,255,255,.08);color:#fff;padding:13px 15px;border-radius:12px;outline:none;font-size:13px;transition:all .18s ease}.mc-command input::placeholder{color:#94a3b8}.mc-command input:focus{border-color:#60a5fa;box-shadow:0 0 0 3px rgba(59,130,246,.14)}.mc-command button{border:0;border-radius:12px;padding:0 18px;background:linear-gradient(135deg,#3b82f6,#6366f1);color:#fff;font-weight:900;cursor:pointer;transition:transform .18s ease,box-shadow .18s ease}.mc-command button:hover{transform:translateY(-1px);box-shadow:0 8px 24px rgba(37,99,235,.28)}.mc-chips{display:flex;gap:7px;flex-wrap:wrap;margin-top:10px;position:relative;z-index:1}.mc-chip{font-size:10px;color:#cbd5e1;border:1px solid rgba(148,163,184,.18);border-radius:999px;padding:6px 9px;background:rgba(255,255,255,.05);transition:all .18s ease}.mc-chip:hover{background:rgba(59,130,246,.16);color:#fff}.mc-command-note{margin-top:9px;padding:8px 10px;border-radius:9px;font-size:11px;position:relative;z-index:1}.mc-command-note.ok{background:rgba(16,185,129,.13);color:#a7f3d0}.mc-command-note.warn{background:rgba(245,158,11,.13);color:#fde68a}
.mc-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.mc-card{background:#fff;border:1px solid var(--mc-line);border-radius:20px;box-shadow:0 5px 22px rgba(15,23,42,.045);transition:transform .18s ease,border-color .18s ease,box-shadow .18s ease}.mc-card:hover{transform:translateY(-1px);border-color:#cbd5e1;box-shadow:0 10px 28px rgba(15,23,42,.07)}.mc-kpi{padding:17px;min-height:128px}.mc-kpi-top{display:flex;align-items:center;justify-content:space-between;gap:8px}.mc-kpi-label{font-size:12px;font-weight:850;color:#475569}.mc-kpi-icon{width:31px;height:31px;border-radius:10px;display:grid;place-items:center;background:#eff6ff;color:#2563eb;font-weight:900}.mc-kpi-value{font-size:31px;font-weight:950;color:var(--mc-ink);margin-top:13px;line-height:1}.mc-kpi-sub{font-size:10px;color:#64748b;margin-top:8px}.mc-sparkline{margin-top:10px;height:30px}.mc-sparkline polyline{fill:none;stroke:#2563eb;stroke-width:2}.mc-sparkline .baseline{stroke:#e2e8f0;stroke-width:1}.mc-neutral-line{margin-top:12px;height:3px;border-radius:999px;background:linear-gradient(90deg,#dbeafe,#eef2ff)}
.mc-grid-2{display:grid;grid-template-columns:1.38fr .82fr;gap:12px}.mc-panel{padding:17px}.mc-panel-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:12px}.mc-panel-head h2{font-size:15px;margin:0;color:var(--mc-ink)}.mc-panel-head small{font-size:10px;color:#64748b}.mc-link{color:#2563eb;font-size:10px;font-weight:900}.mc-situation{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.mc-lane{border:1px solid #edf2f7;border-radius:14px;padding:12px;background:#fbfdff}.mc-lane-title{display:flex;align-items:center;gap:7px;font-size:11px;font-weight:900;color:#334155;margin-bottom:9px}.mc-lane-title i{width:8px;height:8px;border-radius:50%;background:#3b82f6;box-shadow:0 0 10px rgba(59,130,246,.38)}.mc-item{padding:8px 0;border-bottom:1px solid #edf2f7}.mc-item:last-child{border-bottom:0}.mc-item strong{display:block;font-size:11px;color:#1e293b;line-height:1.5}.mc-meta{display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-top:4px;font-size:9px;color:#94a3b8}.mc-source{color:#475569;font-weight:850}.mc-empty{font-size:10px;color:#94a3b8;padding:7px 0}
.mc-matrix{display:grid;gap:8px}.mc-matrix-row{display:grid;grid-template-columns:minmax(0,1.65fr) .55fr .7fr .55fr auto;gap:8px;align-items:center;padding:10px 0;border-bottom:1px solid #edf2f7}.mc-matrix-row:last-child{border-bottom:0}.mc-matrix-title strong{font-size:11px;color:#1e293b;display:block}.mc-matrix-title small{font-size:9px;color:#94a3b8}.mc-badge{display:inline-flex;align-items:center;justify-content:center;border-radius:999px;padding:5px 8px;font-size:9px;font-weight:900;white-space:nowrap}.mc-badge.p0,.mc-badge.ceo{background:#fef2f2;color:#b91c1c}.mc-badge.p1{background:#fff7ed;color:#c2410c}.mc-badge.p2,.mc-badge.approval{background:#eff6ff;color:#1d4ed8}.mc-badge.auto{background:#ecfdf5;color:#047857}.mc-score{font-size:13px;font-weight:950;color:#0f172a}.mc-actions{display:flex;gap:5px}.mc-btn{border:0;border-radius:8px;padding:6px 9px;font-size:9px;font-weight:900;cursor:pointer}.mc-btn.primary{background:#2563eb;color:#fff}.mc-btn.ghost{background:#eff6ff;color:#1d4ed8}.mc-progress{height:5px;border-radius:999px;background:#eef2f7;overflow:hidden;margin-top:5px}.mc-progress span{display:block;height:100%;border-radius:999px;background:linear-gradient(90deg,#3b82f6,#7c3aed)}
.mc-activity{display:grid;gap:0}.mc-activity-item{display:grid;grid-template-columns:12px minmax(0,1fr);gap:9px;padding:9px 0;border-bottom:1px solid #edf2f7}.mc-activity-item:last-child{border-bottom:0}.mc-activity-dot{width:8px;height:8px;border-radius:50%;background:#3b82f6;margin-top:4px;box-shadow:0 0 0 3px #eff6ff}.mc-activity-text strong{font-size:10px;color:#1e293b;display:block;line-height:1.5}.mc-activity-text span{font-size:9px;color:#94a3b8}.mc-trust{display:grid;grid-template-columns:repeat(3,1fr);gap:7px;margin-top:12px}.mc-trust-box{padding:9px;border-radius:11px;background:#f8fafc;border:1px solid #eef2f7}.mc-trust-box strong{display:block;font-size:15px;color:#0f172a}.mc-trust-box span{font-size:9px;color:#64748b}.mc-section-label{font-size:10px;font-weight:900;color:#64748b;text-transform:uppercase;letter-spacing:.8px;margin:1px 2px -5px}.mc-hidden-meta{display:none!important}
@media(max-width:1100px){.mc-kpis{grid-template-columns:repeat(2,1fr)}.mc-grid-2{grid-template-columns:1fr}.mc-situation{grid-template-columns:1fr 1fr}.mc-matrix-row{grid-template-columns:minmax(0,1.4fr) .55fr .65fr .5fr}}
@media(max-width:760px){.mc-kpis,.mc-situation{grid-template-columns:1fr}.mc-command-head{align-items:flex-start;flex-direction:column}.mc-command form{grid-template-columns:1fr}.mc-command button{padding:12px}.mc-matrix-row{grid-template-columns:1fr}.mc-actions{margin-top:4px}.mc-trust{grid-template-columns:1fr 1fr}.ai-sidebar{position:relative!important;height:auto!important}}
"""

_PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


def _admin_redirect(request: Request):
    return v2._admin_redirect(request)


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


def _badge_class(value: str) -> str:
    clean = str(value or "").strip().upper().replace("_", " ")
    if clean == "P0": return "p0"
    if clean == "P1": return "p1"
    if clean == "P2": return "p2"
    if "CEO" in clean: return "ceo"
    if clean == "AUTO": return "auto"
    return "approval"


def _safe_dt(value):
    if value is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _lane_html(title: str, items: list[dict]) -> str:
    parts = []
    for item in items[:3]:
        badge = ""
        if item.get("badge"):
            badge = f"<span class='mc-badge {core.esc(item.get('badge_class') or 'approval')}'>{core.esc(item.get('badge'))}</span>"
        parts.append(
            f"<div class='mc-item'><strong>{core.esc(item['title'])}</strong>"
            f"<div class='mc-meta'><span class='mc-source'>{core.esc(item.get('source') or 'Pakgat AI')}</span>"
            f"<span>·</span><span>{core.esc(item.get('freshness') or '—')}</span>{badge}</div></div>"
        )
    rows = "".join(parts) or "<div class='mc-empty'>لا توجد عناصر فعلية في هذه الفئة الآن.</div>"
    return f"<section class='mc-lane'><div class='mc-lane-title'><i></i>{core.esc(title)}</div>{rows}</section>"


def _activity_entry(ts, source: str, text: str) -> dict:
    return {"ts": _safe_dt(ts), "source": source, "text": text, "freshness": freshness_label(ts)}


@core.app.post("/admin/company/command")
async def mission_control_command(request: Request, db: Session = Depends(core.get_db)):
    """AI Command Bar: safe allow-listed navigation and internal AUTO-safe cycle only."""
    redirect = _admin_redirect(request)
    if redirect:
        return redirect
    form = await request.form()
    target, message = resolve_command(str(form.get("command") or ""))
    if target == "RUN_COMPANY":
        run_connected_company_cycle(db)
        core.log_event(db, "mission_control_command", details="target=RUN_COMPANY")
        return RedirectResponse("/admin/company?command=run", status_code=303)
    if target:
        core.log_event(db, "mission_control_command", details=f"target={target}")
        return RedirectResponse(target, status_code=303)
    core.log_event(db, "mission_control_command_unknown", details=f"message={message[:180]}")
    return RedirectResponse("/admin/company?command=unknown", status_code=303)


def mission_control_dashboard(request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect

    snapshot = ai_company.collect_company_snapshot(db)
    orders = _count(db, SallaOrderSnapshot)
    new_opps = _count(db, ai_company.CompanyOpportunity, ai_company.CompanyOpportunity.status == "new")

    source_summary = ai_company_sources.source_summary(db)
    source_rows = source_summary["rows"]
    source_counts = source_summary["counts"]
    usable_states = {"Connected", "Readable", "Writable"}
    usable_sources = sum(int(source_counts.get(key, 0)) for key in usable_states)
    source_map = {row.source: row.status for row in source_rows}
    core_ready = all(source_map.get(name) in usable_states for name in ("Google Compute Engine", "PostgreSQL"))
    core_status = "Operational" if core_ready else "Needs Attention"
    readiness = summarize_system_statuses(card[2] for card in v2.SYSTEM_CARDS)

    approvals = list(db.scalars(select(CompanyApproval).where(CompanyApproval.status == "pending").order_by(CompanyApproval.created_at.desc()).limit(8)).all())
    approvals = sorted(approvals, key=lambda row: approval_weight(row.priority, row.approval_level, row.created_at), reverse=True)

    alerts = list(db.scalars(select(ai_company.CompanyAlert).where(ai_company.CompanyAlert.status == "open").order_by(ai_company.CompanyAlert.created_at.desc()).limit(8)).all())
    alerts = sorted(alerts, key=lambda row: (_PRIORITY_RANK.get(str(row.severity).upper(), 9), -_safe_dt(row.created_at).timestamp()))

    opportunities = list(db.scalars(select(ai_company.CompanyOpportunity).where(ai_company.CompanyOpportunity.status.in_(["new", "review", "approved", "active"])).order_by(ai_company.CompanyOpportunity.updated_at.desc()).limit(12)).all())
    opportunity_rows = [(row, opportunity_attention_score(row.score, row.priority, row.status, row.created_at)) for row in opportunities]
    opportunity_rows.sort(key=lambda item: item[1], reverse=True)

    tasks = list(db.scalars(select(ai_company.CompanyTask).where(ai_company.CompanyTask.status == "open").order_by(ai_company.CompanyTask.created_at.desc()).limit(6)).all())
    decisions = list(db.scalars(select(CompanyDecision).order_by(CompanyDecision.created_at.desc()).limit(4)).all())
    health_history = list(db.scalars(select(ai_company.CompanyMetricSnapshot).where(ai_company.CompanyMetricSnapshot.metric_group == "company_health").order_by(ai_company.CompanyMetricSnapshot.created_at.desc()).limit(8)).all())
    health_history.reverse()
    spark = sparkline_points([row.score for row in health_history if row.score is not None])

    activity = []
    activity.extend(_activity_entry(row.created_at, row.source, f"تنبيه: {row.title}") for row in alerts[:4])
    activity.extend(_activity_entry(row.created_at, row.department, f"مهمة: {row.title}") for row in tasks[:4])
    activity.extend(_activity_entry(row.updated_at or row.created_at, row.source, f"فرصة: {row.title}") for row in opportunities[:4])
    activity.extend(_activity_entry(row.created_at, row.source, f"موافقة: {row.title}") for row in approvals[:4])
    activity.extend(_activity_entry(row.created_at, "Governance", f"قرار: {row.title} · {row.decision}") for row in decisions[:3])
    activity.extend(_activity_entry(row.created_at, "Health Monitor", f"لقطة صحة تشغيلية {v2._format_score(row.score)}/100") for row in health_history[-3:] if row.score is not None)
    activity.sort(key=lambda item: item["ts"], reverse=True)
    activity = activity[:8]

    changed_lane = [{"title": item["text"], "source": item["source"], "freshness": item["freshness"]} for item in activity[:3]]
    detected_lane = [{"title": row.title, "source": row.source, "freshness": freshness_label(row.created_at), "badge": row.severity, "badge_class": _badge_class(row.severity)} for row in alerts[:2]]
    for row, score in opportunity_rows[:1]:
        detected_lane.append({"title": row.title, "source": row.source, "freshness": freshness_label(row.updated_at or row.created_at), "badge": f"أولوية {score}", "badge_class": "approval"})
    decision_lane = [{"title": row.title, "source": row.source, "freshness": freshness_label(row.created_at), "badge": row.approval_level, "badge_class": _badge_class(row.approval_level)} for row in approvals[:3]]
    attention_lane = [{"title": row.title, "source": row.source, "freshness": freshness_label(row.created_at), "badge": row.severity, "badge_class": _badge_class(row.severity)} for row in alerts if str(row.severity).upper() in {"P0", "P1"}][:2]
    if len(attention_lane) < 3:
        for row in tasks:
            if str(row.priority).upper() in {"P0", "P1"}:
                attention_lane.append({"title": row.title, "source": row.department, "freshness": freshness_label(row.created_at), "badge": row.priority, "badge_class": _badge_class(row.priority)})
            if len(attention_lane) >= 3: break

    approval_html = "".join(f"""<div class='mc-matrix-row'><div class='mc-matrix-title'><strong>{core.esc(row.title)}</strong><small>{core.esc(row.source)} · {core.esc(row.action_type)}</small></div><span class='mc-badge {_badge_class(row.priority)}'>{core.esc(row.priority)}</span><span class='mc-badge {_badge_class(row.approval_level)}'>{core.esc(row.approval_level)}</span><div><span class='mc-score'>{approval_weight(row.priority, row.approval_level, row.created_at)}</span><div class='mc-kpi-sub'>Queue Score</div></div><div class='mc-actions'><form method='post' action='/admin/company/governance/{row.id}/approve' style='margin:0'><button class='mc-btn primary' type='submit'>موافقة</button></form><a class='mc-btn ghost' href='/admin/company/governance'>مراجعة</a></div></div>""" for row in approvals[:5]) or "<div class='mc-empty'>لا توجد قرارات بانتظار الموافقة.</div>"
    opportunity_html = "".join(f"""<div class='mc-matrix-row'><div class='mc-matrix-title'><strong>{core.esc(row.title)}</strong><small>{core.esc(row.source)} · {core.esc(freshness_label(row.updated_at or row.created_at))}</small><div class='mc-progress'><span style='width:{score}%'></span></div></div><span class='mc-badge {_badge_class(row.priority)}'>{core.esc(row.priority)}</span><span class='mc-badge approval'>{core.esc(row.status)}</span><div><span class='mc-score'>{score}</span><div class='mc-kpi-sub'>درجة أولوية</div></div><a class='mc-btn ghost' href='/admin/company/opportunities'>فتح</a></div>""" for row, score in opportunity_rows[:5]) or "<div class='mc-empty'>لا توجد فرص مفتوحة حاليًا.</div>"
    activity_html = "".join(f"<div class='mc-activity-item'><span class='mc-activity-dot'></span><div class='mc-activity-text'><strong>{core.esc(item['text'])}</strong><span>{core.esc(item['source'])} · {core.esc(item['freshness'])}</span></div></div>" for item in activity) or "<div class='mc-empty'>لا توجد أحداث داخلية مسجلة بعد.</div>"
    spark_html = f"<svg class='mc-sparkline' viewBox='0 0 116 30' preserveAspectRatio='none' aria-label='Operational health history'><line class='baseline' x1='0' y1='29' x2='116' y2='29'></line><polyline points='{core.esc(spark)}'></polyline></svg>" if spark else "<div class='mc-neutral-line' title='لا يوجد تاريخ كافٍ للرسم'></div>"

    command_state = request.query_params.get("command", "")
    command_note = ""
    if command_state == "run": command_note = "<div class='mc-command-note ok'>تم تشغيل دورة الشركة الآمنة وتحديث المؤشرات من المصادر المتصلة.</div>"
    elif command_state == "unknown": command_note = "<div class='mc-command-note warn'>الأمر غير مدعوم. جرّب: الفرص، القرارات، المصادر، التقنية، SEO، الأنظمة، الملخص أو شغّل الشركة.</div>"

    body = f"""
    <main class='wrap'><div class='mc-hidden-meta' data-mc-core-status='{core.esc(core_status)}' data-mc-source-count='{usable_sources}'></div><div class='mc-home'>
      <!-- AI Command Bar --><section class='mc-command'><div class='mc-command-head'><div class='mc-command-title'><span class='spark'>✦</span><div><h1>AI Command Bar</h1><p>أوامر داخلية آمنة فوق أنظمة Pakgat AI الحالية — بدون تنفيذ خارجي من النص الحر.</p></div></div><span class='mc-badge auto'>AUTO SAFE</span></div><form method='post' action='/admin/company/command'><input name='command' maxlength='180' autocomplete='off' placeholder='مثال: اعرض الفرص · القرارات · المصادر · شغّل الشركة'><button type='submit'>تنفيذ الأمر</button></form><div class='mc-chips'><a class='mc-chip' href='/admin/company/opportunities'>الفرص</a><a class='mc-chip' href='/admin/company/governance'>القرارات</a><a class='mc-chip' href='/admin/company/sources'>المصادر</a><a class='mc-chip' href='/admin/company/technology'>التقنية والأمان</a><a class='mc-chip' href='/admin/company/brief'>الملخص التنفيذي</a></div>{command_note}</section>
      <div class='mc-kpis'><section class='mc-card mc-kpi'><div class='mc-kpi-top'><span class='mc-kpi-label'>الصحة التشغيلية</span><span class='mc-kpi-icon'>◎</span></div><div class='mc-kpi-value'>{v2._format_score(snapshot['overall_score'])}/100</div><div class='mc-kpi-sub'>تشغيل وتقنية وقسائم فقط — ليست نسبة اكتمال الشركة</div>{spark_html}</section><a class='mc-card mc-kpi' href='/admin/company/systems'><div class='mc-kpi-top'><span class='mc-kpi-label'>اكتمال الأنظمة</span><span class='mc-kpi-icon'>▧</span></div><div class='mc-kpi-value'>{readiness['complete']}/{readiness['total']}</div><div class='mc-kpi-sub'>{readiness['partial']} تشغيل جزئي · {readiness['pending']} بانتظار استكمال</div><div class='mc-neutral-line'></div></a><a class='mc-card mc-kpi' href='/admin/company/opportunities'><div class='mc-kpi-top'><span class='mc-kpi-label'>الفرص الجديدة</span><span class='mc-kpi-icon'>✦</span></div><div class='mc-kpi-value'>{new_opps}</div><div class='mc-kpi-sub'>فرص فعلية مسجلة في Data Hub</div><div class='mc-neutral-line'></div></a><a class='mc-card mc-kpi' href='/admin/company/salla'><div class='mc-kpi-top'><span class='mc-kpi-label'>الطلبات</span><span class='mc-kpi-icon'>▤</span></div><div class='mc-kpi-value'>{orders}</div><div class='mc-kpi-sub'>طلبات مرصودة محليًا من أحداث سلة</div><div class='mc-neutral-line'></div></a></div>
      <div class='mc-section-label'>Mission Intelligence</div><div class='mc-grid-2'><!-- Situation Room --><section class='mc-card mc-panel'><div class='mc-panel-head'><div><h2>Situation Room</h2><small>ماذا تغيّر؟ ماذا اكتشف النظام؟ ماذا يحتاج قرارًا أو انتباهًا؟</small></div><a class='mc-link' href='/admin/company/brief'>الملخص التنفيذي</a></div><div class='mc-situation'>{_lane_html('ما الذي تغيّر؟', changed_lane)}{_lane_html('ما الذي اكتشفه النظام؟', detected_lane)}{_lane_html('ما الذي يحتاج قرارًا؟', decision_lane)}{_lane_html('ما الذي يحتاج انتباهًا؟', attention_lane)}</div></section><!-- Activity Rail --><aside class='mc-card mc-panel'><div class='mc-panel-head'><div><h2>Activity Rail</h2><small>أحدث أدلة النشاط المخزنة فعليًا</small></div></div><div class='mc-activity'>{activity_html}</div><div class='mc-trust'><div class='mc-trust-box'><strong>{usable_sources}</strong><span>مصادر قابلة للاستخدام</span></div><div class='mc-trust-box'><strong>{len(alerts)}</strong><span>تنبيهات مفتوحة معروضة</span></div><div class='mc-trust-box'><strong>{len(approvals)}</strong><span>قرارات معلقة</span></div></div></aside></div>
      <div class='mc-grid-2'><!-- Decision Matrix --><section class='mc-card mc-panel'><div class='mc-panel-head'><div><h2>Decision Matrix</h2><small>Queue Score = الأولوية + الحوكمة + عمر القرار، وليس Confidence</small></div><a class='mc-link' href='/admin/company/governance'>كل القرارات</a></div><div class='mc-matrix'>{approval_html}</div></section><!-- Opportunity Matrix --><section class='mc-card mc-panel'><div class='mc-panel-head'><div><h2>Opportunity Matrix</h2><small>Attention Score من البيانات المخزنة والأولوية والحالة</small></div><a class='mc-link' href='/admin/company/opportunities'>كل الفرص</a></div><div class='mc-matrix'>{opportunity_html}</div></section></div>
      <section class='mc-card mc-panel'><div class='mc-panel-head'><div><h2>Data Trust</h2><small>لا يوجد رقم زيارات أو نمو أو Confidence غير مدعوم بمصدر حقيقي.</small></div><a class='mc-link' href='/admin/company/sources'>Source Inventory</a></div><div class='mc-trust'><div class='mc-trust-box'><strong>{source_counts.get('Connected',0)}</strong><span>Connected</span></div><div class='mc-trust-box'><strong>{source_counts.get('Readable',0)}</strong><span>Readable</span></div><div class='mc-trust-box'><strong>{source_counts.get('Needs Integration',0)}</strong><span>Needs Integration</span></div></div></section>
    </div></main>"""
    return HTMLResponse(core.page_shell("Pakgat AI — Mission Control", body, admin=True))


# AI Core: decorate the existing V2 sidebar only on the Mission Control home.
_base_layout_wrap = v2._layout_wrap


def mission_control_layout_wrap(html: str, path: str) -> str:
    rendered = _base_layout_wrap(html, path)
    if path.rstrip("/") != "/admin/company":
        return rendered
    status_match = re.search(r"data-mc-core-status='([^']*)'", rendered)
    source_match = re.search(r"data-mc-source-count='([^']*)'", rendered)
    status = status_match.group(1) if status_match else "Operational"
    source_count = source_match.group(1) if source_match else "0"
    old_logo = "<div class='ai-logo'><strong>بكجات AI</strong><span>شركة بكجات الذكية · مركز التحكم</span></div>"
    new_logo = f"""<!-- AI Core --><div class='mc-ai-core'><div class='mc-core-head'><div class='mc-core-orb' aria-label='AI Core'><svg viewBox='0 0 24 24'><path d='M8 4a3 3 0 0 0-3 3v1a3 3 0 0 0-2 3v2a3 3 0 0 0 3 3h1a3 3 0 0 0 3 3h2V5h-1a3 3 0 0 0-3-1Z'/><path d='M16 4a3 3 0 0 1 3 3v1a3 3 0 0 1 2 3v2a3 3 0 0 1-3 3h-1a3 3 0 0 1-3 3h-2V5h1a3 3 0 0 1 3-1Z'/><path d='M8 9h2M14 9h2M8 14h2M14 14h2'/></svg></div><div class='mc-core-copy'><strong>Pakgat AI</strong><span>Mission Control</span></div></div><div class='mc-core-state'><span><i class='mc-live-dot'></i><b>{core.esc(status)}</b></span><em>{core.esc(source_count)} sources ready</em></div></div>"""
    rendered = rendered.replace(old_logo, new_logo, 1)
    old_foot = "<div class='ai-sidebar-foot'>PA · Pakgat AI<br>مدير الشركة الذكي</div>"
    new_foot = "<div class='mc-operator'><div class='mc-operator-card'><span class='mc-avatar'>PA</span><div><strong>مدير الشركة الذكي</strong><span><i class='mc-live-dot'></i> Mission Control Online</span></div></div></div>"
    rendered = rendered.replace(old_foot, new_foot, 1)
    return rendered.replace("</head>", f"<style>{MISSION_CSS}</style></head>", 1)


v2._layout_wrap = mission_control_layout_wrap


# Replace only the protected home route. Corporate bridge imported later may
# safely append its factual Corporate Benefits card to this response.
_home_route = _find_route("/admin/company", "GET")
if _home_route is not None:
    _home_route.endpoint = mission_control_dashboard
    _home_route.dependant.call = mission_control_dashboard
