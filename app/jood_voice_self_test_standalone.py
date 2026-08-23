from __future__ import annotations

import json

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import application as core


@core.app.get("/admin/company/jood/voice/{session_id}/self-test", response_class=HTMLResponse)
def jood_voice_self_test_standalone(session_id: int, request: Request):
    try:
        core.require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)

    tts_url = f"/admin/company/jood/voice/{int(session_id)}/tts"
    tts_url_js = json.dumps(tts_url)

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

  <script>
    const TTS_URL = {tts_url_js};
    const btn = document.getElementById('play-jood');
    const statusEl = document.getElementById('status');
    const httpEl = document.getElementById('diag-http');
    const bytesEl = document.getElementById('diag-bytes');
    const sinkEl = document.getElementById('diag-sink');
    const stateEl = document.getElementById('diag-state');

    async function getDefaultOutputLabel() {{
      if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) {{
        return 'System default output';
      }}
      try {{
        const devices = await navigator.mediaDevices.enumerateDevices();
        const outputs = devices.filter(d => d.kind === 'audiooutput');
        const def = outputs.find(d => d.deviceId === 'default') || outputs[0];
        return def && def.label ? def.label : 'System default output';
      }} catch (_) {{
        return 'System default output';
      }}
    }}

    btn.addEventListener('click', async () => {{
      btn.disabled = true;
      httpEl.textContent = '—';
      bytesEl.textContent = '—';
      sinkEl.textContent = '—';
      stateEl.textContent = 'starting';
      statusEl.textContent = 'جاري توليد صوت جود...';

      let objectUrl = '';
      try {{
        const response = await fetch(TTS_URL, {{
          method: 'POST',
          credentials: 'same-origin',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{text: 'السلام عليكم، معك جود من بكجات.'}})
        }});

        httpEl.textContent = String(response.status);
        if (!response.ok) {{
          let detail = 'TTS HTTP ' + response.status;
          try {{ detail = (await response.json()).detail || detail; }} catch (_) {{}}
          throw new Error(detail);
        }}

        const blob = await response.blob();
        bytesEl.textContent = String(blob.size);
        if (!blob || blob.size < 128) throw new Error('ملف الصوت فارغ أو غير صالح.');

        objectUrl = URL.createObjectURL(blob);
        const audio = new Audio(objectUrl);
        audio.preload = 'auto';
        audio.volume = 1.0;

        if (typeof audio.setSinkId !== 'function') {{
          throw new Error('Chrome لا يدعم setSinkId على هذا الجهاز.');
        }}

        const outputLabel = await getDefaultOutputLabel();
        await audio.setSinkId('default');
        sinkEl.textContent = outputLabel + ' [default]';

        await new Promise((resolve, reject) => {{
          let settled = false;

          audio.addEventListener('play', () => {{
            stateEl.textContent = 'playing';
            statusEl.textContent = 'جود تتكلم الآن...';
          }}, {{once:true}});

          audio.addEventListener('ended', () => {{
            if (settled) return;
            settled = true;
            stateEl.textContent = 'ended';
            statusEl.textContent = 'انتهى تشغيل صوت جود.';
            resolve();
          }}, {{once:true}});

          audio.addEventListener('error', () => {{
            if (settled) return;
            settled = true;
            reject(new Error('فشل تشغيل ملف الصوت في Chrome.'));
          }}, {{once:true}});

          audio.play().catch(err => {{
            if (settled) return;
            settled = true;
            reject(err);
          }});
        }});
      }} catch (err) {{
        stateEl.textContent = 'failed';
        statusEl.textContent = 'فشل الاختبار: ' + err.message;
      }} finally {{
        if (objectUrl) URL.revokeObjectURL(objectUrl);
        btn.disabled = false;
      }}
    }});
  </script>
</body>
</html>"""

    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})
