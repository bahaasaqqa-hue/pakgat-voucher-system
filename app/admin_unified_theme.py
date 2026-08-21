"""Final response-level Pakgat admin theme.

Imported last from ``main.py``. It changes only HTML presentation for `/admin`
GET pages and deliberately leaves route handlers, redirects, APIs, QR/images,
webhooks and business behavior untouched.
"""
from __future__ import annotations

from fastapi.responses import HTMLResponse

from app import application as core
from app.admin_theme_core import apply_admin_theme
from app.ai_company_mission_control_ui import PAKGAT_LOGO_DATA_URI


async def _response_body(response) -> bytes:
    """Consume call_next's streaming HTML body only after type/status guards pass."""
    iterator = getattr(response, "body_iterator", None)
    if iterator is not None:
        chunks: list[bytes] = []
        async for chunk in iterator:
            if isinstance(chunk, bytes):
                chunks.append(chunk)
            else:
                chunks.append(str(chunk).encode("utf-8"))
        return b"".join(chunks)
    body = getattr(response, "body", b"")
    return body if isinstance(body, bytes) else bytes(body or b"")


def _safe_html_headers(response) -> dict[str, str]:
    """Keep ordinary response headers; HTMLResponse recalculates body headers."""
    blocked = {"content-length", "content-type"}
    return {
        key: value
        for key, value in response.headers.items()
        if key.lower() not in blocked
    }


@core.app.middleware("http")
async def unified_admin_theme_middleware(request, call_next):
    response = await call_next(request)
    path = request.url.path

    if not path.startswith("/admin"):
        return response

    # Auth redirects and POST action redirects must remain byte-for-byte route semantics.
    if 300 <= response.status_code < 400:
        return response

    content_type = response.headers.get("content-type", "").lower()
    if "text/html" not in content_type:
        return response

    body = await _response_body(response)
    source = body.decode("utf-8", errors="replace")
    rendered = apply_admin_theme(source, path, PAKGAT_LOGO_DATA_URI)

    return HTMLResponse(
        content=rendered,
        status_code=response.status_code,
        headers=_safe_html_headers(response),
        background=getattr(response, "background", None),
    )
