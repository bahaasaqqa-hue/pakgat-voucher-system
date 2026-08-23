from __future__ import annotations

import asyncio
import base64
import json
from typing import Any, Callable, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest, urlopen

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import application as core
from app.jood_ai import JoodAIError, _decode_json_response, _fetch_access_token, _vertex_url, extract_vertex_text
from app.jood_company_ops import JoodCallSession

MAX_AUDIO_BYTES = 4_000_000
MIN_AUDIO_BYTES = 128
ALLOWED_AUDIO_TYPES = {
    "audio/webm",
    "audio/ogg",
    "audio/mp4",
    "audio/mpeg",
    "audio/wav",
    "audio/x-wav",
}

_TRANSCRIBE_PROMPT = (
    "Transcribe only the spoken words in this short call-audio clip. "
    "Return only the transcript, with no labels, timestamps, quotes, Markdown, or commentary. "
    "The speaker may use Saudi Arabic, other Arabic dialects, English, or a mix. "
    "Do not invent words from noise. If there is no intelligible speech, return exactly <NO_SPEECH>."
)


class JoodVoiceSTTError(RuntimeError):
    """Safe operational error for Jood server-side speech transcription."""


def _require_admin_api(request: Request) -> None:
    try:
        core.require_admin(request)
    except HTTPException as exc:
        raise HTTPException(status_code=401, detail="Admin authentication required") from exc


def normalize_transcript(value: Any) -> str:
    clean = " ".join(str(value or "").strip().split())
    if not clean:
        return ""
    marker = clean.strip("` \t\r\n\"'").upper()
    if marker in {"<NO_SPEECH>", "NO_SPEECH", "[NO_SPEECH]"}:
        return ""
    return clean[:4000]


def build_stt_payload(audio: bytes, mime_type: str) -> dict[str, Any]:
    if not isinstance(audio, (bytes, bytearray)) or not audio:
        raise ValueError("Audio bytes are required")
    mime = str(mime_type or "").split(";", 1)[0].strip().lower()
    if mime not in ALLOWED_AUDIO_TYPES:
        raise ValueError("Unsupported audio type")
    return {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": _TRANSCRIBE_PROMPT},
                    {
                        "inlineData": {
                            "mimeType": mime,
                            "data": base64.b64encode(bytes(audio)).decode("ascii"),
                        }
                    },
                ],
            }
        ],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 256,
            "topP": 0.1,
        },
    }


def transcribe_jood_audio(
    audio: bytes,
    mime_type: str,
    opener: Optional[Callable[..., Any]] = None,
) -> str:
    http_open = opener or urlopen
    try:
        access_token = _fetch_access_token(http_open)
        body = json.dumps(build_stt_payload(audio, mime_type), ensure_ascii=False).encode("utf-8")
    except (JoodAIError, ValueError) as exc:
        raise JoodVoiceSTTError(str(exc)) from exc

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
        with http_open(request, timeout=30) as response:
            payload = _decode_json_response(response)
        return normalize_transcript(extract_vertex_text(payload))
    except HTTPError as exc:
        raise JoodVoiceSTTError(f"Vertex STT HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise JoodVoiceSTTError("Vertex STT unavailable") from exc
    except JoodAIError as exc:
        raise JoodVoiceSTTError(str(exc)) from exc


@core.app.post("/admin/company/jood/voice/{session_id}/stt/health")
async def jood_voice_stt_health(session_id: int, request: Request, db: Session = Depends(core.get_db)):
    _require_admin_api(request)
    session = db.get(JoodCallSession, session_id)
    if not session or session.status != "active":
        raise HTTPException(status_code=404, detail="Active voice session not found")
    try:
        token = await asyncio.to_thread(_fetch_access_token, urlopen)
    except JoodAIError as exc:
        core.log_event(
            db,
            "jood_voice_stt_health_failed",
            details=f"session={session.id}; error={str(exc)[:180]}",
        )
        raise HTTPException(status_code=502, detail="Vertex authentication unavailable") from exc
    return JSONResponse(
        {
            "success": True,
            "session_id": session.id,
            "ready": bool(token),
            "provider": "vertex",
        }
    )


@core.app.post("/admin/company/jood/voice/{session_id}/stt")
async def jood_voice_stt(session_id: int, request: Request, db: Session = Depends(core.get_db)):
    _require_admin_api(request)
    session = db.get(JoodCallSession, session_id)
    if not session or session.status != "active":
        raise HTTPException(status_code=404, detail="Active voice session not found")

    mime_type = str(request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if mime_type not in ALLOWED_AUDIO_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported audio type")

    audio = await request.body()
    if len(audio) < MIN_AUDIO_BYTES:
        raise HTTPException(status_code=400, detail="Audio clip is empty")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Audio clip is too large")

    try:
        transcript = await asyncio.to_thread(transcribe_jood_audio, audio, mime_type)
    except JoodVoiceSTTError as exc:
        core.log_event(
            db,
            "jood_voice_stt_failed",
            details=f"session={session.id}; error={str(exc)[:180]}",
        )
        raise HTTPException(status_code=502, detail="Jood speech transcription failed") from exc

    return JSONResponse(
        {
            "success": True,
            "session_id": session.id,
            "transcript": transcript,
            "speech_detected": bool(transcript),
        }
    )
