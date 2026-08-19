"""Pakgat AI Company V1 control center for Google Compute Engine.

This module keeps the AI Company control plane on the same GCE/Postgres stack as
Pakgat Voucher System. It adds a protected CEO dashboard plus a small central
Data Hub for alerts, tasks and KPI snapshots. No Render dependency is used.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import DateTime, Float, Integer, String, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app import application as core
from app.gce_entry import LocalPartnerProduct


class CompanyMetricSnapshot(core.Base):
    __tablename__ = "company_metric_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    metric_group: Mapped[str] = mapped_column(String(80), index=True)
    payload_json: Mapped[str] = mapped_column(String(5000))
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


class CompanyAlert(core.Base):
    __tablename__ = "company_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    severity: Mapped[str] = mapped_column(String(20), default="P2", index=True)
    source: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(255))
    details: Mapped[Optional[str]] = mapped_column(String(1500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class CompanyTask(core.Base):
    __tablename__ = "company_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    priority: Mapped[str] = mapped_column(String(20), default="P2", index=True)
    department: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


def _admin_redirect(request: Request):
    try:
        core.require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)
    return None


def _count(db: Session, model, *conditions) -> int:
    stmt = select(func.count(model.id))
    if conditions:
        stmt = stmt.where(*conditions)
    return int(db.scalar(stmt) or 0)


def collect_company_snapshot(db: Session) -> dict:
    vouchers_total = _count(db, core.Voucher)
    vouchers_active = _count(db, core.Voucher, core.Voucher.status == "active")
    vouchers_redeemed = _count(db, core.Voucher, core.Voucher.status == "redeemed")
    vouchers_expired = _count(db, core.Voucher, core.Voucher.status == "expired")

    whatsapp_failed = _count(
        db,
        core.AuditLog,
        core.AuditLog.action.in_([
            "whatsapp_failed",
            "merchant_whatsapp_failed",
            "redemption_whatsapp_failed",
            "merchant_redemption_whatsapp_failed",
        ]),
    )
    webhook_received = _count(db, core.AuditLog, core.AuditLog.action == "salla_webhook_received")
    webhook_rejected = _count(db, core.AuditLog, core.AuditLog.action == "salla_webhook_rejected")
    local_partners = _count(db, LocalPartnerProduct)
    oauth_rows = _count(db, core.SallaOAuthCredential)
    open_alerts = _count(db, CompanyAlert, CompanyAlert.status == "open")
    open_tasks = _count(db, CompanyTask, CompanyTask.status == "open")

    technology_score = 100.0
    if webhook_rejected:
        technology_score -= min(25.0, webhook_rejected * 2.0)
    if whatsapp_failed:
        technology_score -= min(25.0, whatsapp_failed * 2.0)
    if not core.WHATSLOOP_API_BASE_URL or not core.WHATSLOOP_API_TOKEN:
        technology_score -= 30.0
    technology_score = max(0.0, technology_score)

    voucher_score = 100.0
    if vouchers_total and vouchers_expired:
        voucher_score -= min(30.0, (vouchers_expired / vouchers_total) * 100.0)
    voucher_score = max(0.0, voucher_score)

    overall_score = round((technology_score + voucher_score) / 2.0, 1)

    return {
        "overall_score": overall_score,
        "technology_score": round(technology_score, 1),
        "voucher_score": round(voucher_score, 1),
        "vouchers": {
            "total": vouchers_total,
            "active": vouchers_active,
            "redeemed": vouchers_redeemed,
            "expired": vouchers_expired,
        },
        "integrations": {
            "whatsloop": bool(core.WHATSLOOP_API_BASE_URL and core.WHATSLOOP_API_TOKEN),
            "salla_oauth": bool(oauth_rows),
            "salla_webhooks_received": webhook_received,
            "salla_webhooks_rejected": webhook_rejected,
            "local_partner_products": local_partners,
        },
        "operations": {
            "whatsapp_failures": whatsapp_failed,
            "open_alerts": open_alerts,
            "open_tasks": open_tasks,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def save_snapshot(db: Session, payload: dict) -> CompanyMetricSnapshot:
    row = CompanyMetricSnapshot(
        metric_group="company_health",
        payload_json=json.dumps(payload, ensure_ascii=False),
        score=float(payload.get("overall_score") or 0),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def ensure_alert(db: Session, severity: str, source: str, title: str, details: str = "") -> None:
    existing = db.scalar(
        select(CompanyAlert).where(
            CompanyAlert.status == "open",
            CompanyAlert.source == source,
            CompanyAlert.title == title,
        )
    )
    if existing:
        existing.details = details[:1500] or existing.details
        db.commit()
        return
    db.add(
        CompanyAlert(
            severity=severity,
            source=source,
            title=title,
            details=details[:1500] or None,
            status="open",
        )
    )
    db.commit()


def evaluate_alerts(db: Session, snapshot: dict) -> None:
    integrations = snapshot["integrations"]
    operations = snapshot["operations"]

    if not integrations["whatsloop"]:
        ensure_alert(db, "P0", "WhatsLoop", "WhatsLoop configuration is missing")
    if operations["whatsapp_failures"] > 0:
        ensure_alert(
            db,
            "P1",
            "WhatsLoop",
            "WhatsApp delivery failures detected",
            f"failure_events={operations['whatsapp_failures']}",
        )
    if integrations["salla_webhooks_rejected"] > 0:
        ensure_alert(
            db,
            "P1",
            "Salla",
            "Rejected Salla webhook events detected",
            f"rejected={integrations['salla_webhooks_rejected']}",
        )


@core.app.get("/admin/company", response_class=HTMLResponse)
def company_dashboard(request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect

    snapshot = collect_company_snapshot(db)
    alerts = list(
        db.scalars(
            select(CompanyAlert)
            .where(CompanyAlert.status == "open")
            .order_by(CompanyAlert.created_at.desc())
            .limit(20)
        ).all()
    )
    tasks = list(
        db.scalars(
            select(CompanyTask)
            .where(CompanyTask.status == "open")
            .order_by(CompanyTask.created_at.desc())
            .limit(20)
        ).all()
    )

    def badge(ok: bool, yes: str = "جاهز", no: str = "يحتاج متابعة") -> str:
        cls = "badge-active" if ok else "badge-expired"
        label = yes if ok else no
        return f"<span class='badge {cls}'>{core.esc(label)}</span>"

    alert_rows = "".join(
        "<tr>"
        f"<td>{core.esc(a.severity)}</td><td>{core.esc(a.source)}</td>"
        f"<td>{core.esc(a.title)}</td><td>{core.esc(core.fmt_dt(a.created_at))}</td>"
        "</tr>"
        for a in alerts
    ) or "<tr><td colspan='4' class='muted'>لا توجد تنبيهات مفتوحة.</td></tr>"

    task_rows = "".join(
        "<tr>"
        f"<td>{core.esc(t.priority)}</td><td>{core.esc(t.department)}</td>"
        f"<td>{core.esc(t.title)}</td><td>{core.esc(t.status)}</td>"
        "</tr>"
        for t in tasks
    ) or "<tr><td colspan='4' class='muted'>لا توجد مهام مفتوحة.</td></tr>"

    body = f"""
    <main class='wrap' style='padding:28px 0 48px'>
      <div style='display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap'>
        <div><h1 style='margin-bottom:4px'>Pakgat AI Company — Control Center</h1>
        <p class='muted'>Google Cloud · Data Hub · CEO Dashboard · Monitoring</p></div>
        <form method='post' action='/admin/company/refresh'>
          <button class='btn btn-blue' type='submit'>تحديث لوحة القيادة</button>
        </form>
      </div>

      <div class='grid grid-mobile-1' style='grid-template-columns:repeat(4,1fr);margin:18px 0'>
        <section class='card' style='padding:20px'><div class='muted'>Company Health</div><div style='font-size:34px;font-weight:900'>{snapshot['overall_score']}/100</div></section>
        <section class='card' style='padding:20px'><div class='muted'>Technology</div><div style='font-size:34px;font-weight:900'>{snapshot['technology_score']}/100</div></section>
        <section class='card' style='padding:20px'><div class='muted'>Vouchers</div><div style='font-size:34px;font-weight:900'>{snapshot['vouchers']['total']}</div></section>
        <section class='card' style='padding:20px'><div class='muted'>Open Alerts</div><div style='font-size:34px;font-weight:900'>{snapshot['operations']['open_alerts']}</div></section>
      </div>

      <div class='grid grid-mobile-1' style='grid-template-columns:1fr 1fr;margin-bottom:18px'>
        <section class='card' style='padding:22px'>
          <h2>Voucher & CRM</h2>
          <table><tbody>
            <tr><th>Issued</th><td>{snapshot['vouchers']['total']}</td></tr>
            <tr><th>Active</th><td>{snapshot['vouchers']['active']}</td></tr>
            <tr><th>Redeemed</th><td>{snapshot['vouchers']['redeemed']}</td></tr>
            <tr><th>Expired</th><td>{snapshot['vouchers']['expired']}</td></tr>
          </tbody></table>
        </section>
        <section class='card' style='padding:22px'>
          <h2>Integrations</h2>
          <table><tbody>
            <tr><th>WhatsLoop</th><td>{badge(snapshot['integrations']['whatsloop'])}</td></tr>
            <tr><th>Salla Webhooks</th><td>{snapshot['integrations']['salla_webhooks_received']} received / {snapshot['integrations']['salla_webhooks_rejected']} rejected</td></tr>
            <tr><th>Salla OAuth</th><td>{badge(snapshot['integrations']['salla_oauth'], 'متصل', 'Local fallback')}</td></tr>
            <tr><th>Local Partner Products</th><td>{snapshot['integrations']['local_partner_products']}</td></tr>
          </tbody></table>
        </section>
      </div>

      <section class='card' style='padding:22px;margin-bottom:18px'>
        <h2>Critical Alerts</h2>
        <div class='table-wrap'><table><thead><tr><th>Priority</th><th>Source</th><th>Alert</th><th>Created</th></tr></thead><tbody>{alert_rows}</tbody></table></div>
      </section>

      <section class='card' style='padding:22px'>
        <h2>CEO Decisions / Tasks</h2>
        <div class='table-wrap'><table><thead><tr><th>Priority</th><th>Department</th><th>Task</th><th>Status</th></tr></thead><tbody>{task_rows}</tbody></table></div>
      </section>
    </main>
    """
    return HTMLResponse(core.page_shell("Pakgat AI Company", body, admin=True))


@core.app.post("/admin/company/refresh")
def company_refresh(request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect
    snapshot = collect_company_snapshot(db)
    evaluate_alerts(db, snapshot)
    save_snapshot(db, snapshot)
    core.log_event(db, "ai_company_refresh", details=f"health={snapshot['overall_score']}")
    return RedirectResponse("/admin/company", status_code=303)


@core.app.get("/company/health")
def company_health(db: Session = Depends(core.get_db)):
    snapshot = collect_company_snapshot(db)
    return {
        "ok": snapshot["overall_score"] >= 70,
        "service": "Pakgat AI Company",
        "hosting": "Google Compute Engine",
        "overall_score": snapshot["overall_score"],
        "technology_score": snapshot["technology_score"],
        "voucher_score": snapshot["voucher_score"],
    }
