from __future__ import annotations

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import application as core


def _admin_redirect(request: Request):
    try:
        core.require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)
    return None


@core.app.get("/admin/company/jood/voice/{session_id}/self-test", response_class=HTMLResponse)
def jood_voice_self_test_page(session_id: int, request: Request):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect

    tts_url = f"/admin/company/jood/voice/{int(session_id)}/tts"

    html = r"""
<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>اختبار صوت جود</title>
  <style>
    body { font-family: Arial, sans-serif; background:#f8fafc; margin:0; padding:32px; color:#0f172a; }
    main { max-width:680px; margin:0 auto; background:#fff; border:1px solid #e2e8f0; border-radius:16px; padding:24px; }
    button { cursor:pointer; border:0; border-radius:10px; padding:12px 18px; font-size:16px; background:#2563eb; color:#fff; }
    button:disabled { opacity:.6; cursor:not-allowed; }
    .status { margin-top:16px; padding:12px; border-radius:10px; background:#eff6ff; }
    .diag { margin-top:16px; padding:14px; border:1px solid #e2e8f0; border-radius:10px; line-height:1.9; }
    .muted { color:#64748b; }
  </style>
</head>
<body>
  <main>
    <h1>اختبار صوت جود المستقل</h1>
    <p class="muted">هذه الصفحة لا تستخدم Phone Link أو Voicemeeter أو STT.</p>

    <button id="play-jood" type="button">🔊 تشغيل صوت جود التجريبي</button>

    <div id="status" class="status">جاهز.</div>
    <div class="diag">
      <div>TTS HTTP: <strong id="diag-http">—</strong></div>
      <div>Audio Bytes: <strong id="diag-bytes">—</strong></div>
      <div>Sink: <strong id="diag-sink">—</strong></div>
      <div>State: <strong id="diag-state">—</strong></div>
    </div>
  </main>

  <script>
    const TTS_URL = "__TTS_URL__";
    const button = document.getElementById('play-jood');
    const statusEl = document.getElementById('status');
    const httpEl = document.getElementById('diag-http');
    const bytesEl = document.getElementById('diag-bytes');
    const sinkEl = document.getElementById('diag-sink');
    const stateEl = document.getElementById('diag-state');

    button.addEventListener('click', async () => {
      button.disabled = true;
      httpEl.textContent = '—';
      bytesEl.textContent = '—';
      sinkEl.textContent = '—';
      stateEl.textContent = 'starting';
      statusEl.textContent = 'جاري توليد صوت جود...';

      let objectUrl = null;
      try {
        const response = await fetch(TTS_URL, {
          method: 'POST',
          credentials: 'same-origin',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({text: 'السلام عليكم، معك جود من بكجات.'})
        });

        httpEl.textContent = String(response.status);
        if (!response.ok) {
          let message = 'TTS HTTP ' + response.status;
          try {
            const payload = await response.json();
            if (payload && payload.detail) message = payload.detail;
          } catch (_) {}
          throw new Error(message);
        }

        const blob = await response.blob();
        bytesEl.textContent = String(blob.size);
        if (!blob.size) throw new Error('ملف الصوت فارغ.');

        objectUrl = URL.createObjectURL(blob);
        const audio = new Audio(objectUrl);
        window.__joodSelfTestAudio = audio;

        if (typeof audio.setSinkId !== 'function') {
          throw new Error('Chrome لا يدعم setSinkId على هذا الجهاز.');
        }

        await audio.setSinkId('default');
        sinkEl.textContent = 'default';

        audio.addEventListener('play', () => {
          stateEl.textContent = 'playing';
          statusEl.textContent = 'جود تتكلم الآن...';
        }, {once:true});

        audio.addEventListener('ended', () => {
          stateEl.textContent = 'ended';
          statusEl.textContent = 'انتهى تشغيل صوت جود.';
          if (objectUrl) URL.revokeObjectURL(objectUrl);
          objectUrl = null;
          button.disabled = false;
        }, {once:true});

        audio.addEventListener('error', () => {
          stateEl.textContent = 'playback-error';
        }, {once:true});

        await audio.play();
      } catch (error) {
        stateEl.textContent = 'failed';
        statusEl.textContent = 'فشل الاختبار: ' + error.message;
        if (objectUrl) URL.revokeObjectURL(objectUrl);
        button.disabled = false;
      }
    });
  </script>
</body>
</html>
""".replace("__TTS_URL__", tts_url)

    return HTMLResponse(content=html)
