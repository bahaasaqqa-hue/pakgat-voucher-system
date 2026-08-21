"""Final response-level Pakgat admin theme.

Imported last from ``main.py``. It changes only HTML presentation for `/admin`
GET pages and deliberately leaves route handlers, redirects, APIs, QR/images,
webhooks and business behavior untouched.
"""
from __future__ import annotations

import base64

from fastapi import Response
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


def _decoded_logo() -> tuple[bytes, str]:
    """Decode the already-approved embedded Pakgat logo once per request."""
    value = str(PAKGAT_LOGO_DATA_URI or "")
    if not value.startswith("data:") or "," not in value:
        return b"", "image/jpeg"
    header, payload = value.split(",", 1)
    media_type = header[5:].split(";", 1)[0] or "image/jpeg"
    try:
        return base64.b64decode(payload), media_type
    except Exception:
        return b"", media_type


@core.app.get("/admin/theme/logo", include_in_schema=False)
def unified_admin_logo():
    """Serve the approved Pakgat logo without repeating Base64 in every HTML page."""
    content, media_type = _decoded_logo()
    return Response(content=content, media_type=media_type, headers={"Cache-Control": "public, max-age=86400"})


@core.app.middleware("http")
async def unified_admin_theme_middleware(request, call_next):
    response = await call_next(request)
    path = request.url.path

    if not path.startswith("/admin"):
        return response

    # Keep HEAD and all state-changing actions completely untouched.
    if request.method.upper() != "GET":
        return response

    # Auth redirects and route redirects must remain byte-for-byte route semantics.
    if 300 <= response.status_code < 400:
        return response

    content_type = response.headers.get("content-type", "").lower()
    if "text/html" not in content_type:
        return response

    body = await _response_body(response)
    source = body.decode("utf-8", errors="replace")
    rendered = apply_admin_theme(source, path, "/admin/theme/logo")

    return HTMLResponse(
        content=rendered,
        status_code=response.status_code,
        headers=_safe_html_headers(response),
        background=getattr(response, "background", None),
    )
