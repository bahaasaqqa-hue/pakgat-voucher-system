"""Pure HTML renderer for the unified Pakgat administrative visual system.

This module deliberately has no FastAPI/database imports so its behavior can be
unit tested without production configuration. Runtime response integration lives
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


UNIFIED_ADMIN_CSS = r"""
:root{--ua-bg:#f8fafc;--ua-card:#fff;--ua-ink:#0f172a;--ua-muted:#64748b;--ua-line:#e2e8f0;--ua-blue:#2563eb;--ua-blue2:#1d4ed8;--ua-navy:#0f172a;--ua-navy2:#111c35;--ua-ok:#059669;--ua-warn:#d97706;--ua-bad:#dc2626;--ua-radius:16px;--ua-shadow:0 7px 26px rgba(15,23,42,.055)}
body[data-unified-admin-theme]{background:var(--ua-bg)!important;color:var(--ua-ink)!important;font-family:Arial,Tahoma,"Segoe UI",sans-serif!important}
body[data-unified-admin-theme] *{box-sizing:border-box}
.ua-shell{min-height:100vh;display:grid;grid-template-columns:230px minmax(0,1fr);direction:ltr;background:var(--ua-bg)}
.ua-sidebar{direction:rtl;background:linear-gradient(180deg,var(--ua-navy) 0%,var(--ua-navy2) 64%,#0b1223 100%);color:#fff;padding:16px 12px;position:sticky;top:0;height:100vh;overflow:auto;box-shadow:10px 0 32px rgba(15,23,42,.13);z-index:20}
.ua-brand{display:block;padding:8px 8px 16px;border-bottom:1px solid rgba(255,255,255,.12);margin-bottom:12px}.ua-brand img{display:block;width:145px;max-width:100%;height:54px;object-fit:contain;object-position:center;filter:drop-shadow(0 7px 14px rgba(37,99,235,.22))}.ua-brand small{display:flex;align-items:center;gap:6px;margin-top:7px;color:#a8b7d6;font-size:11px;font-weight:800}.ua-live-dot{width:7px;height:7px;border-radius:50%;background:#22c55e;box-shadow:0 0 11px rgba(34,197,94,.8);display:inline-block}
.ua-nav{display:grid;gap:5px}.ua-nav-link{display:flex;align-items:center;gap:10px;color:#dbe7ff!important;padding:10px 11px;border-radius:11px;font-size:13px;font-weight:850;transition:background .18s ease,color .18s ease,transform .18s ease}.ua-nav-link:hover{background:rgba(255,255,255,.08);color:#fff!important;transform:translateX(-1px)}.ua-nav-link.active{background:linear-gradient(135deg,rgba(37,99,235,.38),rgba(99,102,241,.22));box-shadow:inset 0 0 0 1px rgba(147,197,253,.18);color:#fff!important}.ua-nav-icon{width:26px;height:26px;display:grid;place-items:center;border-radius:8px;background:rgba(255,255,255,.065);font-style:normal;font-size:13px;flex:0 0 auto}.ua-nav-link.active .ua-nav-icon{background:rgba(96,165,250,.18)}
.ua-sidebar-foot{margin-top:18px;border-top:1px solid rgba(255,255,255,.12);padding:14px 8px 4px}.ua-sidebar-foot .ua-admin-state{display:flex;align-items:center;gap:9px;padding:10px;border-radius:12px;background:rgba(255,255,255,.055);border:1px solid rgba(255,255,255,.08)}.ua-admin-avatar{width:34px;height:34px;border-radius:10px;background:linear-gradient(135deg,#2563eb,#7c3aed);display:grid;place-items:center;font-size:11px;font-weight:950}.ua-admin-state strong{display:block;font-size:11px}.ua-admin-state span{display:block;font-size:9px;color:#94a3b8;margin-top:2px}.ua-logout{margin:9px 0 0}.ua-logout button{width:100%;border:1px solid rgba(248,113,113,.2);border-radius:10px;padding:9px 11px;background:rgba(220,38,38,.12);color:#fecaca;font-size:11px;font-weight:900;cursor:pointer}.ua-logout button:hover{background:rgba(220,38,38,.2);color:#fff}
.ua-workspace{direction:rtl;min-width:0}.ua-top{min-height:66px;background:rgba(255,255,255,.94);backdrop-filter:blur(10px);border-bottom:1px solid var(--ua-line);display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 22px;position:sticky;top:0;z-index:15}.ua-top h1{font-size:18px;line-height:1.3;margin:0;color:#0b2d75;font-weight:950}.ua-top p{margin:3px 0 0;font-size:10px;color:var(--ua-muted)}.ua-top-actions{display:flex;gap:7px;align-items:center;flex-wrap:wrap}.ua-top-pill{display:inline-flex;align-items:center;gap:6px;padding:7px 9px;border:1px solid var(--ua-line);border-radius:9px;background:#fff;color:#475569;font-size:10px;font-weight:850}.ua-top-pill.ai{color:#4f46e5;background:#eef2ff;border-color:#dfe3ff}
.ua-content{padding:20px 22px 42px;min-width:0}.ua-content>.wrap,.ua-content .wrap{width:100%!important;max-width:none!important;margin:0!important}.ua-content main.wrap{padding:0!important}.ua-content h1{color:#0f2f70;font-weight:950}.ua-content h2,.ua-content h3{color:#173b7d}.ua-content .muted{color:var(--ua-muted)!important}
.ua-content .card{background:var(--ua-card)!important;border:1px solid var(--ua-line)!important;border-radius:var(--ua-radius)!important;box-shadow:var(--ua-shadow)!important}.ua-content .grid{gap:12px!important}
.ua-content .btn,.ua-content button.btn{min-height:38px;border-radius:10px!important;padding:9px 13px!important;font-size:12px!important;font-weight:900!important;transition:transform .16s ease,box-shadow .16s ease,background .16s ease}.ua-content .btn:hover,.ua-content button.btn:hover{transform:translateY(-1px)}.ua-content .btn-blue,.ua-content .btn-primary{background:linear-gradient(135deg,var(--ua-blue),var(--ua-blue2))!important;color:#fff!important;box-shadow:0 6px 15px rgba(37,99,235,.16)}.ua-content .btn-muted{background:#eff6ff!important;color:#1d4ed8!important}.ua-content .btn-danger{background:#fef2f2!important;color:#b91c1c!important;border:1px solid #fee2e2!important}
.ua-content .input,.ua-content .select,.ua-content input:not([type=hidden]):not([type=checkbox]):not([type=radio]):not([type=submit]),.ua-content select,.ua-content textarea{border:1px solid #cfd8e6!important;border-radius:11px!important;background:#fff!important;color:#0f172a!important;padding:11px 12px!important;outline:none!important;font-size:13px!important;transition:border-color .16s ease,box-shadow .16s ease}.ua-content .input:focus,.ua-content .select:focus,.ua-content input:focus,.ua-content select:focus,.ua-content textarea:focus{border-color:#60a5fa!important;box-shadow:0 0 0 3px rgba(59,130,246,.11)!important}.ua-content label{font-size:12px!important;font-weight:900!important;color:#334155!important;margin-bottom:6px!important}.ua-content textarea{min-height:96px;resize:vertical}
.ua-content .table-wrap{overflow:auto;border:1px solid var(--ua-line)!important;border-radius:14px!important;background:#fff}.ua-content table{width:100%!important;border-collapse:collapse!important;background:#fff}.ua-content th{background:#f8fafc!important;color:#64748b!important;font-size:11px!important;font-weight:900!important;padding:11px 10px!important;border-bottom:1px solid var(--ua-line)!important}.ua-content td{color:#1e293b;font-size:12px;padding:12px 10px!important;border-bottom:1px solid #edf2f7!important}.ua-content tbody tr:hover td{background:#fbfdff}.ua-content tbody tr:last-child td{border-bottom:0!important}
.ua-content .badge{display:inline-flex!important;align-items:center!important;border-radius:999px!important;padding:5px 9px!important;font-size:10px!important;font-weight:900!important}.ua-content .badge-active{background:#ecfdf5!important;color:#047857!important}.ua-content .badge-redeemed{background:#eff6ff!important;color:#1d4ed8!important}.ua-content .badge-expired{background:#fff7ed!important;color:#c2410c!important}.ua-content .alert{border-radius:12px!important;padding:11px 13px!important;font-size:12px!important}.ua-content .alert-ok{background:#ecfdf5!important;color:#065f46!important;border:1px solid #d1fae5!important}.ua-content .alert-error{background:#fef2f2!important;color:#991b1b!important;border:1px solid #fee2e2!important}
.ua-content form[method=get],.ua-content form[method='get']{accent-color:var(--ua-blue)}
.ua-ai-global{height:48px;display:flex;align-items:center;gap:7px;padding:6px 14px;background:#fff;border-bottom:1px solid var(--ua-line);position:sticky;top:0;z-index:30;direction:rtl;overflow-x:auto;box-shadow:0 4px 16px rgba(15,23,42,.035)}.ua-ai-global .ua-ai-brand{display:flex;align-items:center;gap:7px;margin-left:auto;min-width:max-content}.ua-ai-global .ua-ai-brand img{width:92px;height:32px;object-fit:contain}.ua-ai-global a{display:inline-flex;align-items:center;min-width:max-content;padding:7px 9px;border-radius:9px;background:#f8fafc;border:1px solid var(--ua-line);font-size:10px;font-weight:900;color:#334155!important}.ua-ai-global a.active{background:#eff6ff;color:#1d4ed8!important;border-color:#bfdbfe}.ua-ai-global form{margin:0}.ua-ai-global button{border:1px solid #fee2e2;border-radius:9px;padding:7px 9px;background:#fef2f2;color:#b91c1c;font-size:10px;font-weight:900;cursor:pointer}body[data-unified-admin-theme='ai'] .ai-sidebar{top:48px!important;height:calc(100vh - 48px)!important}body[data-unified-admin-theme='ai'] .ai-top{top:48px!important}body[data-unified-admin-theme='ai'] .ai-workspace{background:var(--ua-bg)!important}body[data-unified-admin-theme='ai'] .ai-panel,body[data-unified-admin-theme='ai'] .mc-card{border-color:var(--ua-line)!important;box-shadow:var(--ua-shadow)!important}
.ua-login-brand{display:flex;flex-direction:column;align-items:center;gap:5px;margin:0 auto 14px;text-align:center}.ua-login-brand img{width:190px;height:74px;object-fit:contain;filter:drop-shadow(0 10px 18px rgba(37,99,235,.14))}.ua-login-brand strong{font-size:16px;color:#0f2f70}.ua-login-brand span{font-size:10px;color:#64748b}body[data-unified-admin-theme='login']{min-height:100vh;background:radial-gradient(circle at 75% 10%,#eaf2ff 0,transparent 32%),linear-gradient(135deg,#f8fafc,#eef4ff)!important}body[data-unified-admin-theme='login'] .topbar{display:none!important}body[data-unified-admin-theme='login'] main,body[data-unified-admin-theme='login'] .wrap{max-width:480px!important;margin:auto!important}body[data-unified-admin-theme='login'] .card{border:1px solid var(--ua-line)!important;border-radius:20px!important;box-shadow:0 18px 50px rgba(15,23,42,.09)!important}
@media(max-width:900px){.ua-shell{grid-template-columns:1fr}.ua-sidebar{position:relative;height:auto;top:auto}.ua-brand img{width:128px}.ua-nav{grid-template-columns:repeat(2,minmax(0,1fr))}.ua-sidebar-foot{display:grid;grid-template-columns:1fr 1fr;gap:8px}.ua-logout{margin:0}.ua-top{position:relative;padding:10px 14px}.ua-content{padding:14px}.ua-ai-global{position:relative}.ua-ai-global .ua-ai-brand{margin-left:0}body[data-unified-admin-theme='ai'] .ai-sidebar{top:0!important;height:auto!important}body[data-unified-admin-theme='ai'] .ai-top{top:0!important}}
@media(max-width:560px){.ua-nav{grid-template-columns:1fr}.ua-top{align-items:flex-start;flex-direction:column}.ua-sidebar-foot{grid-template-columns:1fr}.ua-content{padding:11px}.ua-content th,.ua-content td{white-space:nowrap}.ua-ai-global{padding:6px 9px}}
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
            f"<i class='ua-nav-icon'>{html_lib.escape(icon)}</i>"
            f"<span>{html_lib.escape(label)}</span></a>"
        )
    return "".join(rows)


def _standard_shell(content: str, path: str, title: str, logo_data_uri: str) -> str:
    logo = html_lib.escape(str(logo_data_uri or ""), quote=True)
    return f"""<div class='ua-shell' data-ua-path='{html_lib.escape(path, quote=True)}'>
<aside class='ua-sidebar'>
  <a class='ua-brand' href='/admin'><img src='{logo}' alt='Pakgat'><small><i class='ua-live-dot'></i> Pakgat Admin · متصل</small></a>
  <nav class='ua-nav' aria-label='التنقل الإداري'>{_navigation(path)}</nav>
  <div class='ua-sidebar-foot'>
    <div class='ua-admin-state'><span class='ua-admin-avatar'>PA</span><div><strong>Pakgat Administration</strong><span>Voucher System + AI Company</span></div></div>
    <form class='ua-logout' method='post' action='/admin/logout'><button type='submit'>تسجيل الخروج</button></form>
  </div>
</aside>
<section class='ua-workspace'>
  <header class='ua-top'><div><h1>{html_lib.escape(title)}</h1><p>Pakgat Voucher System · لوحة تشغيل موحدة</p></div><div class='ua-top-actions'><a class='ua-top-pill ai' href='/admin/company'>✦ Pakgat AI</a><span class='ua-top-pill'><i class='ua-live-dot'></i> النظام متصل</span></div></header>
  <div class='ua-content'>{content}</div>
</section>
</div>"""


def _ai_global_bar(path: str, logo_data_uri: str) -> str:
    logo = html_lib.escape(str(logo_data_uri or ""), quote=True)
    links = []
    active = active_nav_key(path)
    for key, label, href, _icon in ADMIN_NAV_ITEMS:
        # Company has its own full contextual sidebar; keep only the global admin destinations here.
        if key == "company":
            continue
        cls = "active" if key == active else ""
        links.append(f"<a class='{cls}' href='{href}'>{html_lib.escape(label)}</a>")
    return f"""<nav class='ua-ai-global' aria-label='التنقل الإداري العام'><a class='ua-ai-brand' href='/admin'><img src='{logo}' alt='Pakgat'></a>{''.join(links)}<form method='post' action='/admin/logout'><button type='submit'>تسجيل الخروج</button></form></nav>"""


def _apply_login(source: str, logo_data_uri: str) -> str:
    match = _BODY_RE.search(source)
    if not match:
        return _inject_css(source)
    logo = html_lib.escape(str(logo_data_uri or ""), quote=True)
    brand = f"<div class='ua-login-brand'><img src='{logo}' alt='Pakgat'><strong>لوحة إدارة Pakgat</strong><span>دخول آمن إلى نظام القسائم والشركة الذكية</span></div>"
    body = brand + match.group(2)
    replacement = _mark_body(match.group(1), "login") + body + match.group(3)
    rendered = source[: match.start()] + replacement + source[match.end() :]
    return _inject_css(rendered)


def _apply_ai(source: str, path: str, logo_data_uri: str) -> str:
    match = _BODY_RE.search(source)
    if not match:
        return _inject_css(source)
    body = match.group(2)
    bar = _ai_global_bar(path, logo_data_uri)
    if "class='ua-ai-global'" not in body and 'class="ua-ai-global"' not in body:
        body = bar + body
    replacement = _mark_body(match.group(1), "ai") + body + match.group(3)
    rendered = source[: match.start()] + replacement + source[match.end() :]
    return _inject_css(rendered)


def _apply_standard(source: str, path: str, logo_data_uri: str) -> str:
    match = _BODY_RE.search(source)
    if not match:
        return _inject_css(source)
    content = _TOPBAR_RE.sub("", match.group(2), count=1)
    shell = _standard_shell(content, path, _page_title(source), logo_data_uri)
    replacement = _mark_body(match.group(1), "standard") + shell + match.group(3)
    rendered = source[: match.start()] + replacement + source[match.end() :]
    return _inject_css(rendered)


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
