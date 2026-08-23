from __future__ import annotations

import json

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse
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

    if str(session.transcript or "").strip():
        reply = initial_voice_opening(contact.contact_type)
        return JSONResponse({"success": True, "reply": reply, "already_started": True})

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
    stt_url = f"/admin/company/jood/voice/{int(session_id)}/stt"
    stt_health_url = f"/admin/company/jood/voice/{int(session_id)}/stt/health"
    finish_url = f"/admin/company/jood/voice/{int(session_id)}/finish"

    template = r"""
const START_URL = __START_URL__;
const TURN_URL = __TURN_URL__;
const TTS_URL = __TTS_URL__;
const STT_URL = __STT_URL__;
const STT_HEALTH_URL = __STT_HEALTH_URL__;
const FINISH_URL = __FINISH_URL__;

let speaking = false;
let started = false;
let diagnosticsReady = false;
let inputStream = null;
let inputAudioContext = null;
let inputSource = null;
let analyser = null;
let currentRecorder = null;
let captureGeneration = 0;
let joodAudioContext = null;
let joodAudioSource = null;

const statusEl = document.getElementById('voice-status');
const transcriptEl = document.getElementById('voice-transcript');
const replyEl = document.getElementById('voice-reply');
const startBtn = document.getElementById('start-jood');
const stopBtn = document.getElementById('stop-listening');

const SPEECH_THRESHOLD = 0.012;
const SILENCE_MS = 850;
const MAX_UTTERANCE_MS = 12000;
const WAIT_FOR_SPEECH_MS = 15000;

function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function setStatus(text) {
  if (statusEl) statusEl.textContent = text;
}

function setDiagnostic(key, state, text) {
  const el = document.getElementById('diagnostic-' + key);
  if (!el) return;
  const icon = state === 'ok' ? '✅' : state === 'fail' ? '❌' : state === 'warn' ? '⚠️' : '⏳';
  el.textContent = icon + ' ' + text;
  el.dataset.state = state;
  if (state === 'ok') el.style.color = '#166534';
  else if (state === 'fail') el.style.color = '#991b1b';
  else if (state === 'warn') el.style.color = '#92400e';
  else el.style.color = '#475569';
}

function stopJoodAudio() {
  if (joodAudioSource) {
    try { joodAudioSource.stop(); } catch (_) {}
    try { joodAudioSource.disconnect(); } catch (_) {}
  }
  joodAudioSource = null;
}

function stopCurrentRecorder() {
  if (currentRecorder && currentRecorder.state !== 'inactive') {
    try { currentRecorder.stop(); } catch (_) {}
  }
}

async function stopInputStream() {
  stopCurrentRecorder();
  if (inputSource) {
    try { inputSource.disconnect(); } catch (_) {}
  }
  inputSource = null;
  analyser = null;
  if (inputStream) {
    for (const track of inputStream.getTracks()) track.stop();
  }
  inputStream = null;
  if (inputAudioContext) {
    try { await inputAudioContext.close(); } catch (_) {}
  }
  inputAudioContext = null;
}

async function ensureOutputAudioContext() {
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) throw new Error('AudioContext غير متاح في Chrome');
  if (!joodAudioContext) joodAudioContext = new AudioContextClass();
  if (joodAudioContext.state === 'suspended') await joodAudioContext.resume();
  return joodAudioContext;
}

async function prepareVoicemeeterB1() {
  if (!window.MediaRecorder) throw new Error('MediaRecorder غير متاح في Chrome');
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !navigator.mediaDevices.enumerateDevices) {
    throw new Error('الوصول لأجهزة الصوت غير متاح في Chrome');
  }

  setDiagnostic('b1', 'pending', 'فحص مدخل المكالمة...');
  const probe = await navigator.mediaDevices.getUserMedia({audio: true});
  for (const track of probe.getTracks()) track.stop();

  const devices = await navigator.mediaDevices.enumerateDevices();
  const inputs = devices.filter(d => d.kind === 'audioinput');
  const preferred = inputs.find(d => {
    const label = (d.label || '').toLowerCase();
    return label.includes('voicemeeter')
      && !label.includes('b2')
      && !label.includes('aux')
      && (label.includes('out b1') || label.includes('output') || label.includes('b1'));
  });
  if (!preferred) {
    const available = inputs.map(d => d.label || 'Audio input').join(' | ');
    setDiagnostic('b1', 'fail', 'لم يتم العثور على مدخل المكالمة');
    throw new Error('لم أجد Voicemeeter B1. الأجهزة المتاحة: ' + available);
  }

  await stopInputStream();
  inputStream = await navigator.mediaDevices.getUserMedia({
    audio: {
      deviceId: {exact: preferred.deviceId},
      echoCancellation: false,
      noiseSuppression: false,
      autoGainControl: false
    }
  });
  const track = inputStream.getAudioTracks()[0] || null;
  if (!track) throw new Error('تعذر فتح مدخل المكالمة');

  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) throw new Error('AudioContext غير متاح في Chrome');
  inputAudioContext = new AudioContextClass();
  if (inputAudioContext.state === 'suspended') await inputAudioContext.resume();
  inputSource = inputAudioContext.createMediaStreamSource(inputStream);
  analyser = inputAudioContext.createAnalyser();
  analyser.fftSize = 1024;
  analyser.smoothingTimeConstant = 0.15;
  inputSource.connect(analyser);

  setDiagnostic('b1', 'ok', 'مدخل المكالمة جاهز');
  setDiagnostic('signal', 'pending', 'بانتظار صوت الطرف الآخر');
  return preferred.label;
}

function currentRms() {
  if (!analyser) return 0;
  const data = new Float32Array(analyser.fftSize);
  analyser.getFloatTimeDomainData(data);
  let sum = 0;
  for (let i = 0; i < data.length; i += 1) sum += data[i] * data[i];
  return Math.sqrt(sum / data.length);
}

async function fetchJson(url, body) {
  const response = await fetch(url, {
    method: 'POST',
    credentials: 'same-origin',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body || {})
  });
  let data = {};
  try { data = await response.json(); } catch (_) {}
  if (!response.ok) throw new Error(data.detail || ('HTTP ' + response.status));
  return data;
}

async function checkSttHealth() {
  setDiagnostic('stt', 'pending', 'فحص فهم الكلام...');
  const data = await fetchJson(STT_HEALTH_URL, {});
  if (!data.ready) throw new Error('STT غير جاهز');
  setDiagnostic('stt', 'ok', 'فهم الكلام جاهز');
}

async function checkTtsHealth() {
  setDiagnostic('tts', 'pending', 'فحص صوت جود...');
  const response = await fetch(TTS_URL, {
    method: 'POST',
    credentials: 'same-origin',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({text: 'اختبار جود'})
  });
  if (!response.ok) {
    let detail = 'TTS HTTP ' + response.status;
    try { detail = (await response.json()).detail || detail; } catch (_) {}
    setDiagnostic('tts', 'fail', 'صوت جود غير جاهز');
    throw new Error(detail);
  }
  const audio = await response.arrayBuffer();
  if (!audio || audio.byteLength < 128) {
    setDiagnostic('tts', 'fail', 'صوت جود رجع ملفًا فارغًا');
    throw new Error('TTS returned empty audio');
  }
  setDiagnostic('tts', 'ok', 'صوت جود Zariyah جاهز');
}

async function runDiagnostics() {
  const browserReady = !!(
    window.MediaRecorder
    && navigator.mediaDevices
    && navigator.mediaDevices.getUserMedia
    && navigator.mediaDevices.enumerateDevices
    && (window.AudioContext || window.webkitAudioContext)
  );
  if (!browserReady) {
    setDiagnostic('browser', 'fail', 'Chrome لا يوفّر واجهات الصوت المطلوبة');
    throw new Error('Chrome audio APIs are unavailable');
  }
  setDiagnostic('browser', 'ok', 'Chrome جاهز للصوت');
  await prepareVoicemeeterB1();
  await Promise.all([checkSttHealth(), checkTtsHealth()]);
  diagnosticsReady = true;
  return true;
}

async function startCall() {
  return await fetchJson(START_URL, {});
}

async function sendTurn(text) {
  return await fetchJson(TURN_URL, {text});
}

async function sendAudioForTranscription(blob) {
  const response = await fetch(STT_URL, {
    method: 'POST',
    credentials: 'same-origin',
    headers: {'Content-Type': blob.type || 'audio/webm'},
    body: blob
  });
  let data = {};
  try { data = await response.json(); } catch (_) {}
  if (!response.ok) throw new Error(data.detail || ('STT HTTP ' + response.status));
  setDiagnostic('stt', 'ok', 'فهم الكلام يعمل');
  return (data.transcript || '').trim();
}

async function speakReply(text) {
  const clean = (text || '').trim();
  if (!clean) return;
  speaking = true;
  stopCurrentRecorder();
  stopJoodAudio();
  setStatus('جود تجهز الرد الصوتي...');
  try {
    const response = await fetch(TTS_URL, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({text: clean})
    });
    if (!response.ok) {
      let detail = 'TTS HTTP ' + response.status;
      try { detail = (await response.json()).detail || detail; } catch (_) {}
      setDiagnostic('tts', 'fail', 'تعذر توليد صوت جود');
      throw new Error(detail);
    }
    const context = await ensureOutputAudioContext();
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
        setDiagnostic('tts', 'ok', 'جود تتكلم الآن بصوت Zariyah');
        setStatus('جود تتكلم الآن...');
        source.start(0);
      } catch (err) {
        reject(err);
      }
    });
  } finally {
    speaking = false;
  }
}

function chooseRecorderMimeType() {
  const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus'];
  for (const value of candidates) {
    if (MediaRecorder.isTypeSupported(value)) return value;
  }
  return '';
}

async function captureUtterance() {
  if (!started || speaking || !inputStream || !analyser) return null;
  const mimeType = chooseRecorderMimeType();
  const options = mimeType ? {mimeType} : undefined;
  const recorder = options ? new MediaRecorder(inputStream, options) : new MediaRecorder(inputStream);
  currentRecorder = recorder;
  const chunks = [];
  let heardVoice = false;
  let lastVoiceAt = 0;
  const startedAt = performance.now();

  return await new Promise((resolve, reject) => {
    let timer = null;
    let settled = false;

    const stopRecorder = () => {
      if (recorder.state !== 'inactive') {
        try { recorder.stop(); } catch (_) {}
      }
    };

    const finish = value => {
      if (settled) return;
      settled = true;
      if (timer) clearTimeout(timer);
      if (currentRecorder === recorder) currentRecorder = null;
      resolve(value);
    };

    recorder.ondataavailable = event => {
      if (event.data && event.data.size) chunks.push(event.data);
    };
    recorder.onerror = event => {
      if (settled) return;
      settled = true;
      if (timer) clearTimeout(timer);
      if (currentRecorder === recorder) currentRecorder = null;
      reject(event.error || new Error('MediaRecorder failed'));
    };
    recorder.onstop = () => {
      if (!heardVoice || !chunks.length) {
        finish(null);
        return;
      }
      const type = recorder.mimeType || mimeType || 'audio/webm';
      const blob = new Blob(chunks, {type});
      finish(blob.size >= 128 ? blob : null);
    };

    recorder.start(250);
    setStatus('جود تستمع للطرف الآخر تلقائيًا...');

    const tick = () => {
      if (settled) return;
      if (!started || speaking) {
        stopRecorder();
        return;
      }

      const now = performance.now();
      const rms = currentRms();
      if (rms >= SPEECH_THRESHOLD) {
        heardVoice = true;
        lastVoiceAt = now;
        setDiagnostic('signal', 'ok', 'صوت الطرف الآخر واصل');
      }

      if (heardVoice && now - lastVoiceAt >= SILENCE_MS) {
        stopRecorder();
        return;
      }
      if (heardVoice && now - startedAt >= MAX_UTTERANCE_MS) {
        stopRecorder();
        return;
      }
      if (!heardVoice && now - startedAt >= WAIT_FOR_SPEECH_MS) {
        setDiagnostic('signal', 'pending', 'بانتظار صوت الطرف الآخر');
        stopRecorder();
        return;
      }
      timer = setTimeout(tick, 60);
    };
    timer = setTimeout(tick, 60);
  });
}

async function startCaptureLoop() {
  const myGeneration = ++captureGeneration;
  while (started && myGeneration === captureGeneration) {
    if (speaking) {
      await delay(100);
      continue;
    }
    try {
      const blob = await captureUtterance();
      if (!started || myGeneration !== captureGeneration) return;
      if (!blob) continue;

      setStatus('جود تحوّل كلام الطرف الآخر إلى نص...');
      const transcript = await sendAudioForTranscription(blob);
      if (!started || myGeneration !== captureGeneration) return;
      if (!transcript) continue;

      transcriptEl.textContent = transcript;
      setStatus('جود تفهم الكلام وتجهز الرد...');
      const data = await sendTurn(transcript);
      if (!started || myGeneration !== captureGeneration) return;
      replyEl.textContent = data.reply || '';
      await speakReply(data.reply || '');
      if (started) {
        await delay(250);
        setStatus('جود تستمع للطرف الآخر تلقائيًا...');
      }
    } catch (err) {
      started = false;
      setStatus('توقف التشغيل: ' + err.message);
      startBtn.disabled = false;
      startBtn.textContent = 'إعادة تشغيل جود';
      return;
    }
  }
}

startBtn.addEventListener('click', async () => {
  if (started) return;
  startBtn.disabled = true;
  startBtn.textContent = 'جاري تشغيل جود...';
  setStatus('جود تفحص مسار الصوت كاملًا...');
  try {
    started = true;
    if (!diagnosticsReady) await runDiagnostics();
    await ensureOutputAudioContext();
    const opening = await startCall();
    if (opening.reply) {
      replyEl.textContent = opening.reply;
      await speakReply(opening.reply);
    }
    setStatus('جود تعمل الآن — تستمع وترد تلقائيًا.');
    startBtn.textContent = 'جود تعمل الآن';
    startCaptureLoop();
  } catch (err) {
    started = false;
    diagnosticsReady = false;
    await stopInputStream();
    setStatus('تعذر تشغيل جود: ' + err.message);
    startBtn.disabled = false;
    startBtn.textContent = 'إعادة تشغيل جود';
  }
});

stopBtn.addEventListener('click', async () => {
  started = false;
  captureGeneration += 1;
  stopCurrentRecorder();
  stopJoodAudio();
  await stopInputStream();
  startBtn.disabled = false;
  startBtn.textContent = 'تشغيل جود';
  setStatus('جود متوقفة.');
});

async function finishCall(outcome) {
  started = false;
  captureGeneration += 1;
  stopCurrentRecorder();
  stopJoodAudio();
  await stopInputStream();
  try {
    const data = await fetchJson(FINISH_URL, {outcome});
    setStatus('تم حفظ Call Log: ' + (data.outcome || outcome));
    if (data.summary) replyEl.textContent = data.summary;
    startBtn.disabled = true;
  } catch (err) {
    setStatus('تعذر إغلاق المكالمة: ' + err.message);
  }
}
window.finishJoodCall = finishCall;

if (window.MediaRecorder && navigator.mediaDevices && (window.AudioContext || window.webkitAudioContext)) {
  setDiagnostic('browser', 'ok', 'Chrome جاهز للصوت');
} else {
  setDiagnostic('browser', 'fail', 'Chrome لا يوفّر واجهات الصوت المطلوبة');
}
setDiagnostic('b1', 'pending', 'سيتم فحص مدخل المكالمة عند التشغيل');
setDiagnostic('signal', 'pending', 'بانتظار التشغيل');
setDiagnostic('stt', 'pending', 'سيتم فحص فهم الكلام عند التشغيل');
setDiagnostic('tts', 'pending', 'سيتم فحص صوت جود عند التشغيل');
setStatus('جاهز للمكالمة. اختبر صوت جود من الصفحة المستقلة قبل الاتصال عند الحاجة.');
""".strip()

    replacements = {
        "__START_URL__": json.dumps(start_url),
        "__TURN_URL__": json.dumps(turn_url),
        "__TTS_URL__": json.dumps(tts_url),
        "__STT_URL__": json.dumps(stt_url),
        "__STT_HEALTH_URL__": json.dumps(stt_health_url),
        "__FINISH_URL__": json.dumps(finish_url),
    }
    for marker, value in replacements.items():
        template = template.replace(marker, value)
    return template
