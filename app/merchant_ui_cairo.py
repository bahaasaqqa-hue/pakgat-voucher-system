"""Stable Cairo typography and grouped admin navigation for Pakgat.

Presentation only: this module does not change merchant, voucher, settlement,
Salla, WhatsLoop, Jood, campaign, QR or API business behavior. Cairo typography
is global across authenticated admin HTML; finance wording translation remains
restricted to the approved finance/admin surfaces.
"""
from __future__ import annotations

import html as html_lib
import re

from fastapi.responses import HTMLResponse

from app import application as core


CAIRO_ADMIN_HEAD = r"""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;500;600;700&display=swap" rel="stylesheet">
<style id="pakgat-cairo-admin">
body[data-unified-admin-theme],
body[data-unified-admin-theme] button,
body[data-unified-admin-theme] input,
body[data-unified-admin-theme] select,
body[data-unified-admin-theme] textarea{
  font-family:'Cairo',Tahoma,Arial,sans-serif!important;
}
body[data-unified-admin-theme]{font-weight:400!important}

/* Stable navigation hierarchy: section titles bold, links regular/medium. */
body[data-unified-admin-theme] .ua-nav{gap:0!important}
body[data-unified-admin-theme] .ua-nav-section{display:grid;gap:4px;margin:0 0 12px}
body[data-unified-admin-theme] .ua-nav-section:last-child{margin-bottom:0}
body[data-unified-admin-theme] .ua-nav-section-title{
  padding:4px 11px 3px;
  color:#7f95ba;
  font-size:10px;
  line-height:1.4;
  font-weight:700!important;
  letter-spacing:0!important;
}
body[data-unified-admin-theme] .ua-nav-link{font-weight:500!important}
body[data-unified-admin-theme] .ua-nav-link.active{font-weight:600!important}
body[data-unified-admin-theme] .ua-brand small{font-weight:500!important}
body[data-unified-admin-theme] .ua-admin-state strong{font-weight:600!important}
body[data-unified-admin-theme] .ua-admin-state span{font-weight:400!important}
body[data-unified-admin-theme] .ua-logout button{font-weight:500!important}

/* One typography scale for standard admin pages. */
body[data-unified-admin-theme] .ua-top h1{
  font-size:18px!important;
  line-height:1.35!important;
  font-weight:700!important;
  letter-spacing:0!important;
}
body[data-unified-admin-theme] .ua-top p{font-size:11px!important;font-weight:400!important}
body[data-unified-admin-theme] .ua-top-pill{font-size:11px!important;font-weight:500!important}
body[data-unified-admin-theme] .ua-content{padding-top:16px!important;font-size:13px!important}
body[data-unified-admin-theme] .ua-content h1,
body[data-unified-admin-theme] .ua-content h2,
body[data-unified-admin-theme] .ua-content h3{font-weight:700!important;letter-spacing:0!important}
body[data-unified-admin-theme] .ua-content h1{font-size:26px!important;line-height:1.35!important;margin:0 0 7px!important}
body[data-unified-admin-theme] .ua-content h2{font-size:18px!important;line-height:1.45!important;margin-top:0!important}
body[data-unified-admin-theme] .ua-content h3{font-size:15px!important;line-height:1.5!important}
body[data-unified-admin-theme] .ua-content p,
body[data-unified-admin-theme] .ua-content li,
body[data-unified-admin-theme] .ua-content td,
body[data-unified-admin-theme] .ua-content details,
body[data-unified-admin-theme] .ua-content summary{font-weight:400!important;line-height:1.65!important}
body[data-unified-admin-theme] .ua-content label{font-weight:500!important}
body[data-unified-admin-theme] .ua-content th{font-weight:600!important;font-size:12px!important;line-height:1.5!important}
body[data-unified-admin-theme] .ua-content td{font-weight:400!important;font-size:12px!important}
body[data-unified-admin-theme] .ua-content strong{font-weight:600!important}
body[data-unified-admin-theme] .ua-content .grid .card strong{font-weight:700!important;font-variant-numeric:tabular-nums}
body[data-unified-admin-theme] .ua-content .btn,
body[data-unified-admin-theme] .ua-content button{font-weight:500!important;font-size:12px!important}
body[data-unified-admin-theme] .ua-content .badge{font-weight:500!important}
body[data-unified-admin-theme] .ua-content input,
body[data-unified-admin-theme] .ua-content select,
body[data-unified-admin-theme] .ua-content textarea{font-weight:400!important}
body[data-unified-admin-theme] .ua-content main.wrap>p.muted{margin:0 0 16px!important}
body[data-unified-admin-theme] .ua-content main.wrap>div:first-child{margin-bottom:14px!important}
body[data-unified-admin-theme] .ua-content .card{margin-top:0}

/* Match Pakgat AI Company to the same weight and size system. */
body[data-unified-admin-theme='ai'] .ai-nav a{font-size:13px!important;font-weight:500!important}
body[data-unified-admin-theme='ai'] .ai-nav a.active{font-weight:600!important}
body[data-unified-admin-theme='ai'] .ai-top-title{font-size:18px!important;font-weight:700!important}
body[data-unified-admin-theme='ai'] .ai-pill,
body[data-unified-admin-theme='ai'] .ai-run,
body[data-unified-admin-theme='ai'] .ua-ai-admin-return{font-weight:500!important}
body[data-unified-admin-theme='ai'] .ai-workspace{font-size:13px!important;font-weight:400!important}
body[data-unified-admin-theme='ai'] .ai-workspace h1,
body[data-unified-admin-theme='ai'] .ai-workspace h2,
body[data-unified-admin-theme='ai'] .ai-workspace h3{font-weight:700!important;letter-spacing:0!important}
body[data-unified-admin-theme='ai'] .ai-workspace h1{font-size:26px!important;line-height:1.35!important}
body[data-unified-admin-theme='ai'] .ai-workspace h2{font-size:18px!important;line-height:1.45!important}
body[data-unified-admin-theme='ai'] .ai-workspace h3{font-size:15px!important;line-height:1.5!important}
body[data-unified-admin-theme='ai'] .ai-workspace p{font-weight:400!important}
body[data-unified-admin-theme='ai'] .ai-workspace li,
body[data-unified-admin-theme='ai'] .ai-workspace details,
body[data-unified-admin-theme='ai'] .ai-workspace summary{font-weight:400!important}
body[data-unified-admin-theme='ai'] .ai-workspace label{font-weight:500!important}
body[data-unified-admin-theme='ai'] .ai-workspace th{font-size:12px!important;font-weight:600!important}
body[data-unified-admin-theme='ai'] .ai-workspace td{font-size:12px!important;font-weight:400!important}
body[data-unified-admin-theme='ai'] .ai-workspace .btn{font-size:12px!important;font-weight:500!important}
body[data-unified-admin-theme='ai'] .ai-workspace input,
body[data-unified-admin-theme='ai'] .ai-workspace select,
body[data-unified-admin-theme='ai'] .ai-workspace textarea{font-size:12px!important;font-weight:400!important}
body[data-unified-admin-theme='ai'] .ai-kpi .value,
body[data-unified-admin-theme='ai'] .ai-big,
body[data-unified-admin-theme='ai'] .opp-kpi-value{font-weight:700!important}

@media(max-width:700px){
  body[data-unified-admin-theme] .ua-content h1,
  body[data-unified-admin-theme='ai'] .ai-workspace h1{font-size:23px!important}
  body[data-unified-admin-theme] .ua-content h2,
  body[data-unified-admin-theme='ai'] .ai-workspace h2{font-size:17px!important}
}
</style>
"""


_PHRASE_TRANSLATIONS = (
    ("Active / أموال معلقة", "قسائم نشطة"),
    ("Expired بدون استخدام", "منتهية دون استخدام"),
    ("Cancelled / Revoked", "ملغاة"),
    ("Redemption Rate:", "نسبة الاستبدال:"),
    ("Refund Rate:", "نسبة الاسترجاع:"),
    ("<strong>IBAN:</strong>", "<strong>الآيبان:</strong>"),
    (">Product ID<", ">معرّف المنتج<"),
    ("لا يدخل هنا إلا ما تم Redeem فعليًا.", "لا يدخل هنا إلا ما تم استبدال القسيمة فعليًا."),
)

_TEXT_NODE_TRANSLATIONS = {
    "Active": "نشطة",
    "Redeemed": "مستخدمة",
    "Refunded": "مستردة",
    "Expired": "منتهية",
    "active": "نشط",
    "inactive": "غير نشط",
    "draft": "مسودة",
    "approved": "معتمدة",
    "paid": "مدفوعة",
    "pending": "معلقة",
    "batched": "ضمن تسوية",
    "redeemed": "مستخدمة",
    "refunded": "مستردة",
    "expired": "منتهية",
    "revoked": "ملغاة",
    "cancelled": "ملغاة",
    "general": "عام",
    "finance": "مالي",
    "sales": "مبيعات",
    "contract": "عقد",
    "complaint": "شكوى",
    "operations": "تشغيل",
}

_FINANCE_PATH_PREFIXES = ("/admin/merchants", "/admin/settlements")
_STANDARD_NAV_RE = re.compile(
    r"<nav\s+class=['\"]ua-nav['\"][^>]*>.*?</nav>",
    re.IGNORECASE | re.DOTALL,
)

_ADMIN_NAV_GROUPS = (
    (
        "الرئيسية",
        (
            ("company", "شركة بكجات الذكية", "/admin/company", "✦"),
            ("dashboard", "ملخص الإدارة", "/admin", "⌂"),
        ),
    ),
    (
        "القسائم",
        (("new_voucher", "قسيمة جديدة", "/admin/vouchers/new", "+"),),
    ),
    (
        "التجار والمالية",
        (
            ("merchants", "التجار", "/admin/merchants", "◇"),
            ("settlements", "التسويات والمستحقات", "/admin/settlements", "≋"),
            ("partners", "بيانات الشركاء", "/admin/local-partners", "◎"),
        ),
    ),
    (
        "التكاملات",
        (("integrations", "تكامل سلة", "/admin/integrations", "⇄"),),
    ),
    (
        "النظام",
        (("audit", "سجل العمليات", "/admin/audit", "▤"),),
    ),
)


def _is_admin_path(path: str) -> bool:
    return str(path or "").startswith("/admin")


def _is_finance_path(path: str) -> bool:
    clean = str(path or "")
    return clean == "/admin" or any(clean.startswith(prefix) for prefix in _FINANCE_PATH_PREFIXES)


def _active_nav_key(path: str) -> str:
    clean = str(path or "").rstrip("/") or "/"
    if clean == "/admin":
        return "dashboard"
    if clean.startswith("/admin/company"):
        return "company"
    if clean.startswith("/admin/vouchers/new"):
        return "new_voucher"
    if clean.startswith("/admin/merchants"):
        return "merchants"
    if clean.startswith("/admin/settlements"):
        return "settlements"
    if clean.startswith("/admin/local-partners"):
        return "partners"
    if clean.startswith("/admin/integrations"):
        return "integrations"
    if clean.startswith("/admin/audit"):
        return "audit"
    return ""


def _standard_navigation(path: str) -> str:
    active = _active_nav_key(path)
    groups: list[str] = []
    for section_label, items in _ADMIN_NAV_GROUPS:
        rows = [
            "<div class='ua-nav-section'>",
            f"<div class='ua-nav-section-title'>{html_lib.escape(section_label)}</div>",
        ]
        for key, label, href, icon in items:
            cls = "ua-nav-link active" if key == active else "ua-nav-link"
            rows.append(
                f"<a data-nav-key='{key}' class='{cls}' href='{href}'>"
                f"<i class='ua-nav-icon'>{html_lib.escape(icon)}</i>"
                f"<span>{html_lib.escape(label)}</span></a>"
            )
        rows.append("</div>")
        groups.append("".join(rows))
    return "<nav class='ua-nav' aria-label='التنقل الإداري'>" + "".join(groups) + "</nav>"


def _apply_standard_navigation(source: str, path: str) -> str:
    rendered = source
    if "data-unified-admin-theme='standard'" not in rendered and 'data-unified-admin-theme="standard"' not in rendered:
        return rendered
    if _STANDARD_NAV_RE.search(rendered):
        rendered = _STANDARD_NAV_RE.sub(_standard_navigation(path), rendered, count=1)
    rendered = rendered.replace("class='ua-brand' href='/admin'", "class='ua-brand' href='/admin/company'", 1)
    rendered = rendered.replace('class="ua-brand" href="/admin"', 'class="ua-brand" href="/admin/company"', 1)
    return rendered


def _translate_exact_text_nodes(source: str) -> str:
    rendered = source
    for original, translated in _TEXT_NODE_TRANSLATIONS.items():
        pattern = re.compile(r">(\s*)" + re.escape(original) + r"(\s*)<")
        rendered = pattern.sub(lambda match: f">{match.group(1)}{translated}{match.group(2)}<", rendered)
    return rendered


def apply_merchant_ui_polish(source: str, path: str) -> str:
    """Apply stable admin typography/navigation; translate finance labels only on finance pages."""
    if not _is_admin_path(path):
        return source

    rendered = str(source or "")
    if "id=\"pakgat-cairo-admin\"" not in rendered:
        if "</head>" in rendered:
            rendered = rendered.replace("</head>", CAIRO_ADMIN_HEAD + "</head>", 1)
        else:
            rendered = CAIRO_ADMIN_HEAD + rendered

    rendered = _apply_standard_navigation(rendered, path)

    if _is_finance_path(path):
        for original, translated in _PHRASE_TRANSLATIONS:
            rendered = rendered.replace(original, translated)
        rendered = _translate_exact_text_nodes(rendered)
    return rendered


async def _response_body(response) -> bytes:
    iterator = getattr(response, "body_iterator", None)
    if iterator is not None:
        chunks: list[bytes] = []
        async for chunk in iterator:
            chunks.append(chunk if isinstance(chunk, bytes) else str(chunk).encode("utf-8"))
        return b"".join(chunks)
    body = getattr(response, "body", b"")
    return body if isinstance(body, bytes) else bytes(body or b"")


def _safe_html_headers(response) -> dict[str, str]:
    blocked = {"content-length", "content-type"}
    return {key: value for key, value in response.headers.items() if key.lower() not in blocked}


@core.app.middleware("http")
async def merchant_ui_cairo_middleware(request, call_next):
    response = await call_next(request)
    path = request.url.path

    if not _is_admin_path(path) or request.method.upper() != "GET":
        return response
    if 300 <= response.status_code < 400:
        return response
    if "text/html" not in response.headers.get("content-type", "").lower():
        return response

    body = await _response_body(response)
    source = body.decode("utf-8", errors="replace")
    rendered = apply_merchant_ui_polish(source, path)
    return HTMLResponse(
        content=rendered,
        status_code=response.status_code,
        headers=_safe_html_headers(response),
        background=getattr(response, "background", None),
    )


__all__ = ["apply_merchant_ui_polish", "merchant_ui_cairo_middleware"]
