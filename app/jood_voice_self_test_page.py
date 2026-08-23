from __future__ import annotations

import json

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import application as core
from app.jood_company_ops import CompanyContact, JoodCallSession


def _admin_redirect(request: Request):
    try:
        core.require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)
    return None


def build_self_test_script(session_id: int) -> str:
    tts_url = f"/admin/company/jood/voice/{int(session_id)}/tts"
    template = r"""
const TTS_URL = __TTS_URL__;
const testBtn = document.getElementById('jood-self-test-play');
const statusEl = document.getElementById('jood-self-test-status');
const diagRows = {
  'TTS HTTP': document.getElementById('diag-http'),
  'Audio Bytes': document.getElementById('diag-bytes'),
  'Selected Sink': document.getElementById('diag-sink'),
  'Audio Decode': document.getElementById('diag-decode'),
  'Playback State': document.getElementById('diag-playback')
};

function setStatus(text) {
  if (statusEl) statusEl.textContent = text;
}

function setDiag(key, value) {
  const el = diagRows[key];
  if (el) el.textContent = String(value == null ? '—' : value);
}

function resetDiagnostics() {
  for (const key of Object.keys(diagRows)) setDiag(key, '—');
}

function isRejectedOutput(device) {
  const label = String((device && device.label) || '').toLowerCase();
  return label.includes('voicemeeter')
    || label.includes('vb-audio')
    || label.includes('virtual cable')
    || label.includes('motorola')
    || label.includes('hands-free')
    || label.includes('hands free');
}

function physicalOutputScore(device) {
  if (!device || device.kind !== 'audiooutput' || isRejectedOutput(device)) return -1;
  const label = String(device.label || '').toLowerCase();
  if (!label) return -1;
  let score = -1;
  if (label.includes('realtek')) score = 120;
  else if (label.includes('speakers') || label.includes('speaker')) score = 110;
  else if (label.includes('lg ultrafine') || label.includes('lg')) score = 100;
  else if (label.includes('headphones') || label.includes('headphone')) score = 90;
  else if (label.includes('headset')) score = 80;
  if (score > 0 && device.deviceId && device.deviceId !== 'default') score += 10;
  return score;
}

async function choosePhysicalOutput() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) {
    throw new Error('Chrome لا يوفّر enumerateDevices.');
  }
  const devices = await navigator.mediaDevices.enumerateDevices();
  const outputs = devices.filter(device => device.kind === 'audiooutput');
  const ranked = outputs
    .map(device => ({device, score: physicalOutputScore(device)}))
    .filter(item => item.score > 0)
    .sort((a, b) => b.score - a.score);
  if (ranked.length) return ranked[0].device;

  if (typeof navigator.mediaDevices.selectAudioOutput === 'function') {
    setStatus('اختر Speakers / Realtek / LG فقط. لا تختَر Voicemeeter أو Motorola Hands-Free.');
    const selected = await navigator.mediaDevices.selectAudioOutput();
    if (!selected || selected.kind !== 'audiooutput') throw new Error('لم يتم اختيار مخرج صوت.');
    if (isRejectedOutput(selected)) throw new Error('المخرج المختار مسار مكالمة/افتراضي وليس سماعة محلية.');
    return selected;
  }

  const names = outputs.map(device => device.label || '(بدون اسم)').join(' | ');
  throw new Error('لم يجد Chrome سماعة محلية مستقلة. المخرجات: ' + (names || 'لا يوجد'));
}

function waitForCanPlay(audio) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      reject(new Error('انتهت مهلة Audio Decode.'));
    }, 10000);
    const finish = callback => event => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      callback(event);
    };
    audio.addEventListener('canplay', finish(() => resolve()), {once: true});
    audio.addEventListener('error', finish(() => reject(new Error('فشل Audio Decode في Chrome.'))), {once: true});
    audio.load();
  });
}

function playUntilEnded(audio) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      reject(new Error('انتهت مهلة Playback قبل حدث ended.'));
    }, 20000);
    const finish = callback => event => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      callback(event);
    };
    audio.addEventListener('play', () => setDiag('Playback State', 'playing'), {once: true});
    audio.addEventListener('ended', finish(() => {
      setDiag('Playback State', 'ended');
      resolve();
    }), {once: true});
    audio.addEventListener('error', finish(() => reject(new Error('فشل Playback في Chrome.'))), {once: true});
    Promise.resolve(audio.play()).catch(error => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      reject(error);
    });
  });
}

if (testBtn) {
  testBtn.addEventListener('click', async () => {
    testBtn.disabled = true;
    resetDiagnostics();
    setStatus('جاري توليد صوت جود واختيار سماعة اللابتوب...');
    let objectUrl = '';
    try {
      const response = await fetch(TTS_URL, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({text: 'السلام عليكم، معك جود من بكجات.'})
      });
      setDiag('TTS HTTP', response.status);
      if (!response.ok) {
        let detail = 'TTS HTTP ' + response.status;
        try { detail = (await response.json()).detail || detail; } catch (_) {}
        throw new Error(detail);
      }

      const blob = await response.blob();
      setDiag('Audio Bytes', blob.size);
      if (!blob || blob.size < 128) throw new Error('ملف Zariyah فارغ أو صغير جدًا.');

      const sink = await choosePhysicalOutput();
      const sinkLabel = sink.label || ('device ' + sink.deviceId);
      setDiag('Selected Sink', sinkLabel);

      const audio = new Audio();
      if (typeof audio.setSinkId !== 'function') throw new Error('Chrome لا يدعم setSinkId على هذا الجهاز.');
      await audio.setSinkId(sink.deviceId);
      setDiag('Selected Sink', sinkLabel + ' [' + sink.deviceId + ']');

      objectUrl = URL.createObjectURL(blob);
      audio.preload = 'auto';
      audio.src = objectUrl;
      setDiag('Audio Decode', 'checking');
      await waitForCanPlay(audio);
      setDiag('Audio Decode', 'ready');
      setDiag('Playback State', 'starting');
      await playUntilEnded(audio);
      setStatus('انتهى الاختبار. إذا سمعت جود فمسار Zariyah والسماعة المحلية يعملان.');
    } catch (error) {
      setDiag('Playback State', 'failed: ' + error.message);
      setStatus('فشل الاختبار: ' + error.message);
    } finally {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      testBtn.disabled = false;
    }
  });
}

resetDiagnostics();
setStatus('جاهز. هذا الاختبار مستقل عن Phone Link وB1/B2 ومسار المكالمة.');
""".strip()
    return template.replace("__TTS_URL__", json.dumps(tts_url))


@core.app.get("/admin/company/jood/voice/{session_id}/self-test", response_class=HTMLResponse)
def jood_voice_self_test_page(session_id: int, request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect

    session = db.get(JoodCallSession, session_id)
    if not session or session.status != "active":
        raise HTTPException(status_code=404, detail="Active voice session not found")
    contact = db.get(CompanyContact, session.contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    script = build_self_test_script(session.id)
    label = contact.display_name or contact.business_name or ("Customer" if contact.contact_type == "customer" else "Merchant")
    body = f"""
    <main class='wrap' style='padding:28px 0 48px'>
      <section class='card' style='padding:24px;max-width:760px;margin:auto'>
        <div style='display:flex;justify-content:space-between;gap:10px;align-items:flex-start;flex-wrap:wrap'>
          <div>
            <h1 style='margin-bottom:4px'>اختبار صوت جود المستقل</h1>
            <p class='muted'>Voice Session #{session.id} · {core.esc(label)}</p>
          </div>
          <a class='btn btn-muted' href='/admin/company/jood/voice/{session.id}/bridge'>رجوع إلى المكالمة</a>
        </div>

        <div class='alert' style='margin-top:16px;background:#eff6ff;border:1px solid #bfdbfe;color:#1e3a8a'>
          هذه الصفحة لا تستخدم Phone Link ولا Voicemeeter B1/B2 ولا STT. الاختبار يطلب Zariyah من Pakgat ثم يوجّهها إلى سماعة محلية فعلية في Chrome.
        </div>

        <button id='jood-self-test-play' class='btn btn-blue' type='button' style='margin:10px 0 14px'>🔊 تشغيل صوت جود التجريبي</button>
        <div id='jood-self-test-status' class='alert'>جاهز.</div>

        <div class='card' style='padding:16px;margin-top:12px;background:#f8fafc'>
          <strong>Diagnostics</strong>
          <div style='display:grid;grid-template-columns:minmax(150px,220px) 1fr;gap:8px 12px;margin-top:12px;font-size:14px'>
            <div><strong>TTS HTTP</strong></div><div id='diag-http'>—</div>
            <div><strong>Audio Bytes</strong></div><div id='diag-bytes'>—</div>
            <div><strong>Selected Sink</strong></div><div id='diag-sink'>—</div>
            <div><strong>Audio Decode</strong></div><div id='diag-decode'>—</div>
            <div><strong>Playback State</strong></div><div id='diag-playback'>—</div>
          </div>
        </div>
      </section>
    </main>
    <script>{script}</script>
    """
    return HTMLResponse(core.page_shell(f"اختبار صوت جود #{session.id}", body, admin=True))
