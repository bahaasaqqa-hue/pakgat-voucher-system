from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app import application as core
from app import jood_voice_bridge_ui as base
from app.jood_company_ops import (
    CompanyContact,
    JoodCallSession,
    append_turn,
    conversation_key_for,
)


def _require_admin_api(request: Request) -> None:
    try:
        core.require_admin(request)
    except HTTPException as exc:
        raise HTTPException(status_code=401, detail="Admin authentication required") from exc


def initial_voice_opening(contact_type: str) -> str:
    if str(contact_type or "").strip().lower() == "merchant":
        return (
            "السلام عليكم، معك جود من بكجات. أتواصل معكم بخصوص فرصة تعاون مع منصة بكجات "
            "في الرياض، هل الوقت مناسب لدقيقة؟"
        )
    return (
        "السلام عليكم، معك جود من بكجات. أتواصل معك من منصة بكجات في الرياض، "
        "هل الوقت مناسب لدقيقة؟"
    )


@core.app.post("/admin/company/jood/voice/{session_id}/start")
def start_voice_conversation(session_id: int, request: Request, db: Session = Depends(core.get_db)):
    _require_admin_api(request)
    session = db.get(JoodCallSession, session_id)
    if not session or session.status != "active":
        raise HTTPException(status_code=404, detail="Active voice session not found")
    contact = db.get(CompanyContact, session.contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    # Do not repeat the opening after a refresh/restart if this session already has dialogue.
    if str(session.transcript or "").strip():
        return JSONResponse({"success": True, "reply": "", "already_started": True})

    reply = initial_voice_opening(contact.contact_type)
    conversation_key = conversation_key_for("voice", contact.id)
    append_turn(db, contact.id, "voice", "assistant", reply, conversation_key)
    session.transcript = base.append_transcript_line(session.transcript or "", "jood", reply)
    db.commit()
    return JSONResponse({"success": True, "reply": reply, "already_started": False})


def build_live_voice_bridge_script(session_id: int) -> str:
    start_url = f"/admin/company/jood/voice/{int(session_id)}/start"
    turn_url = f"/admin/company/jood/voice/{int(session_id)}/turn"
    tts_url = f"/admin/company/jood/voice/{int(session_id)}/tts"
    finish_url = f"/admin/company/jood/voice/{int(session_id)}/finish"
    return f"""
const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition = null;
let recognizing = false;
let speaking = false;
let started = false;
let inputStream = null;
let audioTrack = null;
let joodAudioContext = null;
let joodAudioSource = null;

const statusEl = document.getElementById('voice-status');
const transcriptEl = document.getElementById('voice-transcript');
const replyEl = document.getElementById('voice-reply');
const startBtn = document.getElementById('start-listening');
const stopBtn = document.getElementById('stop-listening');

function setStatus(text) {{
  if (statusEl) statusEl.textContent = text;
}}

function stopInputStream() {{
  if (inputStream) {{
    for (const track of inputStream.getTracks()) track.stop();
  }}
  inputStream = null;
  audioTrack = null;
}}

function stopJoodAudio() {{
  if (joodAudioSource) {{
    try {{ joodAudioSource.stop(); }} catch (_) {{}}
    try {{ joodAudioSource.disconnect(); }} catch (_) {{}}
  }}
  joodAudioSource = null;
}}

async function ensureAudioContext() {{
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) throw new Error('AudioContext غير متاح في هذا المتصفح');
  if (!joodAudioContext) joodAudioContext = new AudioContextClass();
  if (joodAudioContext.state === 'suspended') await joodAudioContext.resume();
  return joodAudioContext;
}}

async function prepareVoicemeeterB1() {{
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !navigator.mediaDevices.enumerateDevices) {{
    throw new Error('الوصول لأجهزة الصوت غير متاح في المتصفح');
  }}

  // First request unlocks device labels after the user grants microphone permission.
  const probe = await navigator.mediaDevices.getUserMedia({{audio: true}});
  for (const track of probe.getTracks()) track.stop();

  const devices = await navigator.mediaDevices.enumerateDevices();
  const inputs = devices.filter(d => d.kind === 'audioinput');
  const preferred = inputs.find(d => {{
    const label = (d.label || '').toLowerCase();
    return label.includes('voicemeeter')
      && !label.includes('b2')
      && !label.includes('aux')
      && (label.includes('out b1') || label.includes('output') || label.includes('b1'));
  }});
  if (!preferred) {{
    const available = inputs.map(d => d.label || 'Audio input').join(' | ');
    throw new Error('لم أجد Voicemeeter B1. الأجهزة المتاحة: ' + available);
  }}

  stopInputStream();
  inputStream = await navigator.mediaDevices.getUserMedia({{
    audio: {{
      deviceId: {{exact: preferred.deviceId}},
      echoCancellation: false,
      noiseSuppression: false,
      autoGainControl: false
    }}
  }});
  audioTrack = inputStream.getAudioTracks()[0] || null;
  if (!audioTrack) throw new Error('تعذر فتح مسار Voicemeeter B1');
  setStatus('تم ربط استماع جود بـ ' + preferred.label);
  return preferred.label;
}}

async function fetchJson(url, body) {{
  const response = await fetch(url, {{
    method: 'POST',
    credentials: 'same-origin',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(body || {{}})
  }});
  let data = {{}};
  try {{ data = await response.json(); }} catch (_) {{}}
  if (!response.ok) throw new Error(data.detail || ('HTTP ' + response.status));
  return data;
}}

async function startCall() {{
  return await fetchJson('{start_url}', {{}});
}}

async function sendTurn(text) {{
  return await fetchJson('{turn_url}', {{text}});
}}

async function speakReply(text) {{
  const clean = (text || '').trim();
  if (!clean) return;
  speaking = true;
  if (recognition && recognizing) recognition.stop();
  stopJoodAudio();
  setStatus('جود تولّد صوت Zariyah...');
  try {{
    const response = await fetch('{tts_url}', {{
      method: 'POST',
      credentials: 'same-origin',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{text: clean}})
    }});
    if (!response.ok) {{
      let detail = 'TTS HTTP ' + response.status;
      try {{ detail = (await response.json()).detail || detail; }} catch (_) {{}}
      throw new Error(detail);
    }}
    const context = await ensureAudioContext();
    const encoded = await response.arrayBuffer();
    const decoded = await context.decodeAudioData(encoded.slice(0));
    await new Promise((resolve, reject) => {{
      const source = context.createBufferSource();
      joodAudioSource = source;
      source.buffer = decoded;
      source.connect(context.destination);
      source.onended = () => {{
        if (joodAudioSource === source) joodAudioSource = null;
        resolve();
      }};
      try {{
        setStatus('جود تتكلم الآن بصوت Zariyah...');
        source.start(0);
      }} catch (err) {{
        reject(err);
      }}
    }});
  }} finally {{
    speaking = false;
  }}
}}

function startRecognition() {{
  if (!Recognition || !started || speaking || recognizing || !audioTrack) return;
  recognition = new Recognition();
  recognition.lang = 'ar-SA';
  recognition.continuous = false;
  recognition.interimResults = false;
  recognition.maxAlternatives = 1;
  recognition.onstart = () => {{
    recognizing = true;
    setStatus('جود تستمع للطرف الآخر من Voicemeeter B1...');
  }};
  recognition.onresult = async event => {{
    const text = (event.results[0][0].transcript || '').trim();
    if (!text) return;
    transcriptEl.textContent = text;
    setStatus('جود تفهم الكلام وتجهز الرد...');
    try {{
      const data = await sendTurn(text);
      replyEl.textContent = data.reply || '';
      await speakReply(data.reply || '');
    }} catch (err) {{
      setStatus('تعذر إكمال الدور الصوتي: ' + err.message);
      started = false;
    }}
  }};
  recognition.onerror = event => {{
    if (started && event.error !== 'aborted') setStatus('خطأ استماع: ' + event.error);
  }};
  recognition.onend = () => {{
    recognizing = false;
    if (started && !speaking) setTimeout(startRecognition, 250);
  }};
  try {{
    recognition.start(audioTrack);
  }} catch (err) {{
    recognizing = false;
    started = false;
    setStatus('تعذر تمرير Voicemeeter B1 إلى SpeechRecognition: ' + err.message);
  }}
}}

startBtn.addEventListener('click', async () => {{
  if (!Recognition) {{
    setStatus('SpeechRecognition غير متاح. افتح الصفحة في Microsoft Edge الحديث.');
    return;
  }}
  if (started) return;
  startBtn.disabled = true;
  try {{
    started = true;
    setStatus('جود تجهز مسار Voicemeeter B1...');
    await prepareVoicemeeterB1();
    await ensureAudioContext();
    const opening = await startCall();
    if (opening.reply) {{
      replyEl.textContent = opening.reply;
      await speakReply(opening.reply);
    }}
    startRecognition();
  }} catch (err) {{
    started = false;
    setStatus('تعذر بدء جود: ' + err.message);
  }} finally {{
    startBtn.disabled = false;
  }}
}});

stopBtn.addEventListener('click', () => {{
  started = false;
  if (recognition && recognizing) recognition.stop();
  stopJoodAudio();
  stopInputStream();
  setStatus('متوقف.');
}});

async function finishCall(outcome) {{
  started = false;
  if (recognition && recognizing) recognition.stop();
  stopJoodAudio();
  stopInputStream();
  try {{
    const data = await fetchJson('{finish_url}', {{outcome}});
    setStatus('تم حفظ Call Log: ' + (data.outcome || outcome));
    if (data.summary) replyEl.textContent = data.summary;
  }} catch (err) {{
    setStatus('تعذر إغلاق المكالمة: ' + err.message);
  }}
}}
window.finishJoodCall = finishCall;

setStatus('جود جاهزة · المصدر المطلوب Voicemeeter B1 · الصوت Zariyah عبر Pakgat Voice TTS');
""".strip()


def _live_voice_bridge_page(session_id: int, request: Request, db: Session = Depends(core.get_db)):
    response = base.voice_bridge_page(session_id, request, db)
    if not isinstance(response, HTMLResponse):
        return response

    html = bytes(response.body).decode("utf-8", errors="replace")
    old_script = base.build_voice_bridge_script(session_id)
    old_tag = f"<script>{old_script}</script>"
    new_tag = f"<script>{build_live_voice_bridge_script(session_id)}</script>"
    if old_tag not in html:
        raise RuntimeError("Jood base voice script was not found in bridge page")
    html = html.replace(old_tag, new_tag, 1)
    html = html.replace(
        "جارٍ فحص Zariyah...",
        "جود جاهزة · اربط الاستماع بـ Voicemeeter B1 ثم ابدأ المكالمة.",
        1,
    )
    html = html.replace(
        "Edge يجب أن يأخذ صوت الطرف الآخر من Voicemeeter، ويخرج صوته إلى AUX → B2.",
        "جود ستلتقط صوت الطرف الآخر تلقائيًا من Voicemeeter B1، ويخرج صوتها إلى AUX → B2.",
        1,
    )
    return HTMLResponse(content=html, status_code=response.status_code)


def install_live_bridge_patch() -> None:
    target = "/admin/company/jood/voice/{session_id}/bridge"
    for route in core.app.routes:
        if getattr(route, "path", None) != target or "GET" not in (getattr(route, "methods", set()) or set()):
            continue
        route.endpoint = _live_voice_bridge_page
        dependant = getattr(route, "dependant", None)
        if dependant is not None:
            dependant.call = _live_voice_bridge_page
        return
    raise RuntimeError("Jood voice bridge route was not registered before live bridge patch")


install_live_bridge_patch()
