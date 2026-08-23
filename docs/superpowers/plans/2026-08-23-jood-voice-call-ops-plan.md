# Jood Voice + Call Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Company AI call campaigns, half-duplex Jood voice sessions, 30-second queue cooldown, call logging, and a Windows/Edge browser bridge that reuses the same Jood Core.

**Architecture:** The server owns contact type, call campaign/session state, transcript, Jood generation, summary and outcomes. The Windows laptop remains the audio edge: Motorola/eSIM + Phone Link + Voicemeeter + Microsoft Edge. Voice v1 is manually dialed but AI-controlled after pickup; the browser bridge posts recognized utterances to an authenticated Company AI call-session API and plays returned Arabic speech to the Voicemeeter AUX route.

**Tech Stack:** FastAPI, SQLAlchemy/PostgreSQL, browser Web Speech API for v1 STT, pluggable TTS adapter targeting `ar-SA-ZariyahNeural`, existing Vertex AI Jood Core.

**Spec:** `docs/superpowers/specs/2026-08-23-jood-company-ai-omnichannel-design.md`

## Global Constraints

- Manual Phone Link dialing remains v1; automatic dial is out of scope until Windows/Android control is proven.
- Call window is enforced server-side.
- Cooldown is fixed at 30 seconds between completed attempts.
- One eSIM means one active call at a time.
- Customer/Merchant mode comes from Company AI contact type, not model guessing for outbound calls.
- First release is half-duplex; pause recognition while Jood speaks.
- Call log must persist outcome, summary, timestamps, transcript when enabled, follow-up and do-not-contact.
- Do-not-contact blocks future call and WhatsApp campaign queueing.

---

### Task 1: Call campaign, session and log models

**Files:**
- Modify: `app/jood_company_ops.py`
- Test: `tests/test_jood_call_ops.py`

**Interfaces:**
- Models: `JoodCallCampaign`, `JoodCallSession`, `JoodCallLog`.
- Produces: `call_window_is_open(campaign, now) -> bool`
- Produces: `cooldown_is_satisfied(campaign, last_finished_at, now) -> bool`
- Produces: `next_callable_contact(db, campaign, now) -> CompanyContact | None`

- [ ] **Step 1: Write failing tests** for inside/outside call windows, 30-second cooldown, one-contact-at-a-time queue selection, type filtering, and do-not-contact exclusion.
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Implement minimal models/helpers.**
- [ ] **Step 4: Run focused tests.**
- [ ] **Step 5: Commit.**

### Task 2: Reusable voice-session API

**Files:**
- Modify: `app/jood_company_ops.py`
- Test: `tests/test_jood_voice_session.py`

**Interfaces:**
- Admin API creates a voice session for a chosen contact/campaign.
- `POST /admin/company/jood/voice/{session_id}/turn` accepts one transcript utterance.
- Response returns sanitized Jood reply, mode, intent and session state.
- `POST /admin/company/jood/voice/{session_id}/finish` records outcome and generates/stores a concise call summary.

- [ ] **Step 1: Write failing tests** for authenticated session creation, customer/merchant mode, real-turn memory reuse, safe URL filtering, transcript accumulation, finish/outcome persistence and do-not-contact outcome propagation.
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Implement APIs using the same `generate_jood_reply` path as WhatsApp.**
- [ ] **Step 4: Run focused tests.**
- [ ] **Step 5: Commit.**

### Task 3: Edge/Voicemeeter half-duplex voice bridge

**Files:**
- Create: `app/jood_voice_bridge_ui.py`
- Modify: `main.py`
- Test: `tests/test_jood_voice_bridge_ui.py`

**Interfaces:**
- `GET /admin/company/jood/voice/{session_id}/bridge` renders an admin-authenticated browser page.
- Browser recognition posts one final utterance at a time to the turn endpoint.
- Recognition pauses during speech playback and resumes afterward.
- UI clearly identifies `ar-SA-ZariyahNeural` as the target voice and exposes provider/availability status instead of silently switching identities.

- [ ] **Step 1: Write failing route/content tests** proving the page is admin-only, targets `ar-SA`, uses half-duplex pause/resume, and calls only the active session endpoint.
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Implement the focused bridge page using existing admin shell.**
- [ ] **Step 4: Run focused tests and compile checks.**
- [ ] **Step 5: Commit.**

### Task 4: Call campaign UI and Call Log

**Files:**
- Modify: `app/jood_company_ops.py`
- Modify: `app/jood_company_ui.py`
- Test: `tests/test_jood_call_ops.py`

**Interfaces:**
- Company AI Jood hub displays contacts, call campaigns, next callable contact and call log.
- Campaign form captures customer/merchant target, goal, start/end time and transcript preference; cooldown displays fixed 30 seconds.
- “Call with Jood” creates a session and opens the bridge; the operator dials that displayed contact manually in Phone Link.

- [ ] **Step 1: Write failing UI/helper tests** for campaign validation and visible queue/log fields.
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Implement compact UI without altering unrelated Company AI pages.**
- [ ] **Step 4: Run focused tests.**
- [ ] **Step 5: Commit.**

### Task 5: End-to-end regression and deployment gate

**Files:**
- Modify: `deploy/gce/install-ai-company.sh` only if required to include new focused tests/dependency checks; preserve `deploy/gce/pakgat-db-backup.sh` untouched.

- [ ] **Step 1: Run all Jood core, WhatsLoop, policy, call and voice-bridge tests.**
- [ ] **Step 2: Compile all modified modules.**
- [ ] **Step 3: Verify a voice turn uses the same core payload/history/policy as WhatsApp.**
- [ ] **Step 4: Verify the 30-second cooldown and call window rules in tests.**
- [ ] **Step 5: Review diff to prove backup script, voucher flow, Salla flow and webhook signature enforcement were not modified.**
