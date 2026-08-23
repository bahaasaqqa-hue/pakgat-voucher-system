# Jood Core + Company AI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Jood a shared, stateful Company AI agent for customer and merchant WhatsApp conversations with real memory, deterministic mode/intent routing, URL safety, contacts, handoff state, and reusable voice-session APIs.

**Architecture:** Keep the existing signed WhatsLoop webhook as transport. Add a focused orchestration module for Company AI contacts, conversation turns, mode/intent routing, URL/claim validation, and call-session primitives. Refactor `jood_ai.py` so real history is passed as Vertex `contents`, while style examples remain only in the system instruction.

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL, stdlib urllib/JSON, Vertex AI Gemini via existing metadata-token flow.

**Spec:** `docs/superpowers/specs/2026-08-23-jood-company-ai-omnichannel-design.md`

## Global Constraints

- Preserve the existing WhatsLoop signed-webhook boundary and `from_me` loop protection.
- Preserve voucher, Salla, local-partner and backup behavior.
- Real memory: last 6–8 actual turns only; no few-shot examples as fake history.
- Outbound mode is assigned by Company AI contact type: `customer` or `merchant`.
- Canonical car-care URL: `https://pakgat.com/ar/%D8%A7%D9%84%D8%B9%D9%86%D8%A7%D9%8A%D8%A9-%D8%A8%D8%A7%D9%84%D8%B3%D9%8A%D8%A7%D8%B1%D8%A7%D8%AA/c1691767409`.
- Forbidden legacy path: `/ar/categories/car-care`.
- No fabricated prices, offers, discounts, order state, payment state, legal terms, commission rates, or completed escalation.
- Do-not-contact blocks future outbound activity.

---

### Task 1: Jood payload, memory and safe policy core

**Files:**
- Create: `app/jood_policy.py`
- Modify: `app/jood_ai.py`
- Test: `tests/test_jood_ai.py`
- Test: `tests/test_jood_policy.py`

**Interfaces:**
- Produces: `sanitize_jood_reply(text: str, allow_handoff_claim: bool = False) -> str`
- Produces: `approved_url_for_intent(intent: str) -> str | None`
- Produces: `build_vertex_payload(text: str, history=None, mode="customer", intent="general") -> dict`
- Produces: `generate_jood_reply(text: str, history=None, mode="customer", intent="general", opener=None) -> str`

- [ ] **Step 1: Write failing tests** proving the legacy URL is replaced, unknown URLs are replaced with the Pakgat home URL, the canonical car-care URL survives, fake few-shot `user/model` turns are absent from `contents`, real history is included in order, and merchant/customer runtime context is included in the system instruction.
- [ ] **Step 2: Verify the tests fail because the new interfaces/behavior do not exist.**
- [ ] **Step 3: Implement `jood_policy.py` and refactor `jood_ai.py` minimally to satisfy the tests.** Few-shot examples become plain labeled style examples inside system text, never `contents` turns.
- [ ] **Step 4: Run focused tests and the existing Jood AI suite.**
- [ ] **Step 5: Commit the task.**

### Task 2: Company AI contacts, conversation turns and router

**Files:**
- Create: `app/jood_company_ops.py`
- Test: `tests/test_jood_company_ops.py`

**Interfaces:**
- Produces SQLAlchemy models: `CompanyContact`, `JoodConversationTurn`, `JoodHandoff`.
- Produces: `resolve_contact_mode(db, phone, text="") -> tuple[CompanyContact, str]`
- Produces: `route_jood_intent(text: str, mode: str) -> str`
- Produces: `load_recent_turns(db, contact_id: int, limit: int = 8) -> list[dict[str,str]]`
- Produces: `append_turn(db, contact_id, channel, role, text, conversation_key) -> JoodConversationTurn`
- Produces: `can_contact(contact) -> bool`

- [ ] **Step 1: Write failing tests** for customer/merchant mode precedence, unknown-contact inference, merchant/customer intent routing, last-eight ordering, and do-not-contact blocking.
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Implement the models and pure helpers with no automatic outbound side effects.**
- [ ] **Step 4: Run focused tests.**
- [ ] **Step 5: Commit.**

### Task 3: Stateful WhatsLoop orchestration

**Files:**
- Modify: `app/whatsloop_inbound.py`
- Test: `tests/test_jood_whatsloop_orchestration.py`

**Interfaces:**
- Consumes `resolve_contact_mode`, `route_jood_intent`, `load_recent_turns`, `append_turn`, `generate_jood_reply`, and `sanitize_jood_reply`.
- Existing `_send_jood_reply` and webhook signature validation remain transport boundaries.

- [ ] **Step 1: Write failing orchestration tests** showing that a second dependent customer message receives previous real turns, a merchant contact gets merchant mode, group history is isolated by sender/contact, and a forbidden URL is sanitized before `_send_jood_reply`.
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Refactor only the Jood-reply block in `whatsloop_webhook`: resolve contact, load history, store user turn, generate with mode/intent/history, sanitize, send, then store assistant turn on success.**
- [ ] **Step 4: Run Jood + WhatsLoop tests.**
- [ ] **Step 5: Commit.**

### Task 4: Company AI Jood operations UI

**Files:**
- Modify: `app/jood_company_ops.py`
- Modify: `app/jood_company_ui.py`
- Modify: `main.py`
- Test: `tests/test_jood_company_ops.py`

**Interfaces:**
- Admin routes under `/admin/company/jood` for contacts and contact detail.
- Contact create/update actions support customer/merchant type, name/business, city, notes and do-not-contact.

- [ ] **Step 1: Write route/helper tests** for valid normalized Saudi phones, contact type validation, do-not-contact update, and admin-only route registration.
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Add compact Company AI UI using the existing admin shell; update Jood nav item to point at the Jood operations hub; import module from `main.py` before the final theme import.**
- [ ] **Step 4: Run focused tests and Python compile checks.**
- [ ] **Step 5: Commit.**

### Task 5: Regression verification

**Files:**
- No production changes unless verification exposes a regression.

- [ ] **Step 1: Run the complete Jood-focused test set.**
- [ ] **Step 2: Compile `main.py` and all modified modules.**
- [ ] **Step 3: Confirm the forbidden legacy URL no longer occurs in executable Jood prompt/example code.**
- [ ] **Step 4: Confirm WhatsLoop signature enforcement and `from_me` behavior are unchanged in diff review.**
- [ ] **Step 5: Open a PR for review before merging to `gce-migration`.**
