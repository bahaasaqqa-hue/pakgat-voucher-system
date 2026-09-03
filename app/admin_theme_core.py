"""Pure HTML renderer for the unified Pakgat administrative visual system.

This module has no FastAPI/database imports. Runtime response integration lives
in :mod:`app.admin_unified_theme`.
"""
from __future__ import annotations

import html as html_lib
import re


ADMIN_NAV_ITEMS = (
    ("dashboard", "لوحة الإدارة", "/admin", "⌂"),
    ("company", "شركة بكجات الذكية", "/admin/company", "✦"),
    ("new_voucher", "قسيمة جديدة", "/admin/vouchers/new", "+"),
    ("audit", "سجل العمليات", "/admin/audit", "▤"),
    ("integrations", "تكامل سلة", "/admin/integrations", "⇄"),
    ("partners", "بيانات الشركاء", "/admin/local-partners", "◇"),
)

_BODY_RE = re.compile(r"(<body\b[^>]*>)(.*?)(</body>)", re.IGNORECASE | re.DOTALL)
_TOPBAR_RE = re.compile(r"<header\s+class=['\"]topbar['\"][^>]*>.*?</header>", re.IGNORECASE | re.DOTALL)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_AI_LOGO_RE = re.compile(r"<div\s+class=['\"]ai-logo['\"][^>]*>.*?</div>", re.IGNORECASE | re.DOTALL)
_AI_BACK_RE = re.compile(
    r"<a\s+class=['\"]ai-pill['\"]\s+href=['\"]/admin['\"][^>]*>.*?رجوع إلى لوحة الإدارة.*?</a>",
    re.IGNORECASE | re.DOTALL,
)
_AI_NAV_RE = re.compile(r"(<nav\s+class=['\"]ai-nav['\"][^>]*>)", re.IGNORECASE)


UNIFIED_ADMIN_CSS = r"""
:root{--ua-bg:#f8fafc;--ua-card:#fff;--ua-ink:#0f172a;--ua-muted:#64748b;--ua-line:#e2e8f0;--ua-blue:#2563eb;--ua-blue2:#1d4ed8;--ua-navy:#0f172a;--ua-navy2:#111c35;--ua-ok:#059669;--ua-warn:#d97706;--ua-bad:#dc2626;--ua-radius:16px;--ua-shadow:0 7px 26px rgba(15,23,42,.055)}
body[data-unified-admin-theme]{background:var(--ua-bg)!important;color:var(--ua-ink)!important;font-family:Arial,Tahoma,"Segoe UI",sans-serif!important}body[data-unified-admin-theme] *{box-sizing:border-box}
.ua-shell{min-height:100vh;display:grid;grid-template-columns:230px minmax(0,1fr);direction:ltr;background:var(--ua-bg)}.ua-sidebar{direction:rtl;background:linear-gradient(180deg,var(--ua-navy),var(--ua-navy2) 64%,#0b1223);color:#fff;padding:16px 12px;position:sticky;top:0;height:100vh;overflow:auto;box-shadow:10px 0 32px rgba(15,23,42,.13);z-index:20}.ua-brand{display:block;padding:8px 8px 16px;border-bottom:1px solid rgba(255,255,255,.12);margin-bottom:12px}.ua-brand img{display:block;width:145px;max-width:100%;height:54px;object-fit:contain;margin:auto;filter:drop-shadow(0 7px 14px rgba(37,99,235,.22))}.ua-brand small{display:flex;align-items:center;gap:6px;margin-top:7px;color:#a8b7d6;font-size:11px;font-weight:800}.ua-live-dot{width:7px;height:7px;border-radius:50%;background:#22c55e;box-shadow:0 0 11px rgba(34,197,94,.8);display:inline-block}.ua-nav{display:grid;gap:5px}.ua-nav-link{display:flex;align-items:center;gap:10px;color:#dbe7ff!important;padding:10px 11px;border-radius:11px;font-size:13px;font-weight:850;transition:.18s}.ua-nav-link:hover{background:rgba(255,255,255,.08);color:#fff!important}.ua-nav-link.active{background:linear-gradient(135deg,rgba(37,99,235,.38),rgba(99,102,241,.22));box-shadow:inset 0 0 0 1px rgba(147,197,253,.18);color:#fff!important}.ua-nav-icon{width:26px;height:26px;display:grid;place-items:center;border-radius:8px;background:rgba(255,255,255,.065);font-style:normal;flex:0 0 auto}.ua-sidebar-foot{margin-top:18px;border-top:1px solid rgba(255,255,255,.12);padding:14px 8px 4px}.ua-admin-state{display:flex;align-items:center;gap:9px;padding:10px;border-radius:12px;background:rgba(255,255,255,.055);border:1px solid rgba(255,255,255,.08)}.ua-admin-avatar{width:34px;height:34px;border-radius:10px;background:linear-gradient(135deg,#2563eb,#7c3aed);display:grid;place-items:center;font-size:11px;font-weight:950}.ua-admin-state strong{display:block;font-size:11px}.ua-admin-state span{display:block;font-size:9px;color:#94a3b8}.ua-logout{margin:9px 0 0}.ua-logout button{width:100%;border:1px solid rgba(248,113,113,.2);border-radius:10px;padding:9px 11px;background:rgba(220,38,38,.12);color:#fecaca;font-size:11px;font-weight:900;cursor:pointer}
.ua-workspace{direction:rtl;min-width:0}.ua-top{min-height:66px;background:rgba(255,255,255,.94);backdrop-filter:blur(10px);border-bottom:1px solid var(--ua-line);display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 22px;position:sticky;top:0;z-index:15}.ua-top h1{font-size:18px;margin:0;color:#0b2d75;font-weight:950}.ua-top p{margin:3px 0 0;font-size:10px;color:var(--ua-muted)}.ua-top-actions{display:flex;gap:7px;align-items:center;flex-wrap:wrap}.ua-top-pill{display:inline-flex;align-items:center;gap:6px;padding:7px 9px;border:1px solid var(--ua-line);border-radius:9px;background:#fff;color:#475569;font-size:10px;font-weight:850}.ua-top-pill.ai{color:#4f46e5;background:#eef2ff}.ua-content{padding:20px 22px 42px;min-width:0}.ua-content>.wrap,.ua-content .wrap{width:100%!important;max-width:none!important;margin:0!important}.ua-content main.wrap{padding:0!important}.ua-content h1{color:#0f2f70;font-weight:950}.ua-content h2,.ua-content h3{color:#173b7d}.ua-content .muted{color:var(--ua-muted)!important}.ua-content .card{background:#fff!important;border:1px solid var(--ua-line)!important;border-radius:var(--ua-radius)!important;box-shadow:var(--ua-shadow)!important}.ua-content .grid{gap:12px!important}
.ua-content .btn,.ua-content button.btn{min-height:38px;border-radius:10px!important;padding:9px 13px!important;font-size:12px!important;font-weight:900!important;transition:.16s}.ua-content .btn-blue,.ua-content .btn-primary{background:linear-gradient(135deg,var(--ua-blue),var(--ua-blue2))!important;color:#fff!important}.ua-content .btn-muted{background:#eff6ff!important;color:#1d4ed8!important}.ua-content .btn-danger{background:#fef2f2!important;color:#b91c1c!important;border:1px solid #fee2e2!important}.ua-content .input,.ua-content .select,.ua-content input:not([type=hidden]):not([type=checkbox]):not([type=radio]):not([type=submit]),.ua-content select,.ua-content textarea{border:1px solid #cfd8e6!important;border-radius:11px!important;background:#fff!important;color:#0f172a!important;padding:11px 12px!important;outline:none!important;font-size:13px!important}.ua-content input:focus,.ua-content select:focus,.ua-content textarea:focus{border-color:#60a5fa!important;box-shadow:0 0 0 3px rgba(59,130,246,.11)!important}.ua-content label{font-size:12px!important;font-weight:900!important;color:#334155!important}.ua-content textarea{min-height:96px;resize:vertical}.ua-content .table-wrap{overflow:auto;border:1px solid var(--ua-line)!important;border-radius:14px!important;background:#fff}.ua-content table{width:100%!important;border-collapse:collapse!important;background:#fff}.ua-content th{background:#f8fafc!important;color:#64748b!important;font-size:11px!important;font-weight:900!important;padding:11px 10px!important}.ua-content td{color:#1e293b;font-size:12px;padding:12px 10px!important;border-bottom:1px solid #edf2f7!important}.ua-content .badge{display:inline-flex!important;border-radius:999px!important;padding:5px 9px!important;font-size:10px!important;font-weight:900!important}.ua-content .badge-active{background:#ecfdf5!important;color:#047857!important}.ua-content .badge-redeemed{background:#eff6ff!important;color:#1d4ed8!important}.ua-content .badge-expired{background:#fff7ed!important;color:#c2410c!important}.ua-content .alert{border-radius:12px!important;padding:11px 13px!important;font-size:12px!important}.ua-content .alert-ok{background:#ecfdf5!important;color:#065f46!important}.ua-content .alert-error{background:#fef2f2!important;color:#991b1b!important}
/* AI Company pages: keep one layout, but force the same Mission Control chrome everywhere. */
body[data-unified-admin-theme='ai'] .ai-layout{background:var(--ua-bg)!important;grid-template-columns:230px minmax(0,1fr)!important}body[data-unified-admin-theme='ai'] .ai-sidebar{background:linear-gradient(180deg,var(--ua-navy) 0%,var(--ua-navy2) 64%,#0b1223 100%)!important;top:0!important;height:100vh!important;padding:14px 12px!important;box-shadow:10px 0 32px rgba(15,23,42,.14)!important;z-index:20!important}body[data-unified-admin-theme='ai'] .ai-nav{gap:4px!important}body[data-unified-admin-theme='ai'] .ai-nav a{color:#dbe7ff!important;padding:9px 10px!important;border-radius:10px!important;font-size:12px!important;opacity:1!important;border:1px solid transparent!important}body[data-unified-admin-theme='ai'] .ai-nav a:hover{background:rgba(255,255,255,.07)!important;border-color:rgba(255,255,255,.08)!important}body[data-unified-admin-theme='ai'] .ai-nav a.active{background:linear-gradient(135deg,rgba(37,99,235,.42),rgba(99,102,241,.24))!important;border-color:rgba(147,197,253,.2)!important;box-shadow:inset 0 0 0 1px rgba(147,197,253,.06)!important}body[data-unified-admin-theme='ai'] .ai-nav i{color:#bfdbfe!important}body[data-unified-admin-theme='ai'] .ai-sidebar-foot{border-top-color:rgba(255,255,255,.1)!important;color:#a8b7d6!important;font-size:10px!important}body[data-unified-admin-theme='ai'] .ai-workspace{background:var(--ua-bg)!important}body[data-unified-admin-theme='ai'] .ai-top{top:0!important;height:66px!important;background:rgba(255,255,255,.96)!important;border-bottom:1px solid var(--ua-line)!important;box-shadow:0 4px 18px rgba(15,23,42,.035)!important;padding:9px 20px!important}body[data-unified-admin-theme='ai'] .ai-top-title{font-size:18px!important;color:#0b2d75!important}body[data-unified-admin-theme='ai'] .ai-pill{border-color:var(--ua-line)!important;background:#fff!important;color:#475569!important;border-radius:9px!important;font-size:10px!important;padding:7px 9px!important}body[data-unified-admin-theme='ai'] .ai-live{background:#ecfdf5!important;color:#047857!important}body[data-unified-admin-theme='ai'] .ai-run{background:linear-gradient(135deg,#2563eb,#4f46e5)!important;border-radius:10px!important;padding:9px 13px!important;font-size:11px!important;box-shadow:0 6px 16px rgba(37,99,235,.18)!important}body[data-unified-admin-theme='ai'] .ai-workspace .wrap{padding:18px 20px 36px!important}body[data-unified-admin-theme='ai'] .ai-panel,body[data-unified-admin-theme='ai'] .mc-card,body[data-unified-admin-theme='ai'] .card{border:1px solid var(--ua-line)!important;border-radius:16px!important;box-shadow:var(--ua-shadow)!important;background:#fff!important}.ua-ai-company-brand{padding:7px 8px 13px;border-bottom:1px solid rgba(255,255,255,.11);margin-bottom:8px}.ua-ai-company-brand img{display:block;width:142px;height:54px;object-fit:contain;margin:auto;filter:drop-shadow(0 7px 14px rgba(37,99,235,.18))}.ua-ai-company-brand strong{display:block;text-align:center;color:#fff;font-size:12px;margin-top:3px}.ua-ai-company-brand span{display:block;text-align:center;color:#93a8cb;font-size:9px;margin-top:2px}.ua-ai-sidebar-tools{padding:0 0 8px;margin-bottom:5px;border-bottom:1px solid rgba(255,255,255,.08)}.ua-ai-admin-return{display:flex!important;align-items:center!important;gap:8px!important;padding:9px 10px!important;border-radius:10px!important;background:rgba(255,255,255,.055)!important;border:1px solid rgba(255,255,255,.09)!important;color:#dbe7ff!important;font-size:11px!important;font-weight:900!important}.ua-ai-admin-return:hover{background:rgba(37,99,235,.24)!important;color:#fff!important}.ua-ai-admin-return i{width:20px;height:20px;display:grid;place-items:center;border-radius:7px;background:rgba(96,165,250,.13);font-style:normal}
.ua-login-brand{display:flex;flex-direction:column;align-items:center;gap:5px;margin:0 auto 14px;text-align:center}.ua-login-brand img{width:190px;height:74px;object-fit:contain}.ua-login-brand strong{font-size:16px;color:#0f2f70}.ua-login-brand span{font-size:10px;color:#64748b}body[data-unified-admin-theme='login']{min-height:100vh;background:linear-gradient(135deg,#f8fafc,#eef4ff)!important}body[data-unified-admin-theme='login'] .topbar{display:none!important}body[data-unified-admin-theme='login'] main,body[data-unified-admin-theme='login'] .wrap{max-width:480px!important;margin:auto!important}body[data-unified-admin-theme='login'] .card{border:1px solid var(--ua-line)!important;border-radius:20px!important;box-shadow:0 18px 50px rgba(15,23,42,.09)!important}
@media(max-width:900px){.ua-shell{grid-template-columns:1fr}.ua-sidebar{position:relative;height:auto}.ua-nav{grid-template-columns:repeat(2,minmax(0,1fr))}.ua-top{position:relative}.ua-content{padding:14px}body[data-unified-admin-theme='ai'] .ai-layout{grid-template-columns:1fr!important}body[data-unified-admin-theme='ai'] .ai-sidebar{position:relative!important;height:auto!important}body[data-unified-admin-theme='ai'] .ai-top{position:relative!important}body[data-unified-admin-theme='ai'] .ai-nav{grid-template-columns:repeat(2,minmax(0,1fr))!important}}@media(max-width:560px){.ua-nav,body[data-unified-admin-theme='ai'] .ai-nav{grid-template-columns:1fr!important}.ua-top{align-items:flex-start;flex-direction:column}.ua-content{padding:11px}.ua-content th,.ua-content td{white-space:nowrap}}
"""


def active_nav_key(path: str) -> str:
    value = str(path or "").rstrip("/") or "/"
    if value == "/admin":
        return "dashboard"
    if value.startswith("/admin/company"):
        return "company"
    if value.startswith("/admin/vouchers/new"):
        return "new_voucher"
    if value.startswith("/admin/audit"):
        return "audit"
    if value.startswith("/admin/integrations"):
        return "integrations"
    if value.startswith("/admin/local-partners"):
        return "partners"
    return ""


def _page_title(source: str) -> str:
    match = _TITLE_RE.search(source or "")
    if not match:
        return "لوحة إدارة Pakgat"
    raw = re.sub(r"\s+", " ", match.group(1)).strip()
    raw = re.sub(r"\s*\|\s*Pakgat\s*$", "", raw, flags=re.IGNORECASE).strip()
    return html_lib.unescape(raw) or "لوحة إدارة Pakgat"


def _inject_css(source: str) -> str:
    if "data-unified-admin-css" in source:
        return source
    style = f"<style data-unified-admin-css='1'>{UNIFIED_ADMIN_CSS}</style>"
    if "</head>" in source:
        return source.replace("</head>", style + "</head>", 1)
    return style + source


def _mark_body(opening: str, mode: str) -> str:
    if "data-unified-admin-theme" in opening:
        return opening
    return opening[:-1] + f" data-unified-admin-theme='{mode}'>"


def _navigation(path: str) -> str:
    active = active_nav_key(path)
    rows = []
    for key, label, href, icon in ADMIN_NAV_ITEMS:
        cls = "ua-nav-link active" if key == active else "ua-nav-link"
        rows.append(
            f"<a data-nav-key='{key}' class='{cls}' href='{href}'>"
            f"<i class='ua-nav-icon'>{html_lib.escape(icon)}</i><span>{html_lib.escape(label)}</span></a>"
        )
    return "".join(rows)


def _standard_shell(content: str, path: str, title: str, logo_data_uri: str) -> str:
    logo = html_lib.escape(str(logo_data_uri or ""), quote=True)
    return f"""<div class='ua-shell' data-ua-path='{html_lib.escape(path, quote=True)}'>
<aside class='ua-sidebar'>
<a class='ua-brand' href='/admin'><img src='{logo}' alt='Pakgat'><small><i class='ua-live-dot'></i> Pakgat Admin · متصل</small></a>
<nav class='ua-nav' aria-label='التنقل الإداري'>{_navigation(path)}</nav>
<div class='ua-sidebar-foot'><div class='ua-admin-state'><span class='ua-admin-avatar'>PA</span><div><strong>Pakgat Administration</strong><span>Voucher System + AI Company</span></div></div><form class='ua-logout' method='post' action='/admin/logout'><button type='submit'>تسجيل الخروج</button></form></div>
</aside>
<section class='ua-workspace'><header class='ua-top'><div><h1>{html_lib.escape(title)}</h1><p>Pakgat Voucher System · لوحة تشغيل موحدة</p></div><div class='ua-top-actions'><a class='ua-top-pill ai' href='/admin/company'>✦ Pakgat AI</a><span class='ua-top-pill'><i class='ua-live-dot'></i> النظام متصل</span></div></header><div class='ua-content'>{content}</div></section>
</div>"""


def _apply_login(source: str, logo_data_uri: str) -> str:
    match = _BODY_RE.search(source)
    if not match:
        return _inject_css(source)
    logo = html_lib.escape(str(logo_data_uri or ""), quote=True)
    brand = f"<div class='ua-login-brand'><img src='{logo}' alt='Pakgat'><strong>لوحة إدارة Pakgat</strong><span>دخول آمن إلى نظام القسائم والشركة الذكية</span></div>"
    replacement = _mark_body(match.group(1), "login") + brand + match.group(2) + match.group(3)
    return _inject_css(source[:match.start()] + replacement + source[match.end():])


def _ai_company_brand(logo_data_uri: str) -> str:
    logo = html_lib.escape(str(logo_data_uri or ""), quote=True)
    return f"<div class='ua-ai-company-brand'><img src='{logo}' alt='Pakgat'><strong>Pakgat AI</strong><span>Mission Control</span></div>"


def _ai_admin_return() -> str:
    return "<div class='ua-ai-sidebar-tools'><a class='ua-ai-admin-return' href='/admin'><i>←</i><span>العودة إلى لوحة الإدارة</span></a></div>"


def _apply_ai(source: str, path: str, logo_data_uri: str) -> str:
    match = _BODY_RE.search(source)
    if not match:
        return _inject_css(source)
    body = match.group(2)
    body = _AI_BACK_RE.sub("", body)
    if _AI_LOGO_RE.search(body):
        body = _AI_LOGO_RE.sub(_ai_company_brand(logo_data_uri), body, count=1)
    if "ua-ai-admin-return" not in body:
        body = _AI_NAV_RE.sub(_ai_admin_return() + r"\1", body, count=1)
    replacement = _mark_body(match.group(1), "ai") + body + match.group(3)
    return _inject_css(source[:match.start()] + replacement + source[match.end():])


def _apply_standard(source: str, path: str, logo_data_uri: str) -> str:
    match = _BODY_RE.search(source)
    if not match:
        return _inject_css(source)
    content = _TOPBAR_RE.sub("", match.group(2), count=1)
    shell = _standard_shell(content, path, _page_title(source), logo_data_uri)
    replacement = _mark_body(match.group(1), "standard") + shell + match.group(3)
    return _inject_css(source[:match.start()] + replacement + source[match.end():])


def apply_admin_theme(source: str, path: str, logo_data_uri: str = "") -> str:
    """Return themed HTML for one admin path without changing route semantics."""
    html = str(source or "")
    clean_path = str(path or "")
    if not clean_path.startswith("/admin"):
        return html
    if "data-unified-admin-theme" in html:
        return html
    if clean_path.rstrip("/") == "/admin/login":
        return _apply_login(html, logo_data_uri)
    has_ai_layout = "class='ai-layout'" in html or 'class="ai-layout"' in html
    if has_ai_layout:
        return _apply_ai(html, clean_path, logo_data_uri)
    return _apply_standard(html, clean_path, logo_data_uri)
