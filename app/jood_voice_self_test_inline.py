from __future__ import annotations

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app import application as core
from app import jood_voice_live_bridge as live


OLD_SELF_TEST_HANDLER = """testVoiceBtn.addEventListener('click', async () => {
  if (started) {
    setStatus('أوقف جود أولًا قبل اختبار الصوت المستقل.');
    return;
  }
  testVoiceBtn.disabled = true;
  setStatus('جاري اختبار صوت جود...');
  try {
    await ensureOutputAudioContext();
    await speakReply('السلام عليكم، معك جود من بكجات.');
    setStatus('تم اختبار صوت جود بنجاح.');
  } catch (err) {
    setStatus('تعذر اختبار صوت جود: ' + err.message);
  } finally {
    testVoiceBtn.disabled = false;
  }
});"""


def build_inline_local_self_test_handler() -> str:
    return r"""
function ensureLocalSelfTestDiagnostics() {
  let host = document.getElementById('local-self-test-diagnostics');
  if (host) return host;

  host = document.createElement('div');
  host.id = 'local-self-test-diagnostics';
  host.className = 'card';
  host.style.cssText = 'padding:12px;margin-top:10px;background:#fff;border:1px solid #dbeafe;font-size:13px;line-height:1.8';
  const title = document.createElement('strong');
  title.textContent = 'تشخيص اختبار صوت جود المحلي';
  host.appendChild(title);
  const rows = document.createElement('div');
  rows.id = 'local-self-test-diagnostic-rows';
  rows.style.marginTop = '6px';
  host.appendChild(rows);

  const controls = testVoiceBtn && testVoiceBtn.parentElement;
  if (controls && controls.parentElement) {
    controls.parentElement.insertBefore(host, controls.nextSibling);
  } else if (statusEl && statusEl.parentElement) {
    statusEl.parentElement.insertBefore(host, statusEl.nextSibling);
  }
  return host;
}

const localSelfTestState = {
  'TTS HTTP': '—',
  'Audio Bytes': '—',
  'Selected Sink': '—',
  'Audio Decode': '—',
  'Playback State': '—'
};

function renderLocalSelfTestDiagnostics() {
  ensureLocalSelfTestDiagnostics();
  const rows = document.getElementById('local-self-test-diagnostic-rows');
  if (!rows) return;
  rows.replaceChildren();
  for (const [label, value] of Object.entries(localSelfTestState)) {
    const row = document.createElement('div');
    const key = document.createElement('span');
    key.textContent = label + ': ';
    key.style.fontWeight = '600';
    const val = document.createElement('span');
    val.textContent = String(value || '—');
    row.appendChild(key);
    row.appendChild(val);
    rows.appendChild(row);
  }
}

function updateLocalSelfTestDiagnostic(label, value) {
  localSelfTestState[label] = value;
  renderLocalSelfTestDiagnostics();
}

function isDisallowedLocalOutput(device) {
  const label = String((device && device.label) || '').toLowerCase();
  return label.includes('voicemeeter')
    || label.includes('vb-audio')
    || label.includes('virtual cable')
    || label.includes('motorola')
    || label.includes('hands-free')
    || label.includes('hands free');
}

function physicalLocalOutputScore(device) {
  if (!device || device.kind !== 'audiooutput' || isDisallowedLocalOutput(device)) return -1;
  const label = String(device.label || '').toLowerCase();
  if (!label) return -1;

  let score = -1;
  if (label.includes('realtek')) score = 120;
  else if (label.includes('lg ultrafine')) score = 110;
  else if (label.includes('speakers') || label.includes('speaker')) score = 90;
  else if (label.includes('headphones') || label.includes('headphone')) score = 80;
  else if (label.includes('headset')) score = 70;

  if (score > 0 && device.deviceId && device.deviceId !== 'default') score += 10;
  return score;
}

async function enumerateNamedAudioOutputs() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) {
    throw new Error('Chrome لا يوفّر enumerateDevices لاختيار سماعة محلية.');
  }

  let devices = await navigator.mediaDevices.enumerateDevices();
  let outputs = devices.filter(device => device.kind === 'audiooutput');
  if (outputs.some(device => String(device.label || '').trim())) return outputs;

  if (navigator.mediaDevices.getUserMedia) {
    try {
      const probe = await navigator.mediaDevices.getUserMedia({audio: true});
      for (const track of probe.getTracks()) track.stop();
      devices = await navigator.mediaDevices.enumerateDevices();
      outputs = devices.filter(device => device.kind === 'audiooutput');
    } catch (_) {
      // Continue to explicit output selection below if labels remain unavailable.
    }
  }
  return outputs;
}

async function choosePhysicalLocalOutput() {
  const outputs = await enumerateNamedAudioOutputs();
  const ranked = outputs
    .map(device => ({device, score: physicalLocalOutputScore(device)}))
    .filter(item => item.score > 0)
    .sort((a, b) => b.score - a.score);

  if (ranked.length) return ranked[0].device;

  if (navigator.mediaDevices && typeof navigator.mediaDevices.selectAudioOutput === 'function') {
    setStatus('اختر سماعة فعلية مثل Speakers (Realtek/LG)، وليس Voicemeeter أو Motorola Hands-Free.');
    const selected = await navigator.mediaDevices.selectAudioOutput();
    if (!selected || selected.kind !== 'audiooutput') throw new Error('لم يتم اختيار مخرج صوت.');
    if (isDisallowedLocalOutput(selected)) {
      throw new Error('تم اختيار مسار مكالمة/افتراضي. اختر Speakers (Realtek/LG).');
    }
    return selected;
  }

  const visible = outputs.map(device => device.label || '(بدون اسم)').join(' | ');
  throw new Error('لم يجد Chrome مخرجًا فيزيائيًا مستقلًا. المخرجات: ' + (visible || 'لا يوجد'));
}

function waitForLocalAudioDecode(audio) {
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

function playLocalAudioUntilEnded(audio) {
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
    audio.addEventListener('play', () => updateLocalSelfTestDiagnostic('Playback State', 'playing'), {once: true});
    audio.addEventListener('ended', finish(() => {
      updateLocalSelfTestDiagnostic('Playback State', 'ended');
      resolve();
    }), {once: true});
    audio.addEventListener('error', finish(() => reject(new Error('فشل Playback بعد بدء الاختبار.'))), {once: true});
    Promise.resolve(audio.play()).catch(err => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      reject(err);
    });
  });
}

testVoiceBtn.addEventListener('click', async () => {
  if (started) {
    setStatus('أوقف جود أولًا قبل اختبار الصوت المحلي.');
    return;
  }

  testVoiceBtn.disabled = true;
  setStatus('جاري اختبار صوت جود محليًا — هذا الاختبار لا يستخدم B2.');
  for (const key of Object.keys(localSelfTestState)) localSelfTestState[key] = '—';
  renderLocalSelfTestDiagnostics();

  let objectUrl = '';
  try {
    const response = await fetch(TTS_URL, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({text: 'السلام عليكم، معك جود من بكجات.'})
    });
    updateLocalSelfTestDiagnostic('TTS HTTP', String(response.status));
    if (!response.ok) {
      let detail = 'TTS HTTP ' + response.status;
      try { detail = (await response.json()).detail || detail; } catch (_) {}
      throw new Error(detail);
    }

    const blob = await response.blob();
    updateLocalSelfTestDiagnostic('Audio Bytes', String(blob.size));
    if (!blob || blob.size < 128) throw new Error('ملف Zariyah فارغ أو صغير جدًا.');

    const sink = await choosePhysicalLocalOutput();
    const sinkLabel = sink.label || ('device ' + sink.deviceId);
    updateLocalSelfTestDiagnostic('Selected Sink', sinkLabel);

    const audio = new Audio();
    if (typeof audio.setSinkId !== 'function') {
      throw new Error('Chrome لا يدعم setSinkId على هذا الجهاز.');
    }
    await audio.setSinkId(sink.deviceId);
    updateLocalSelfTestDiagnostic('Selected Sink', sinkLabel + ' [' + sink.deviceId + ']');

    objectUrl = URL.createObjectURL(blob);
    audio.preload = 'auto';
    audio.src = objectUrl;
    updateLocalSelfTestDiagnostic('Audio Decode', 'checking');
    await waitForLocalAudioDecode(audio);
    updateLocalSelfTestDiagnostic('Audio Decode', 'ready');

    updateLocalSelfTestDiagnostic('Playback State', 'starting');
    await playLocalAudioUntilEnded(audio);
    setStatus('انتهى اختبار صوت جود المحلي على: ' + sinkLabel);
  } catch (err) {
    updateLocalSelfTestDiagnostic('Playback State', 'failed: ' + err.message);
    setStatus('تعذر اختبار صوت جود المحلي: ' + err.message);
  } finally {
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    testVoiceBtn.disabled = false;
  }
});
""".strip()


def rewrite_live_self_test_html(html: str) -> str:
    source = str(html or "")
    if OLD_SELF_TEST_HANDLER not in source:
        raise RuntimeError("Known Jood live self-test handler was not found")

    rewritten = source.replace(OLD_SELF_TEST_HANDLER, build_inline_local_self_test_handler(), 1)
    rewritten = rewritten.replace(
        "testVoiceBtn.textContent = '🔊 اختبار صوت جود';",
        "testVoiceBtn.textContent = '🔊 اختبار محلي لصوت جود';",
        1,
    )
    rewritten = rewritten.replace(
        "setStatus('جاهز. يمكنك اختبار صوت جود بدون مكالمة، أو تشغيلها بعد أن يرد الطرف الآخر.');",
        "setStatus('جاهز. «اختبار محلي لصوت جود» يخرج للسماعة الفيزيائية فقط؛ «تشغيل جود» يبقى لمسار المكالمة.');",
        1,
    )
    return rewritten


def _inline_self_test_bridge_page(session_id: int, request: Request, db: Session = Depends(core.get_db)):
    # Deliberately call the known live bridge directly. This bypasses the old PR #23
    # runtime overlay/clone path and rewrites the self-test inside the script that is
    # already proven to execute because it creates the visible Jood controls.
    response = live._live_voice_bridge_page(session_id, request, db)
    if not isinstance(response, HTMLResponse):
        return response
    html = bytes(response.body).decode("utf-8", errors="replace")
    html = rewrite_live_self_test_html(html)
    return HTMLResponse(content=html, status_code=response.status_code)


def install_inline_self_test_patch() -> None:
    target = "/admin/company/jood/voice/{session_id}/bridge"
    for route in core.app.routes:
        if getattr(route, "path", None) != target or "GET" not in (getattr(route, "methods", set()) or set()):
            continue
        route.endpoint = _inline_self_test_bridge_page
        dependant = getattr(route, "dependant", None)
        if dependant is not None:
            dependant.call = _inline_self_test_bridge_page
        return
    raise RuntimeError("Jood voice bridge route was not registered before inline self-test patch")

