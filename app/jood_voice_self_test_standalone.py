from __future__ import annotations

import json

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app import application as core


def build_standalone_self_test_script(session_id: int) -> str:
    tts_url = json.dumps(f"/admin/company/jood/voice/{int(session_id)}/tts")
    template = r"""
const TTS_URL = __TTS_URL__;
const btn = document.getElementById('play-jood');
const statusEl = document.getElementById('status');
const httpEl = document.getElementById('diag-http');
const bytesEl = document.getElementById('diag-bytes');
const sinkEl = document.getElementById('diag-sink');
const stateEl = document.getElementById('diag-state');

function showFailure(err) {
  stateEl.textContent = 'failed';
  statusEl.textContent = 'فشل الاختبار: ' + (err && err.message ? err.message : String(err));
}

async function getDefaultOutputLabel() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) {
    return 'System default output';
  }
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    const outputs = devices.filter(device => device.kind === 'audiooutput');
    const selected = outputs.find(device => device.deviceId === 'default') || outputs[0];
    return selected && selected.label ? selected.label : 'System default output';
  } catch (_) {
    return 'System default output';
  }
}

if (!btn) {
  throw new Error('Jood self-test button was not found');
}

btn.addEventListener('click', async () => {
  btn.disabled = true;
  httpEl.textContent = '—';
  bytesEl.textContent = '—';
  sinkEl.textContent = '—';
  stateEl.textContent = 'requesting';
  statusEl.textContent = 'جاري طلب صوت جود من الخادم...';

  let objectUrl = '';
  try {
    const response = await fetch(TTS_URL, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({text: 'السلام عليكم، معك جود من بكجات.'})
    });

    httpEl.textContent = String(response.status);
    if (!response.ok) {
      let detail = 'TTS HTTP ' + response.status;
      try {
        const payload = await response.json();
        detail = payload.detail || detail;
      } catch (_) {}
      throw new Error(detail);
    }

    const blob = await response.blob();
    bytesEl.textContent = String(blob.size);
    if (!blob || blob.size < 128) throw new Error('ملف الصوت فارغ أو غير صالح.');

    objectUrl = URL.createObjectURL(blob);
    const audio = new Audio(objectUrl);
    audio.preload = 'auto';
    audio.volume = 1.0;

    const outputLabel = await getDefaultOutputLabel();
    if (typeof audio.setSinkId === 'function') {
      await audio.setSinkId('default');
      sinkEl.textContent = outputLabel + ' [default]';
    } else {
      sinkEl.textContent = outputLabel + ' [browser default]';
    }

    audio.addEventListener('play', () => {
      stateEl.textContent = 'playing';
      statusEl.textContent = 'جود تتكلم الآن...';
    }, {once: true});

    await new Promise((resolve, reject) => {
      audio.addEventListener('ended', resolve, {once: true});
      audio.addEventListener('error', () => reject(new Error('فشل تشغيل ملف الصوت في Chrome.')), {once: true});
      audio.play().catch(reject);
    });

    stateEl.textContent = 'ended';
    statusEl.textContent = 'نجح الاختبار وانتهى تشغيل صوت جود.';
  } catch (err) {
    showFailure(err);
  } finally {
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    btn.disabled = false;
  }
});
""".strip()
    return template.replace("__TTS_URL__", tts_url)


@core.app.get("/admin/company/jood/voice/{session_id}/self-test.js")
def jood_voice_self_test_script(session_id: int, request: Request):
    try:
        core.require_admin(request)
    except HTTPException:
        return Response(
            content="throw new Error('Admin authentication required');",
            status_code=401,
            media_type="application/javascript",
            headers={"Cache-Control": "no-store"},
        )
    return Response(
        content=build_standalone_self_test_script(session_id),
        media_type="application/javascript",
        headers={"Cache-Control": "no-store"},
    )


@core.app.get("/admin/company/jood/voice/{session_id}/self-test", response_class=HTMLResponse)
def jood_voice_self_test_standalone(session_id: int, request: Request):
    try:
        core.require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)

    tts_url = f"/admin/company/jood/voice/{int(session_id)}/tts"
    script_url = f"/admin/company/jood/voice/{int(session_id)}/self-test.js"

    html = f"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>اختبار صوت جود</title>
  <style>
    body {{ font-family: Arial, sans-serif; background:#f8fafc; margin:0; padding:32px; color:#0f172a; }}
    .card {{ max-width:720px; margin:auto; background:#fff; border:1px solid #e2e8f0; border-radius:16px; padding:24px; box-shadow:0 8px 28px rgba(15,23,42,.06); }}
    h1 {{ margin:0 0 8px; font-size:26px; }}
    p {{ color:#475569; line-height:1.7; }}
    button {{ border:0; border-radius:10px; padding:12px 18px; font-size:16px; cursor:pointer; background:#2563eb; color:#fff; font-weight:700; }}
    button:disabled {{ opacity:.55; cursor:not-allowed; }}
    .status {{ margin-top:16px; padding:12px; border-radius:10px; background:#eff6ff; border:1px solid #bfdbfe; }}
    .diag {{ margin-top:16px; border:1px solid #e2e8f0; border-radius:12px; overflow:hidden; }}
    .row {{ display:grid; grid-template-columns:180px 1fr; gap:12px; padding:10px 12px; border-bottom:1px solid #e2e8f0; }}
    .row:last-child {{ border-bottom:0; }}
    .key {{ font-weight:700; }}
    .val {{ direction:ltr; text-align:left; word-break:break-all; }}
  </style>
</head>
<body>
  <main class="card">
    <h1>اختبار صوت جود المستقل</h1>
    <p>جلسة #{int(session_id)} — هذا الاختبار مستقل عن Phone Link وVoicemeeter وSTT.</p>

    <button id="play-jood" type="button">🔊 تشغيل صوت جود التجريبي</button>
    <div id="status" class="status">جاهز للاختبار.</div>

    <div class="diag">
      <div class="row"><div class="key">TTS HTTP</div><div id="diag-http" class="val">—</div></div>
      <div class="row"><div class="key">Audio Bytes</div><div id="diag-bytes" class="val">—</div></div>
      <div class="row"><div class="key">Selected Sink</div><div id="diag-sink" class="val">—</div></div>
      <div class="row"><div class="key">Playback State</div><div id="diag-state" class="val">—</div></div>
    </div>
  </main>

  <script src="{script_url}" defer></script>
</body>
</html>"""

    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})
