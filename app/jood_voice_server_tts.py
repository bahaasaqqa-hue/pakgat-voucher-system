from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app import application as core
from app import jood_voice_bridge_ui as base
from app.jood_company_ops import JoodCallSession

JOOD_VOICE_NAME = base.JOOD_VOICE_NAME
JOOD_TTS_RATE = "-2%"
MAX_TTS_CHARS = 1500


def _require_admin_api(request: Request) -> None:
    try:
        core.require_admin(request)
    except HTTPException as exc:
        raise HTTPException(status_code=401, detail="Admin authentication required") from exc


async def synthesize_zariyah_mp3(
    text: str,
    communicator_factory: Optional[Callable[..., Any]] = None,
) -> bytes:
    """Generate one Zariyah MP3 payload without exposing a browser-voice dependency."""
    clean = " ".join(str(text or "").strip().split())[:MAX_TTS_CHARS]
    if not clean:
        raise ValueError("TTS text is required")

    if communicator_factory is None:
        try:
            import edge_tts  # type: ignore
        except ImportError as exc:
            raise RuntimeError("edge-tts is not installed") from exc
        communicator_factory = edge_tts.Communicate

    communicator = communicator_factory(
        clean,
        JOOD_VOICE_NAME,
        rate=JOOD_TTS_RATE,
        volume="+0%",
        pitch="+0Hz",
    )
    audio_parts: list[bytes] = []
    async for chunk in communicator.stream():
        if str(chunk.get("type") or "").lower() == "audio" and chunk.get("data"):
            audio_parts.append(bytes(chunk["data"]))
    if not audio_parts:
        raise RuntimeError("Zariyah returned no audio")
    return b"".join(audio_parts)


@core.app.post("/admin/company/jood/voice/{session_id}/tts")
async def jood_voice_tts(session_id: int, request: Request, db: Session = Depends(core.get_db)):
    _require_admin_api(request)
    session = db.get(JoodCallSession, session_id)
    if not session or session.status != "active":
        raise HTTPException(status_code=404, detail="Active voice session not found")
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="JSON body required") from exc
    text = " ".join(str((payload or {}).get("text") or "").strip().split())[:MAX_TTS_CHARS]
    if not text:
        raise HTTPException(status_code=400, detail="TTS text is required")

    try:
        audio = await synthesize_zariyah_mp3(text)
    except Exception as exc:
        core.log_event(
            db,
            "jood_voice_tts_failed",
            details=f"session={session.id}; error_type={type(exc).__name__}; error={str(exc)[:140]}",
        )
        raise HTTPException(status_code=502, detail="Zariyah TTS generation failed") from exc

    return Response(
        content=audio,
        media_type="audio/mpeg",
        headers={
            "Cache-Control": "no-store",
            "X-Jood-Voice": JOOD_VOICE_NAME,
        },
    )
