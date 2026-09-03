# Jood Vertex AI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Jood's fixed WhatsLoop greeting with a guarded Vertex AI conversational reply flow.

**Architecture:** Keep the existing verified WhatsLoop webhook and sender. Add a small Vertex REST client that authenticates from the GCE metadata service, then route eligible inbound text through it. Fail closed on AI/provider errors and run standard-library unit tests in the deployment gate.

**Tech Stack:** Python 3, FastAPI, urllib, Google Compute Engine metadata service, Vertex AI Gemini REST API, WhatsLoop REST API, unittest.

**Spec:** `docs/superpowers/specs/2026-08-23-jood-vertex-ai-design.md`

## Global Constraints
- Do not add or expose API keys or OAuth tokens.
- Preserve WhatsLoop HMAC verification exactly as the inbound security boundary.
- Preserve Salla, voucher, order, and customer business logic.
- Groups reply only when explicitly addressed to Jood; direct chats may auto-reply.
- AI failures must not send fabricated fallback content.
- One production deployment command for the operator.

---

### Task 1: Routing and Vertex client

**Files:**
- Create: `app/jood_ai.py`
- Modify: `app/jood_identity.py`
- Test: `tests/test_jood_ai.py`

**Interfaces:**
- Produces: `should_jood_ai_reply(text, chat_id) -> bool`
- Produces: `build_vertex_payload(text) -> dict`
- Produces: `extract_vertex_text(payload) -> str`
- Produces: `generate_jood_reply(text, opener=None) -> str`

- [ ] Write tests for direct/group routing, system prompt payload, metadata-token + Vertex request sequence, response extraction, and invalid response failure.
- [ ] Run the focused test and verify it fails before `app/jood_ai.py` exists.
- [ ] Implement the smallest standard-library Vertex client and routing helper that satisfy the tests.
- [ ] Run the focused test and verify all tests pass.

### Task 2: WhatsLoop smart reply integration

**Files:**
- Modify: `app/whatsloop_inbound.py`

**Interfaces:**
- Consumes: `should_jood_ai_reply` and `generate_jood_reply`.
- Sends generated text through the existing `/messages/send-reply` provider path.

- [ ] Replace the fixed greeting sender with a sender accepting generated text.
- [ ] Route eligible `message.received` events to Vertex and only send when generation succeeds.
- [ ] Log AI failures safely without tokens or secrets.
- [ ] Preserve duplicate-event handling and webhook signature verification.

### Task 3: Deployment safety gate

**Files:**
- Modify: `deploy/gce/install-ai-company.sh`

**Interfaces:**
- Runs `python -m unittest discover -s tests -p 'test_jood_ai.py' -q` before restarting production.

- [ ] Add the focused unit-test gate after syntax compilation and before systemd restart.
- [ ] Keep the existing health checks and backup-script behavior unchanged.

### Task 4: Review and production acceptance

- [ ] Review the final diff for unrelated Salla/voucher changes or secret material.
- [ ] Deploy once after enabling Vertex AI API and granting the VM service account `roles/aiplatform.user`.
- [ ] Confirm deployment gate and `/company/health` succeed.
- [ ] Send one WhatsApp message addressed to Jood and confirm the response is generated rather than the old fixed test string.
