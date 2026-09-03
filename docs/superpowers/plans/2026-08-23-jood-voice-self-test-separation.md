# Jood Voice Self-Test Separation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/bridge` single-owner and move local Zariyah testing to a standalone speaker-test page.

**Architecture:** `jood_voice_bridge_ui` owns the GET bridge route directly and renders the proven live-call script from `jood_voice_live_bridge` without runtime HTML rewriting. A new `jood_voice_self_test_page` owns a separate GET self-test route and uses only the existing TTS endpoint plus browser output-device APIs.

**Tech Stack:** FastAPI, SQLAlchemy, vanilla JavaScript, HTMLAudioElement/setSinkId, edge-tts Zariyah, unittest.

**Spec:** `docs/superpowers/specs/2026-08-23-jood-voice-self-test-separation-design.md`

## Global Constraints

- Browser target is Google Chrome.
- Do not change Phone Link, Bluetooth, Voicemeeter B1/B2 routing, STT, or the TTS endpoint contract.
- Self-test must prefer physical Realtek/Speakers/LG outputs and reject Voicemeeter/Motorola Hands-Free/virtual outputs.
- Self-test diagnostics: TTS HTTP, Audio Bytes, Selected Sink, Audio Decode, Playback State.
- The GET `/bridge` route must have exactly one owner: `app.jood_voice_bridge_ui`.

---

### Task 1: Add architecture regression coverage

**Files:**
- Create: `tests/test_jood_voice_route_architecture.py`
- Modify: `tests/test_jood_voice_bridge_ui.py`
- Modify: `tests/test_jood_voice_server_tts.py`

**Interfaces:**
- Consumes: current FastAPI route registry and existing live/TTS modules.
- Produces: failing tests describing single bridge ownership and a standalone self-test route.

- [ ] **Step 1: Write failing tests** asserting one bridge GET route owned by `app.jood_voice_bridge_ui`, no deprecated patch imports, no live-script self-test listener, and a standalone self-test module/route with the approved browser diagnostics.
- [ ] **Step 2: Push tests on a `fix-jood-*` branch and verify the Jood PR workflow fails for the expected missing/legacy architecture assertions.**
- [ ] **Step 3: Commit the red tests.**

### Task 2: Remove route monkey-patches and render live bridge directly

**Files:**
- Modify: `app/jood_voice_bridge_ui.py`
- Modify: `app/jood_voice_live_bridge.py`
- Modify: `app/jood_voice_server_tts.py`
- Modify: `main.py`
- Delete: `app/jood_voice_local_self_test.py`
- Delete: `app/jood_voice_self_test_inline.py`

**Interfaces:**
- Consumes: `build_live_voice_bridge_script(session_id)` from `app.jood_voice_live_bridge`.
- Produces: canonical bridge GET endpoint with `start-jood`, diagnostics, and a normal self-test link.

- [ ] **Step 1: Remove import-time bridge patch installation from live bridge and TTS modules.**
- [ ] **Step 2: Remove dynamic `testVoiceBtn` creation/listener from the live call script.**
- [ ] **Step 3: Update `voice_bridge_page` to render live diagnostics and controls directly and include `<a href='/admin/company/jood/voice/{session_id}/self-test' target='_blank'>اختبار صوت جود (صفحة مستقلة)</a>`.**
- [ ] **Step 4: Remove deprecated patch imports/files.**
- [ ] **Step 5: Push and verify architecture tests progress to the standalone-page failure only.**

### Task 3: Add standalone physical-speaker self-test

**Files:**
- Create: `app/jood_voice_self_test_page.py`
- Modify: `main.py`

**Interfaces:**
- Consumes: authenticated TTS endpoint `/admin/company/jood/voice/{session_id}/tts`.
- Produces: GET `/admin/company/jood/voice/{session_id}/self-test` and standalone HTML/JS.

- [ ] **Step 1: Register the authenticated GET self-test route and validate the voice session/contact exist.**
- [ ] **Step 2: Render one `🔊 تشغيل صوت جود التجريبي` button and the five diagnostics.**
- [ ] **Step 3: Implement TTS fetch → Blob → enumerate audio outputs → select physical sink → `setSinkId` → decode/canplay → play/ended lifecycle.**
- [ ] **Step 4: Explicitly exclude Voicemeeter, VB-Audio, virtual cable, Motorola and Hands-Free outputs; fall back to `selectAudioOutput()` when Chrome cannot expose a named physical sink automatically.**
- [ ] **Step 5: Push and verify all focused Jood tests pass in GitHub Actions.**

### Task 4: Final verification and merge

**Files:**
- Review all changed files above.

**Interfaces:**
- Consumes: completed implementation.
- Produces: merge-ready PR without runtime route patching.

- [ ] **Step 1: Inspect PR diff for any remaining `/bridge` route endpoint mutation or self-test overlay/string replacement.**
- [ ] **Step 2: Confirm GitHub workflow is green and the route-ownership regression passes.**
- [ ] **Step 3: Merge to `gce-migration`.**
- [ ] **Step 4: Run the existing production deploy gate; require all Jood tests and health checks to pass before browser testing.**
