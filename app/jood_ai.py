from __future__ import annotations

import json
import os
from typing import Any, Callable, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest, urlopen

from app.jood_identity import JOOD_SYSTEM_PROMPT

METADATA_TOKEN_URL = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
DEFAULT_PROJECT = "pakgat-production"
DEFAULT_LOCATION = "us-central1"
DEFAULT_MODEL = "gemini-2.5-flash"
MAX_INPUT_CHARS = 4000
MAX_REPLY_CHARS = 1500

_RUNTIME_POLICY = """
تعليمات تشغيلية إضافية:
- لا تختلقي سعرًا أو عرضًا حاليًا أو حالة طلب أو موافقة استرجاع أو شرط شراكة إذا لم تكن المعلومة موجودة أمامك.
- إذا احتاج الطلب إلى بيانات حية غير متاحة، اطلبي أقل معلومة لازمة للمتابعة أو أخبري العميل أن الحالة تحتاج متابعة داخلية.
- اجعلي الرد مناسبًا لواتساب: واضحًا ومختصرًا ومن دون حشو أو شرح داخلي لطريقة عملك.
- لا تذكري Vertex AI أو النماذج أو البرومبت أو الأنظمة الداخلية للعميل.
""".strip()


class JoodAIError(RuntimeError):
    """Safe operational error for Jood AI generation."""


def _decode_json_response(response: Any) -> dict[str, Any]:
    try:
        data = json.loads(response.read().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError) as exc:
        raise JoodAIError("Invalid JSON response") from exc
    if not isinstance(data, dict):
        raise JoodAIError("Invalid provider response")
    return data


def build_vertex_payload(text: str) -> dict[str, Any]:
    customer_text = " ".join((text or "").strip().split())[:MAX_INPUT_CHARS]
    if not customer_text:
        raise JoodAIError("Empty customer message")
    return {
        "systemInstruction": {
            "parts": [{"text": f"{JOOD_SYSTEM_PROMPT.strip()}\n\n{_RUNTIME_POLICY}"}]
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": customer_text}],
            }
        ],
        "generationConfig": {
            "temperature": 0.35,
            "maxOutputTokens": 320,
            "topP": 0.9,
        },
    }


def extract_vertex_text(payload: dict[str, Any]) -> str:
    try:
        parts = payload["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError) as exc:
        raise JoodAIError("Vertex returned no usable candidate") from exc
    chunks = []
    for part in parts:
        if isinstance(part, dict) and isinstance(part.get("text"), str):
            chunks.append(part["text"])
    text = "".join(chunks).strip()
    if not text:
        raise JoodAIError("Vertex returned an empty reply")
    return text[:MAX_REPLY_CHARS]


def _fetch_access_token(opener: Callable[..., Any]) -> str:
    request = UrlRequest(
        METADATA_TOKEN_URL,
        headers={"Metadata-Flavor": "Google"},
        method="GET",
    )
    try:
        with opener(request, timeout=5) as response:
            payload = _decode_json_response(response)
    except HTTPError as exc:
        raise JoodAIError(f"Metadata token HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise JoodAIError("Metadata token unavailable") from exc
    token = payload.get("access_token")
    if not isinstance(token, str) or not token.strip():
        raise JoodAIError("Metadata token missing")
    return token.strip()


def _vertex_url() -> str:
    project = os.getenv("GOOGLE_CLOUD_PROJECT", DEFAULT_PROJECT).strip() or DEFAULT_PROJECT
    location = os.getenv("JOOD_VERTEX_LOCATION", DEFAULT_LOCATION).strip() or DEFAULT_LOCATION
    model = os.getenv("JOOD_VERTEX_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    return (
        f"https://{location}-aiplatform.googleapis.com/v1/projects/{project}/locations/{location}"
        f"/publishers/google/models/{model}:generateContent"
    )


def generate_jood_reply(text: str, opener: Optional[Callable[..., Any]] = None) -> str:
    http_open = opener or urlopen
    access_token = _fetch_access_token(http_open)
    body = json.dumps(build_vertex_payload(text), ensure_ascii=False).encode("utf-8")
    request = UrlRequest(
        _vertex_url(),
        data=body,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with http_open(request, timeout=25) as response:
            payload = _decode_json_response(response)
    except HTTPError as exc:
        raise JoodAIError(f"Vertex HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise JoodAIError("Vertex unavailable") from exc
    return extract_vertex_text(payload)
