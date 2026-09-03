"""Evidence-based, read-only security posture for the admin dashboard."""

from __future__ import annotations

import os
from pathlib import Path
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import application as core


FAILURE_ACTIONS = ["whatsapp_failed", "merchant_whatsapp_failed", "redemption_whatsapp_failed", "merchant_redemption_whatsapp_failed"]


def _audit_count(db: Session, actions: list[str]) -> int:
    return int(db.scalar(select(func.count(core.AuditLog.id)).where(core.AuditLog.action.in_(actions))) or 0)


def security_watch_rows(db: Session) -> list[tuple[str, str, str]]:
    salla_rejected = _audit_count(db, ["salla_webhook_rejected"])
    whatsloop_rejected = _audit_count(db, ["whatsloop_webhook_signature_rejected"])
    whatsapp_failures = _audit_count(db, FAILURE_ACTIONS)
    notification_failures = int(db.scalar(select(func.count(core.CustomerNotification.id)).where(core.CustomerNotification.status == "failed")) or 0)
    admin_ready = bool(core.ADMIN_PASSWORD and core.ADMIN_SECRET and core.ADMIN_SECRET != "change-this-admin-secret")
    whatsloop_signature_ready = bool(os.getenv("WHATSLOOP_WEBHOOK_SECRET", "").strip()) or Path("/etc/pakgat/whatsloop_webhook_secret").is_file()
    return [
        ("حالة التطبيق", "يعمل · الصفحة متاحة", "ok"),
        ("اتصال قاعدة البيانات", "يعمل · القراءة ناجحة", "ok"),
        ("توقيع Webhook من سلة", "Fail-closed ومفعّل" if core.SALLA_WEBHOOK_SECRET else "السر غير مضبوط", "ok" if core.SALLA_WEBHOOK_SECRET else "bad"),
        ("Webhook سلة مرفوض", f"{salla_rejected:,}", "ok" if not salla_rejected else "pending"),
        ("توقيع WhatsLoop الوارد", "Fail-closed ومفعّل" if whatsloop_signature_ready else "مغلق حتى ضبط سر التوقيع", "ok" if whatsloop_signature_ready else "bad"),
        ("Webhook WhatsLoop مرفوض", f"{whatsloop_rejected:,}", "ok" if not whatsloop_rejected else "pending"),
        ("مصادقة لوحة الإدارة", "مضبوطة" if admin_ready else "تحتاج مراجعة الإعدادات", "ok" if admin_ready else "bad"),
        ("Secure Cookie", "مفعّل" if core.COOKIE_SECURE else "غير مفعّل", "ok" if core.COOKIE_SECURE else "bad"),
        ("فشل إرسال WhatsApp المسجل", f"{whatsapp_failures:,}", "ok" if not whatsapp_failures else "pending"),
        ("إشعارات Outbox فاشلة", f"{notification_failures:,}", "ok" if not notification_failures else "pending"),
        ("أسرار الاتصال", "لا تُعرض في هذه اللوحة", "ok"),
        ("آخر نسخة احتياطية ناجحة", "يحتاج سجل نجاح يكتبه Backup Timer", "pending"),
        ("فحص الثغرات والتحديثات", "يحتاج ماسح أمني دوري منفصل", "pending"),
    ]
