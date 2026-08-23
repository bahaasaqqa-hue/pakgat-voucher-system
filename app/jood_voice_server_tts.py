from __future__ import annotations

import json
from typing import Any, Callable, Optional

from fastapi import Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
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


def build_server_tts_overlay(session_id: int) -> str:
    tts_url = f"/admin/company/jood/voice/{int(session_id)}/tts"
    template = r"""
<script>
(() => {
  const JOOD_TTS_URL = __TTS_URL__;
  let joodAudioContext = null;
  let joodAudioSource = null;

  async function ensureJoodAudioContext() {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) throw new Error('AudioContext غير متاح في Edge');
    if (!joodAudioContext) joodAudioContext = new AudioContextClass();
    if (joodAudioContext.state === 'suspended') await joodAudioContext.resume();
    return joodAudioContext;
  }

  function stopJoodAudio() {
    if (joodAudioSource) {
      try { joodAudioSource.stop(); } catch (_) {}
      try { joodAudioSource.disconnect(); } catch (_) {}
      joodAudioSource = null;
    }
  }

  window.speakReply = async function speakReplyViaPakgatTTS(text) {
    speaking = true;
    if (recognition) recognition.stop();
    stopJoodAudio();
    statusEl.textContent = 'جود تولّد صوت Zariyah...';
    try {
      const response = await fetch(JOOD_TTS_URL, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({text: text || ''})
      });
      if (!response.ok) {
        let detail = 'TTS HTTP ' + response.status;
        try { detail = (await response.json()).detail || detail; } catch (_) {}
        throw new Error(detail);
      }
      const context = await ensureJoodAudioContext();
      const encoded = await response.arrayBuffer();
      const decoded = await context.decodeAudioData(encoded.slice(0));
      await new Promise((resolve, reject) => {
        const source = context.createBufferSource();
        joodAudioSource = source;
        source.buffer = decoded;
        source.connect(context.destination);
        source.onended = () => {
          if (joodAudioSource === source) joodAudioSource = null;
          resolve();
        };
        try {
          statusEl.textContent = 'جود تتكلم الآن بصوت Zariyah...';
          source.start(0);
        } catch (err) {
          reject(err);
        }
      });
      speaking = false;
      statusEl.textContent = 'جود انتهت؛ أستمع للطرف الآخر.';
      if (started) startRecognition();
    } catch (err) {
      speaking = false;
      statusEl.textContent = 'تعذر تشغيل Zariyah: ' + err.message;
      throw err;
    }
  };

  if (startBtn) {
    startBtn.addEventListener('click', () => {
      ensureJoodAudioContext().catch(err => {
        statusEl.textContent = 'تعذر تهيئة الصوت: ' + err.message;
      });
    });
  }
  if (stopBtn) stopBtn.addEventListener('click', stopJoodAudio);

  const originalFinish = window.finishJoodCall;
  if (originalFinish) {
    window.finishJoodCall = async function(outcome) {
      stopJoodAudio();
      return originalFinish(outcome);
    };
  }

  statusEl.textContent = 'Zariyah جاهزة عبر Pakgat Voice TTS · ar-SA · نصف مزدوج';
  statusEl.dataset.voiceReady = '1';
})();
</script>
""".strip()
    return template.replace("__TTS_URL__", json.dumps(tts_url))


def _server_tts_voice_bridge_page(session_id: int, request: Request, db: Session = Depends(core.get_db)):
    response = base.voice_bridge_page(session_id, request, db)
    if not isinstance(response, HTMLResponse):
        return response
    html = bytes(response.body).decode("utf-8", errors="replace")
    overlay = build_server_tts_overlay(session_id)
    if "</body>" in html:
        html = html.replace("</body>", overlay + "</body>", 1)
    else:
        html += overlay
    html = html.replace(
        "لن يستخدم الجسر صوتًا آخر بصمت إذا لم تكن Zariyah متاحة داخل Edge Web Speech.",
        "Zariyah تُولَّد من Pakgat Voice TTS وتُشغَّل داخل Edge إلى Voicemeeter AUX → B2.",
    )
    return HTMLResponse(content=html, status_code=response.status_code)


def install_server_tts_bridge_patch() -> None:
    target = "/admin/company/jood/voice/{session_id}/bridge"
    for route in core.app.routes:
        if getattr(route, "path", None) != target or "GET" not in (getattr(route, "methods", set()) or set()):
            continue
        route.endpoint = _server_tts_voice_bridge_page
        dependant = getattr(route, "dependant", None)
        if dependant is not None:
            dependant.call = _server_tts_voice_bridge_page
        return
    raise RuntimeError("Jood voice bridge route was not registered before server TTS patch")


install_server_tts_bridge_patch()
