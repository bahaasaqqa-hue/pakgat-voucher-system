"""Secure external agent reporting for Pakgat AI opportunities.

The agent receives a bearer-style, unguessable report URL after an admin-approved
WhatsLoop assignment. Only the SHA-256 hash is stored. Public report pages expose
only the assigned opportunity, while evidence files are served only to admins.
"""
from __future__ import annotations

import hashlib
import io
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from PIL import Image, UnidentifiedImageError
from sqlalchemy import DateTime, Integer, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app import ai_company
from app import application as core
from app.ai_company_dispatch import CompanyAgent, OpportunityDispatch


MAX_EVIDENCE_BYTES = 5 * 1024 * 1024
TOKEN_VALID_DAYS = 30
COMPLETION_ARCHIVE_HOURS = 48
REPORT_PUBLIC_BASE_URL = core.env(
    "AGENT_REPORT_PUBLIC_BASE_URL", "https://voucher.pakgat.com"
).rstrip("/")
EVIDENCE_ROOT = Path(
    core.env("OPPORTUNITY_EVIDENCE_DIR", "/var/lib/pakgat/opportunity-evidence")
)

REPORT_ACTIONS = {
    "contacted": "تم التواصل",
    "visited": "تمت الزيارة",
    "interested": "مهتم",
    "replied": "تم الرد",
    "negotiating": "قيد التفاوض",
    "follow_up": "متابعة لاحقًا",
    "won": "ناجحة",
    "lost": "غير ناجحة",
}
IN_PROGRESS_STATUSES = {
    "review",
    "approved",
    "active",
    "assigned",
    "contacted",
    "replied",
    "negotiating",
}
_ALLOWED_IMAGE_MIME_TO_FORMAT = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
}


class OpportunityReportLink(core.Base):
    __tablename__ = "opportunity_report_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dispatch_id: Mapped[int] = mapped_column(Integer, index=True)
    opportunity_id: Mapped[int] = mapped_column(Integer, index=True)
    agent_id: Mapped[int] = mapped_column(Integer, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


class OpportunityAgentReport(core.Base):
    __tablename__ = "opportunity_agent_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    opportunity_id: Mapped[int] = mapped_column(Integer, index=True)
    dispatch_id: Mapped[int] = mapped_column(Integer, index=True)
    agent_id: Mapped[int] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String(30), index=True)
    notes: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    follow_up_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence_filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    evidence_content_type: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _audit(db: Session, action: str, details: str) -> None:
    db.add(core.AuditLog(action=action, details=details[:500]))


def hash_report_token(raw_token: str) -> str:
    return hashlib.sha256(str(raw_token or "").encode("utf-8")).hexdigest()


def report_url(raw_token: str) -> str:
    return f"{REPORT_PUBLIC_BASE_URL}/agent/report/{raw_token}"


def append_report_link(message: str, url: str) -> str:
    base = str(message or "").strip()
    block = (
        "\n\n📝 تحديث نتيجة الفرصة\n"
        "بعد التواصل أو الزيارة افتح الرابط وسجّل الإجراء والملاحظات، ويمكنك رفع صورة إثبات اختيارية:\n"
        f"{url}"
    )
    # OpportunityDispatch.message is 4000 chars. Leave room for the secure block.
    max_base = max(0, 4000 - len(block) - 4)
    return base[:max_base].rstrip() + block


def map_agent_action(current_status: str, action: str) -> str:
    action = str(action or "").strip().lower()
    current = str(current_status or "").strip().lower()
    mapping = {
        "contacted": "contacted",
        "visited": "contacted",
        "interested": "replied",
        "replied": "replied",
        "negotiating": "negotiating",
        "won": "won",
        "lost": "lost",
    }
    if action == "follow_up":
        return current if current in IN_PROGRESS_STATUSES else "assigned"
    if action not in mapping:
        raise ValueError("Invalid agent report action")
    return mapping[action]


def revoke_opportunity_links(
    db: Session,
    opportunity_id: int,
    now: Optional[datetime] = None,
) -> None:
    current = now or _now()
    links = list(
        db.scalars(
            select(OpportunityReportLink).where(
                OpportunityReportLink.opportunity_id == int(opportunity_id),
                OpportunityReportLink.revoked_at.is_(None),
            )
        ).all()
    )
    for link in links:
        link.revoked_at = current


def create_report_capability(
    db: Session,
    dispatch_id: int,
    opportunity_id: int,
    agent_id: int,
    now: Optional[datetime] = None,
) -> tuple[OpportunityReportLink, str]:
    current = now or _now()
    # Reassignment invalidates older bearer links for the same opportunity.
    revoke_opportunity_links(db, opportunity_id, current)
    raw_token = secrets.token_urlsafe(32)
    link = OpportunityReportLink(
        dispatch_id=int(dispatch_id),
        opportunity_id=int(opportunity_id),
        agent_id=int(agent_id),
        token_hash=hash_report_token(raw_token),
        expires_at=current + timedelta(days=TOKEN_VALID_DAYS),
        created_at=current,
    )
    db.add(link)
    db.flush()
    _audit(
        db,
        "opportunity_report_link_created",
        f"opportunity=OP-{int(opportunity_id):04d}; dispatch={int(dispatch_id)}; agent={int(agent_id)}",
    )
    return link, raw_token


def revoke_report_capability(
    db: Session,
    link: OpportunityReportLink,
    now: Optional[datetime] = None,
) -> None:
    if link.revoked_at is None:
        link.revoked_at = now or _now()


def resolve_report_capability(
    db: Session,
    raw_token: str,
    now: Optional[datetime] = None,
) -> Optional[OpportunityReportLink]:
    token = str(raw_token or "").strip()
    if not token:
        return None
    link = db.scalar(
        select(OpportunityReportLink).where(
            OpportunityReportLink.token_hash == hash_report_token(token)
        )
    )
    if not link or link.revoked_at is not None:
        return None
    current = _aware_utc(now or _now())
    if _aware_utc(link.expires_at) <= current:
        return None
    opportunity = db.get(ai_company.CompanyOpportunity, link.opportunity_id)
    if not opportunity or opportunity.status == "archived":
        return None
    return link


def archive_completed_opportunities(
    db: Session,
    now: Optional[datetime] = None,
) -> int:
    current = now or _now()
    cutoff = current - timedelta(hours=COMPLETION_ARCHIVE_HOURS)
    rows = list(
        db.scalars(
            select(ai_company.CompanyOpportunity).where(
                ai_company.CompanyOpportunity.status.in_(["won", "lost"]),
                ai_company.CompanyOpportunity.updated_at < cutoff,
            )
        ).all()
    )
    for row in rows:
        row.status = "archived"
        row.updated_at = current
        revoke_opportunity_links(db, row.id, current)
        _audit(db, "opportunity_auto_archived", f"OP-{row.id:04d}")
    if rows:
        db.commit()
    return len(rows)


def store_verified_evidence(
    data: bytes,
    content_type: str,
    root: Optional[Path] = None,
) -> tuple[str, str]:
    payload = bytes(data or b"")
    mime = str(content_type or "").lower().strip()
    if mime not in _ALLOWED_IMAGE_MIME_TO_FORMAT:
        raise ValueError("نوع الصورة غير مدعوم. استخدم JPG أو PNG أو WebP.")
    if not payload:
        raise ValueError("الصورة فارغة.")
    if len(payload) > MAX_EVIDENCE_BYTES:
        raise ValueError("حجم الصورة أكبر من 5 MB.")

    try:
        with Image.open(io.BytesIO(payload)) as probe:
            actual_format = str(probe.format or "").upper()
            width, height = probe.size
            probe.verify()
        if actual_format != _ALLOWED_IMAGE_MIME_TO_FORMAT[mime]:
            raise ValueError("نوع الملف لا يطابق محتوى الصورة.")
        if width <= 0 or height <= 0 or width * height > 25_000_000:
            raise ValueError("أبعاد الصورة غير مقبولة.")
        with Image.open(io.BytesIO(payload)) as source:
            source.load()
            if source.mode not in {"RGB", "RGBA"}:
                source = source.convert("RGB")
            elif source.mode == "RGBA":
                # WebP supports alpha; keep it rather than flattening unexpectedly.
                source = source.copy()
            else:
                source = source.copy()
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ValueError("الملف المرفوع ليس صورة صالحة.") from exc

    storage_root = Path(root or EVIDENCE_ROOT)
    storage_root.mkdir(parents=True, exist_ok=True)
    filename = f"{secrets.token_hex(16)}.webp"
    target = storage_root / filename
    try:
        source.save(target, format="WEBP", quality=88, method=6)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return filename, "image/webp"


def _parse_follow_up(value: str) -> Optional[datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        local = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("تاريخ المتابعة غير صالح.") from exc
    saudi_tz = timezone(timedelta(hours=3))
    if local.tzinfo is None:
        local = local.replace(tzinfo=saudi_tz)
    return local.astimezone(timezone.utc)


def _public_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
        "X-Robots-Tag": "noindex, nofollow",
        "X-Content-Type-Options": "nosniff",
    }


def _invalid_report_page(status_code: int = 404) -> HTMLResponse:
    html = """<!doctype html><html lang='ar' dir='rtl'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>رابط غير صالح | Pakgat</title><style>body{margin:0;background:#f8fafc;font-family:Arial,Tahoma,sans-serif;color:#0f172a}.box{width:min(520px,calc(100% - 28px));margin:10vh auto;background:#fff;border:1px solid #e2e8f0;border-radius:20px;padding:26px;box-shadow:0 16px 45px rgba(15,23,42,.08)}h1{font-size:22px;color:#0b2d75}.muted{color:#64748b;font-size:13px;line-height:1.7}</style></head><body><main class='box'><h1>هذا الرابط غير صالح أو انتهت صلاحيته</h1><p class='muted'>إذا كانت الفرصة ما زالت تحت التنفيذ، تواصل مع إدارة Pakgat للحصول على رابط تحديث جديد.</p></main></body></html>"""
    return HTMLResponse(html, status_code=status_code, headers=_public_headers())


def _report_context(db: Session, token: str):
    link = resolve_report_capability(db, token)
    if not link:
        return None
    opportunity = db.get(ai_company.CompanyOpportunity, link.opportunity_id)
    agent = db.get(CompanyAgent, link.agent_id)
    dispatch = db.get(OpportunityDispatch, link.dispatch_id)
    if not opportunity or not agent or not dispatch:
        return None
    return link, opportunity, agent, dispatch


def _report_form_html(
    token: str,
    opportunity: ai_company.CompanyOpportunity,
    agent: CompanyAgent,
    error: str = "",
) -> str:
    action_options = "".join(
        f"<option value='{core.esc(key)}'>{core.esc(label)}</option>"
        for key, label in REPORT_ACTIONS.items()
    )
    error_html = (
        f"<div class='error'><strong>{core.esc(error)}</strong></div>" if error else ""
    )
    return f"""<!doctype html><html lang='ar' dir='rtl'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>تحديث OP-{opportunity.id:04d} | Pakgat</title><style>*{{box-sizing:border-box}}body{{margin:0;background:#f8fafc;font-family:Arial,Tahoma,sans-serif;color:#0f172a}}.shell{{width:min(620px,calc(100% - 24px));margin:24px auto 48px}}.brand{{background:linear-gradient(135deg,#0f172a,#111c35);border-radius:20px;padding:20px;color:#fff;margin-bottom:14px}}.brand img{{width:150px;height:52px;object-fit:contain;display:block;margin-bottom:8px}}.brand h1{{font-size:20px;margin:6px 0}}.brand p{{margin:0;color:#cbd5e1;font-size:12px;line-height:1.7}}.card{{background:#fff;border:1px solid #e2e8f0;border-radius:18px;padding:20px;box-shadow:0 10px 30px rgba(15,23,42,.05)}}.meta{{display:grid;gap:7px;background:#f8fafc;border:1px solid #e2e8f0;padding:12px;border-radius:12px;margin-bottom:16px;font-size:12px}}label{{display:block;font-size:12px;font-weight:900;margin:14px 0 6px}}select,textarea,input{{width:100%;border:1px solid #cbd5e1;border-radius:11px;padding:11px 12px;font:inherit;background:#fff}}textarea{{min-height:110px;resize:vertical}}button{{width:100%;margin-top:18px;border:0;border-radius:11px;background:linear-gradient(135deg,#2563eb,#4f46e5);color:#fff;padding:12px 16px;font-size:13px;font-weight:900;cursor:pointer}}.hint{{font-size:11px;color:#64748b;line-height:1.7;margin-top:6px}}.error{{background:#fef2f2;color:#991b1b;border:1px solid #fecaca;padding:11px 12px;border-radius:11px;margin-bottom:14px;font-size:12px}}</style></head><body><main class='shell'><section class='brand'><img src='/admin/theme/logo' alt='Pakgat'><h1>تحديث نتيجة الفرصة</h1><p>سجّل الإجراء الذي تم واترك ملاحظة واضحة للإدارة. رفع الصورة اختياري.</p></section><section class='card'>{error_html}<div class='meta'><strong>OP-{opportunity.id:04d} · {core.esc(opportunity.title)}</strong><span>المندوب: {core.esc(agent.name)}</span><span>الحالة الحالية: {core.esc(opportunity.status)}</span></div><form method='post' enctype='multipart/form-data' action='/agent/report/{core.esc(token)}'><label>الإجراء الذي اتخذته</label><select name='action' required><option value=''>اختر الإجراء</option>{action_options}</select><label>ملاحظاتك</label><textarea name='notes' maxlength='2000' placeholder='ماذا حصل؟ مع من تحدثت؟ ما النتيجة؟'></textarea><label>موعد متابعة لاحقًا · اختياري</label><input type='datetime-local' name='follow_up_at'><label>صورة إثبات · اختياري</label><input type='file' name='evidence' accept='image/jpeg,image/png,image/webp'><div class='hint'>JPG / PNG / WebP · بحد أقصى 5 MB. مثال: صورة زيارة الموقع أو عرض استلمته.</div><button type='submit'>إرسال التحديث إلى Pakgat</button></form></section></main></body></html>"""


def _report_form_response(
    token: str,
    opportunity: ai_company.CompanyOpportunity,
    agent: CompanyAgent,
    error: str = "",
    status_code: int = 200,
) -> HTMLResponse:
    return HTMLResponse(
        _report_form_html(token, opportunity, agent, error),
        status_code=status_code,
        headers=_public_headers(),
    )


@core.app.get("/agent/report/{token}", response_class=HTMLResponse)
def agent_report_page(token: str, db: Session = Depends(core.get_db)):
    context = _report_context(db, token)
    if not context:
        return _invalid_report_page()
    _link, opportunity, agent, _dispatch = context
    return _report_form_response(token, opportunity, agent)


@core.app.post("/agent/report/{token}", response_class=HTMLResponse)
async def agent_report_submit(token: str, request: Request, db: Session = Depends(core.get_db)):
    context = _report_context(db, token)
    if not context:
        return _invalid_report_page()
    link, opportunity, agent, dispatch = context

    form = await request.form()
    action = str(form.get("action") or "").strip().lower()
    notes = str(form.get("notes") or "").strip()
    follow_up_raw = str(form.get("follow_up_at") or "").strip()
    if action not in REPORT_ACTIONS:
        return _report_form_response(token, opportunity, agent, "اختر إجراءً صحيحًا.", 400)
    if len(notes) > 2000:
        return _report_form_response(token, opportunity, agent, "الملاحظات تتجاوز 2000 حرف.", 400)
    try:
        follow_up_at = _parse_follow_up(follow_up_raw)
    except ValueError as exc:
        return _report_form_response(token, opportunity, agent, str(exc), 400)

    evidence_filename = None
    evidence_content_type = None
    evidence_field = form.get("evidence")
    if evidence_field is not None and getattr(evidence_field, "filename", ""):
        content_type = str(getattr(evidence_field, "content_type", "") or "")
        payload = await evidence_field.read(MAX_EVIDENCE_BYTES + 1)
        try:
            evidence_filename, evidence_content_type = store_verified_evidence(
                payload, content_type
            )
        except (ValueError, OSError) as exc:
            return _report_form_response(token, opportunity, agent, str(exc), 400)

    current = _now()
    report = OpportunityAgentReport(
        opportunity_id=opportunity.id,
        dispatch_id=dispatch.id,
        agent_id=agent.id,
        action=action,
        notes=notes[:2000] or None,
        follow_up_at=follow_up_at,
        evidence_filename=evidence_filename,
        evidence_content_type=evidence_content_type,
        created_at=current,
    )
    db.add(report)
    opportunity.status = map_agent_action(opportunity.status, action)
    opportunity.updated_at = current
    _audit(
        db,
        "opportunity_agent_report_submitted",
        f"opportunity=OP-{opportunity.id:04d}; dispatch={dispatch.id}; agent={agent.id}; action={action}",
    )
    if evidence_filename:
        _audit(
            db,
            "opportunity_evidence_uploaded",
            f"opportunity=OP-{opportunity.id:04d}; report=pending; agent={agent.id}",
        )
    try:
        db.commit()
        db.refresh(report)
    except Exception:
        db.rollback()
        if evidence_filename:
            (EVIDENCE_ROOT / Path(evidence_filename).name).unlink(missing_ok=True)
        raise

    success = f"""<!doctype html><html lang='ar' dir='rtl'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>تم التحديث | Pakgat</title><style>body{{margin:0;background:#f8fafc;font-family:Arial,Tahoma,sans-serif;color:#0f172a}}.box{{width:min(540px,calc(100% - 28px));margin:10vh auto;background:#fff;border:1px solid #e2e8f0;border-radius:20px;padding:26px;box-shadow:0 16px 45px rgba(15,23,42,.08)}}h1{{font-size:22px;color:#047857}}p{{font-size:13px;line-height:1.8;color:#475569}}a{{display:inline-block;margin-top:10px;background:#eff6ff;color:#1d4ed8;text-decoration:none;padding:10px 13px;border-radius:10px;font-weight:900;font-size:12px}}</style></head><body><main class='box'><h1>تم إرسال التحديث ✅</h1><p>تم حفظ تحديث OP-{opportunity.id:04d} لدى Pakgat. يمكنك استخدام نفس الرابط لإضافة تحديث آخر طالما الفرصة ما زالت مفتوحة والرابط صالح.</p><a href='/agent/report/{core.esc(token)}'>إرسال تحديث إضافي</a></main></body></html>"""
    return HTMLResponse(success, headers=_public_headers())


@core.app.get(
    "/admin/company/agent-reports/{report_id}/evidence",
    include_in_schema=False,
)
def admin_agent_report_evidence(
    report_id: int,
    request: Request,
    db: Session = Depends(core.get_db),
):
    try:
        core.require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)
    report = db.get(OpportunityAgentReport, report_id)
    if not report or not report.evidence_filename:
        raise HTTPException(status_code=404, detail="Evidence not found")
    filename = Path(report.evidence_filename).name
    target = EVIDENCE_ROOT / filename
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Evidence not found")
    return FileResponse(
        target,
        media_type=report.evidence_content_type or "image/webp",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
