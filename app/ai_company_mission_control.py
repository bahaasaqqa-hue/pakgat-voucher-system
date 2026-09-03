"""Pure deterministic helpers for Pakgat AI Mission Control."""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone


_ALLOWED_COMMANDS = (
    (("شغل الشركة", "شغّل الشركة", "تشغيل الشركة", "run company", "refresh company"), "RUN_COMPANY", "تشغيل دورة الشركة"),
    (("الفرص", "opportunit"), "/admin/company/opportunities", "فتح الفرص الجديدة"),
    (("الموافقات", "القرارات", "governance", "approval"), "/admin/company/governance", "فتح القرارات والموافقات"),
    (("المصادر", "التكاملات", "sources", "integration"), "/admin/company/sources", "فتح مصادر البيانات"),
    (("التقنية", "الأمان", "الامن", "technology", "security"), "/admin/company/technology", "فتح التقنية والأمان"),
    (("seo", "google", "جوجل"), "/admin/company/seo", "فتح SEO وGoogle"),
    (("الأنظمة", "الانظمة", "systems"), "/admin/company/systems", "فتح أنظمة الشركة"),
    (("الملخص", "brief", "executive"), "/admin/company/brief", "فتح الملخص التنفيذي"),
)

_PRIORITY_WEIGHT = {"P0": 60, "P1": 45, "P2": 30, "P3": 15}
_APPROVAL_LEVEL_WEIGHT = {
    "CEO ONLY": 30,
    "ONLY CEO": 30,
    "CEO_ONLY": 30,
    "ONLY_CEO": 30,
    "APPROVAL": 15,
    "AUTO": 0,
}
_OPPORTUNITY_PRIORITY = {"P0": 28, "P1": 20, "P2": 12, "P3": 6}
_OPPORTUNITY_STATUS = {"new": 12, "review": 9, "approved": 6, "active": 4}


def _normalize_text(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[ًٌٍَُِّْـ]", "", text)
    return re.sub(r"\s+", " ", text)


def resolve_command(text: str) -> tuple[str | None, str]:
    """Map free text to a fixed allow-list of safe internal Mission Control actions."""
    value = _normalize_text(text)
    if not value:
        return None, "اكتب أمرًا مثل: اعرض الفرص، القرارات، المصادر، التقنية، SEO أو شغّل الشركة."
    for keywords, target, message in _ALLOWED_COMMANDS:
        if any(_normalize_text(keyword) in value for keyword in keywords):
            return target, message
    return None, "هذا الأمر غير مدعوم داخل Mission Control. استخدم أمرًا داخليًا من القائمة المقترحة."


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _age_days(created_at: datetime | None, now: datetime | None = None) -> int:
    created = _utc(created_at)
    if created is None:
        return 0
    current = _utc(now) or datetime.now(timezone.utc)
    delta = max(0.0, (current - created).total_seconds())
    return int(delta // 86400)


def approval_weight(priority: str, approval_level: str, created_at: datetime | None = None, now: datetime | None = None) -> int:
    """Queue-priority score derived only from stored governance fields and age."""
    p = _PRIORITY_WEIGHT.get(str(priority or "").strip().upper(), 20)
    level = str(approval_level or "").strip().upper().replace("-", "_")
    level_weight = _APPROVAL_LEVEL_WEIGHT.get(level, 10)
    age_bonus = min(10, _age_days(created_at, now))
    return int(p + level_weight + age_bonus)


def _recency_bonus(created_at: datetime | None, now: datetime | None = None) -> int:
    created = _utc(created_at)
    if created is None:
        return 0
    current = _utc(now) or datetime.now(timezone.utc)
    hours = max(0.0, (current - created).total_seconds() / 3600.0)
    if hours <= 24:
        return 6
    if hours <= 72:
        return 4
    if hours <= 168:
        return 2
    return 0


def opportunity_attention_score(stored_score, priority: str, status: str, created_at: datetime | None = None, now: datetime | None = None) -> int:
    """Attention score for ordering real opportunities; never represents confidence or revenue."""
    priority_weight = _OPPORTUNITY_PRIORITY.get(str(priority or "").strip().upper(), 8)
    status_weight = _OPPORTUNITY_STATUS.get(str(status or "").strip().lower(), 4)
    recency = _recency_bonus(created_at, now)
    if stored_score is None:
        raw = 34 + priority_weight + status_weight + recency
    else:
        try:
            factual = max(0.0, min(100.0, float(stored_score)))
        except (TypeError, ValueError):
            factual = 0.0
        raw = factual * 0.62 + priority_weight + status_weight + recency
    return max(0, min(100, int(round(raw))))


def freshness_label(created_at: datetime | None, now: datetime | None = None) -> str:
    """Format a real timestamp as compact Arabic freshness text."""
    created = _utc(created_at)
    if created is None:
        return "—"
    current = _utc(now) or datetime.now(timezone.utc)
    seconds = max(0, int((current - created).total_seconds()))
    if seconds < 60:
        return "الآن"
    minutes = seconds // 60
    if minutes < 60:
        return f"منذ {minutes} د"
    hours = minutes // 60
    if hours < 24:
        return f"منذ {hours} س"
    days = hours // 24
    if days < 30:
        return f"منذ {days} ي"
    months = max(1, days // 30)
    return f"منذ {months} ش"


def sparkline_points(values, width: int = 116, height: int = 30) -> str:
    """Convert factual numeric history into SVG polyline points; empty if insufficient."""
    nums = []
    for value in values or []:
        try:
            nums.append(float(value))
        except (TypeError, ValueError):
            continue
    if len(nums) < 2:
        return ""
    lo, hi = min(nums), max(nums)
    spread = hi - lo
    step = width / max(1, len(nums) - 1)
    points = []
    for idx, value in enumerate(nums):
        x = idx * step
        y = height / 2 if math.isclose(spread, 0.0) else height - ((value - lo) / spread) * height
        points.append(f"{x:.1f},{y:.1f}")
    return " ".join(points)
