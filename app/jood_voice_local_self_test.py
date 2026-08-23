from __future__ import annotations

import json

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app import application as core
from app import jood_voice_live_bridge as live


def build_local_self_test_overlay(session_id: int) -> str:
    tts_url = f"/admin/company/jood/voice/{int(session_id)}/tts"
    template = r"""
<script>
(() => {
  const TTS_URL = __TTS_URL__;
  const originalButton = document.getElementById('test-jood-voice');
  if (!originalButton) return;

  // Replace the PR #22 button node so its old listener cannot reuse the live-call AudioContext.
  const testVoiceBtn = originalButton.cloneNode(true);
  testVoiceBtn.textContent = '🔊 اختبار صوت جود';
  originalButton.replaceWith(testVoiceBtn);

  const statusEl = document.getElementById('voice-status');
  const startBtn = document.getElementById('start-jood');
  const diagnosticsHost = document.createElement('div');
  diagnosticsHost.id = 'local-self-test-diagnostics';
  diagnosticsHost.className = 'card';
  diagnosticsHost.style.cssText = 'padding:12px;margin-top:10px;background:#fff;border:1px solid #dbeafe;font-size:13px;line-height:1.8;display:none';

  const title = document.createElement('strong');
  title.textContent = 'تشخيص اختبار صوت جود المحلي';
  diagnosticsHost.appendChild(title);

  const rows = document.createElement('div');
  rows.style.marginTop = '6px';
  diagnosticsHost.appendChild(rows);

  const controls = testVoiceBtn.parentElement;
  if (controls && controls.parentElement) controls.parentElement.insertBefore(diagnosticsHost, controls.nextSibling);

  const diagnosticState = {
    'TTS HTTP': '—',
    'Audio Bytes': '—',
    'Selected Sink': '—',
    'Audio Decode': '—',
    'Playback State': '—'
  };

  function renderDiagnostics() {
    diagnosticsHost.style.display = 'block';
    rows.replaceChildren();
    for (const [label, value] of Object.entries(diagnosticState)) {
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

  function updateDiagnostic(label, value) {
    diagnosticState[label] = value;
    renderDiagnostics();
  }

  function setMainStatus(text) {
    if (statusEl) statusEl.textContent = text;
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

  function physicalOutputScore(device) {
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

  async function choosePhysicalOutput() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) {
      throw new Error('Chrome لا يوفّر enumerateDevices لاختيار سماعة محلية.');
    }
    const devices = await navigator.mediaDevices.enumerateDevices();
    const outputs = devices.filter(device => device.kind === 'audiooutput');
    const ranked = outputs
      .map(device => ({device, score: physicalOutputScore(device)}))
      .filter(item => item.score > 0)
      .sort((a, b) => b.score - a.score);

    if (ranked.length) return ranked[0].device;

    if (typeof navigator.mediaDevices.selectAudioOutput === 'function') {
      setMainStatus('اختر سماعة اللابتوب الفعلية مثل Speakers (Realtek/LG)، وليس Voicemeeter.');
      const selected = await navigator.mediaDevices.selectAudioOutput();
      if (!selected || selected.kind !== 'audiooutput') throw new Error('لم يتم اختيار مخرج صوت.');
      if (isDisallowedLocalOutput(selected)) {
        throw new Error('اختر مخرجًا محليًا مثل Speakers (Realtek/LG)، وليس Voicemeeter أو Motorola Hands-Free.');
      }
      return selected;
    }

    const visible = outputs.map(device => device.label || '(بدون اسم)').join(' | ');
    throw new Error('لم يكشف Chrome مخرج Realtek/LG مستقلًا. المخرجات: ' + (visible || 'لا يوجد'));
  }

  function waitForDecodedAudio(audio) {
    return new Promise((resolve, reject) => {
      let settled = false;
      const timeout = setTimeout(() => {
        if (settled) return;
        settled = true;
        reject(new Error('انتهت مهلة فك ترميز ملف الصوت.'));
      }, 10000);
      const finish = callback => event => {
        if (settled) return;
        settled = true;
        clearTimeout(timeout);
        callback(event);
      };
      audio.addEventListener('canplay', finish(() => resolve()), {once: true});
      audio.addEventListener('error', finish(() => reject(new Error('فشل Audio Decode في Chrome.'))), {once: true});
      audio.load();
    });
  }

  function waitForPlaybackEnd(audio) {
    return new Promise((resolve, reject) => {
      let settled = false;
      const timeout = setTimeout(() => {
        if (settled) return;
        settled = true;
        reject(new Error('انتهت مهلة تشغيل الصوت قبل حدث ended.'));
      }, 20000);
      const finish = callback => event => {
        if (settled) return;
        settled = true;
        clearTimeout(timeout);
        callback(event);
      };
      audio.addEventListener('play', () => updateDiagnostic('Playback State', 'playing'), {once: true});
      audio.addEventListener('ended', finish(() => {
        updateDiagnostic('Playback State', 'ended');
        resolve();
      }), {once: true});
      audio.addEventListener('error', finish(() => reject(new Error('فشل Playback بعد بدء الاختبار.'))), {once: true});

      Promise.resolve(audio.play()).catch(err => {
        if (settled) return;
        settled = true;
        clearTimeout(timeout);
        reject(err);
      });
    });
  }

  testVoiceBtn.addEventListener('click', async () => {
    const callBridgeRunning = !!(startBtn && startBtn.disabled && String(startBtn.textContent || '').includes('جود تعمل'));
    if (callBridgeRunning) {
      setMainStatus('أوقف جود أولًا قبل اختبار الصوت المحلي.');
      return;
    }

    testVoiceBtn.disabled = true;
    setMainStatus('جاري اختبار صوت جود على سماعة محلية مستقلة...');
    for (const key of Object.keys(diagnosticState)) diagnosticState[key] = '—';
    renderDiagnostics();

    let objectUrl = '';
    try {
      const sink = await choosePhysicalOutput();
      const sinkLabel = sink.label || ('device ' + sink.deviceId);
      updateDiagnostic('Selected Sink', sinkLabel);

      const response = await fetch(TTS_URL, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({text: 'السلام عليكم، معك جود من بكجات.'})
      });
      updateDiagnostic('TTS HTTP', String(response.status));
      if (!response.ok) {
        let detail = 'TTS HTTP ' + response.status;
        try { detail = (await response.json()).detail || detail; } catch (_) {}
        throw new Error(detail);
      }

      const blob = await response.blob();
      updateDiagnostic('Audio Bytes', String(blob.size));
      if (!blob || blob.size < 128) throw new Error('ملف Zariyah فارغ أو صغير جدًا.');

      const audio = new Audio();
      if (typeof audio.setSinkId !== 'function') {
        throw new Error('Chrome لا يدعم setSinkId على هذا الجهاز.');
      }
      await audio.setSinkId(sink.deviceId);
      updateDiagnostic('Selected Sink', sinkLabel + ' [' + sink.deviceId + ']');

      objectUrl = URL.createObjectURL(blob);
      audio.preload = 'auto';
      audio.src = objectUrl;
      updateDiagnostic('Audio Decode', 'checking');
      await waitForDecodedAudio(audio);
      updateDiagnostic('Audio Decode', 'ready');

      updateDiagnostic('Playback State', 'starting');
      await waitForPlaybackEnd(audio);
      setMainStatus('اختبار صوت جود المحلي انتهى على: ' + sinkLabel);
    } catch (err) {
      updateDiagnostic('Playback State', 'failed: ' + err.message);
      setMainStatus('تعذر اختبار صوت جود المحلي: ' + err.message);
    } finally {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      testVoiceBtn.disabled = false;
    }
  });
})();
</script>
""".strip()
    return template.replace("__TTS_URL__", json.dumps(tts_url))


def _local_self_test_bridge_page(session_id: int, request: Request, db: Session = Depends(core.get_db)):
    response = live._live_voice_bridge_page(session_id, request, db)
    if not isinstance(response, HTMLResponse):
        return response
    html = bytes(response.body).decode("utf-8", errors="replace")
    overlay = build_local_self_test_overlay(session_id)
    if "</body>" in html:
        html = html.replace("</body>", overlay + "</body>", 1)
    else:
        html += overlay
    return HTMLResponse(content=html, status_code=response.status_code)


def install_local_self_test_patch() -> None:
    target = "/admin/company/jood/voice/{session_id}/bridge"
    for route in core.app.routes:
        if getattr(route, "path", None) != target or "GET" not in (getattr(route, "methods", set()) or set()):
            continue
        route.endpoint = _local_self_test_bridge_page
        dependant = getattr(route, "dependant", None)
        if dependant is not None:
            dependant.call = _local_self_test_bridge_page
        return
    raise RuntimeError("Jood voice bridge route was not registered before local self-test patch")


install_local_self_test_patch()
