# Jood Voice Self-Test Separation Design

## Goal

Remove the fragile chain of runtime route monkey-patches around `/admin/company/jood/voice/{session_id}/bridge` and isolate the local Zariyah speaker test into a dedicated route.

## Approved architecture

- The original `app.jood_voice_bridge_ui.voice_bridge_page` is the only runtime owner of the GET `/bridge` route.
- `app.jood_voice_live_bridge` remains responsible only for the live-call start endpoint and the live-call JavaScript builder; it must not mutate the `/bridge` route at import time.
- `app.jood_voice_server_tts` remains responsible only for Zariyah synthesis and the authenticated TTS endpoint; it must not mutate the `/bridge` route or inject an overlay.
- Remove the old `jood_voice_local_self_test` and `jood_voice_self_test_inline` runtime patch modules.
- Add a dedicated GET `/admin/company/jood/voice/{session_id}/self-test` page in `app/jood_voice_self_test_page.py`.
- The `/bridge` page contains a normal `<a target="_blank">` link to the self-test page instead of a JavaScript-created test button.

## Self-test page behavior

The standalone page has one button: `🔊 تشغيل صوت جود التجريبي`. It uses the existing authenticated `/admin/company/jood/voice/{session_id}/tts` endpoint, obtains the MP3 blob, enumerates browser `audiooutput` devices, prefers a physical Realtek/Speakers/LG output, excludes Voicemeeter, Motorola, Hands-Free, VB-Audio and virtual cable outputs, applies `HTMLAudioElement.setSinkId()`, then plays until `ended`.

The page always exposes these diagnostics: `TTS HTTP`, `Audio Bytes`, `Selected Sink`, `Audio Decode`, `Playback State`.

The self-test page must not use MediaRecorder, STT, B1, B2, Phone Link logic, or the live call capture loop.

## Live-call behavior preserved

The call path remains `Phone Link remote audio → Voicemeeter B1 → MediaRecorder/STT → Jood → Zariyah → Chrome default call output → Voicemeeter AUX/B2 → Phone Link`. The live script keeps its existing start/opening/capture/finish behavior but no longer creates or handles a self-test button.

## Verification

Regression coverage must prove:

1. Exactly one GET `/bridge` route is registered and its endpoint module is `app.jood_voice_bridge_ui`.
2. The bridge HTML contains the standalone self-test link and the live call controls/diagnostics directly, with no runtime string-replacement dependency.
3. The live-call JS contains no `testVoiceBtn` self-test code.
4. The self-test page route is registered and its JS contains TTS fetch, `enumerateDevices`, physical-output filtering, `setSinkId`, and the five diagnostics, while excluding MediaRecorder/STT/call-loop behavior.
5. `main.py` no longer imports the two deprecated self-test patch modules.
6. The TTS and live bridge modules no longer install route patches at import time.
