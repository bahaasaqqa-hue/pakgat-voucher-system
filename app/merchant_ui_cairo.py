"""Cairo typography and Arabic presentation polish for Pakgat admin finance UI.

Presentation only: this module does not change merchant, voucher, settlement,
Salla, WhatsLoop, Jood, campaign, QR or API business behavior.
"""
from __future__ import annotations

import re

from fastapi.responses import HTMLResponse

from app import application as core


CAIRO_ADMIN_HEAD = r"""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
<style id="pakgat-cairo-admin">
body[data-unified-admin-theme],
body[data-unified-admin-theme] button,input,select,textarea{
  font-family:'Cairo',Tahoma,Arial,sans-serif!important;
}
body[data-unified-admin-theme] .ua-top h1{font-weight:800!important;letter-spacing:0!important}
body[data-unified-admin-theme] .ua-content{padding-top:16px!important}
body[data-unified-admin-theme] .ua-content h1{
  font-family:'Cairo',Tahoma,Arial,sans-serif!important;
  font-size:32px!important;
  line-height:1.3!important;
  font-weight:800!important;
  letter-spacing:0!important;
  margin:0 0 6px!important;
}
body[data-unified-admin-theme] .ua-content h2{
  font-family:'Cairo',Tahoma,Arial,sans-serif!important;
  font-size:21px!important;
  line-height:1.4!important;
  font-weight:700!important;
  letter-spacing:0!important;
  margin-top:0!important;
}
body[data-unified-admin-theme] .ua-content h3{font-weight:700!important}
body[data-unified-admin-theme] .ua-content p,
body[data-unified-admin-theme] .ua-content td,
body[data-unified-admin-theme] .ua-content th{line-height:1.65!important}
body[data-unified-admin-theme] .ua-content th{font-weight:700!important;font-size:12px!important}
body[data-unified-admin-theme] .ua-content td{font-weight:500!important;font-size:13px!important}
body[data-unified-admin-theme] .ua-content strong{font-weight:700}
body[data-unified-admin-theme] .ua-content .btn,
body[data-unified-admin-theme] .ua-content button{font-weight:700!important}
body[data-unified-admin-theme] .ua-content main.wrap>p.muted{margin:0 0 16px!important}
body[data-unified-admin-theme] .ua-content main.wrap>div:first-child{margin-bottom:14px!important}
body[data-unified-admin-theme] .ua-content .card{margin-top:0}
body[data-unified-admin-theme] .ua-content .grid .card strong{font-variant-numeric:tabular-nums}
@media(max-width:700px){
  body[data-unified-admin-theme] .ua-content h1{font-size:26px!important}
  body[data-unified-admin-theme] .ua-content h2{font-size:19px!important}
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


def _translate_exact_text_nodes(source: str) -> str:
    rendered = source
    for original, translated in _TEXT_NODE_TRANSLATIONS.items():
        pattern = re.compile(r">(\s*)" + re.escape(original) + r"(\s*)<")
        rendered = pattern.sub(lambda match: f">{match.group(1)}{translated}{match.group(2)}<", rendered)
    return rendered


def apply_merchant_ui_polish(source: str, path: str) -> str:
    """Apply Cairo globally to admin HTML and Arabic finance labels on finance pages."""
    if not str(path or "").startswith("/admin"):
        return source

    rendered = str(source or "")
    if "id=\"pakgat-cairo-admin\"" not in rendered:
        if "</head>" in rendered:
            rendered = rendered.replace("</head>", CAIRO_ADMIN_HEAD + "</head>", 1)
        else:
            rendered = CAIRO_ADMIN_HEAD + rendered

    is_finance_page = path == "/admin" or any(path.startswith(prefix) for prefix in _FINANCE_PATH_PREFIXES)
    if not is_finance_page:
        return rendered

    for original, translated in _PHRASE_TRANSLATIONS:
        rendered = rendered.replace(original, translated)
    return _translate_exact_text_nodes(rendered)


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

    if not path.startswith("/admin") or request.method.upper() != "GET":
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
