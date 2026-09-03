# Jood Professional WhatsApp Outreach Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one-click individual outreach and automatic Excel/CSV campaigns using stored customer/merchant defaults while preserving inbound website customer service.

**Architecture:** Add a focused settings/import module, reuse the existing Jood generation and WhatsLoop delivery boundaries, and extend campaign dispatches into a database-backed queue processed automatically. Inbound webhook routing remains unchanged and regression tests prove outbound instructions cannot enter inbound prompts.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, PostgreSQL, `openpyxl`, `unittest`/pytest compatibility.

**Spec:** `docs/superpowers/specs/2026-08-23-jood-professional-whatsapp-outreach-design.md`

## Global Constraints

- Voice is excluded.
- Preserve the existing WhatsLoop inbound customer-support path and website number behavior.
- Blank optional instructions resolve to stored defaults.
- Enforce do-not-contact, normalized Saudi numbers, deduplication, idempotency and truthful provider status.
- Preserve `deploy/gce/pakgat-db-backup.sh` unchanged.

---

### Task 1: Stored outreach defaults and prompt isolation

**Files:**
- Create: `app/jood_whatsapp_settings.py`
- Modify: `app/jood_outbound.py`
- Modify: `main.py`
- Test: `tests/test_jood_whatsapp_settings.py`

**Interfaces:**
- Produces: `JoodWhatsAppSetting`, `default_outreach_prompt(db, contact_type) -> str`, and `resolved_outreach_instruction(db, contact_type, override="") -> str`.
- Consumes: existing SQLAlchemy `core.Base` and session.

- [ ] Write failing tests proving customer/merchant defaults differ, blank override uses the default, and a nonblank override supplements rather than replaces the default.
- [ ] Run `python -m unittest tests.test_jood_whatsapp_settings -v` and verify failures are caused by the missing module/functions.
- [ ] Implement the settings model, seeded constants, resolver and protected settings page/save route.
- [ ] Update outbound composition to use the resolver without modifying `whatsloop_inbound.py`.
- [ ] Run the targeted tests and commit.

### Task 2: One-click individual outreach

**Files:**
- Modify: `app/jood_outbound.py`
- Modify: `app/jood_company_control_ui.py`
- Test: `tests/test_jood_outbound.py`

**Interfaces:**
- Produces: `build_contact_outreach_context(contact, instruction) -> str` and one form accepting an optional special instruction.
- Consumes: `resolved_outreach_instruction` from Task 1 and existing `_send_whatsloop_text`.

- [ ] Write failing tests proving a blank special instruction is accepted and contact fields are included without changing inbound mode.
- [ ] Run the targeted test and verify the expected failure.
- [ ] Make the existing contact page optional-instruction based and add the direct phone/name/type form to the control center.
- [ ] Generate, sanitize, send, record history/stage and redirect with a visible outcome.
- [ ] Run targeted tests and commit.

### Task 3: Excel/CSV import and automatic campaign queue

**Files:**
- Create: `app/jood_whatsapp_import.py`
- Modify: `app/jood_whatsapp_campaign.py`
- Modify: `app/jood_whatsapp_campaign_ui.py`
- Modify: `main.py`
- Modify: `requirements.txt`
- Test: `tests/test_jood_whatsapp_import.py`
- Test: `tests/test_jood_whatsapp_campaign.py`

**Interfaces:**
- Produces: `parse_contact_upload(filename: str, body: bytes, default_type: str) -> list[ImportedContact]`, `queue_campaign_contacts(db, campaign) -> int`, and `process_campaign_queue(campaign_id: int) -> None`.
- Consumes: settings resolver, contact upsert, generator and WhatsLoop sender.

- [ ] Write failing tests for CSV/XLSX parsing, header aliases, phone normalization, deduplication, do-not-contact filtering and campaign/contact uniqueness.
- [ ] Run targeted tests and verify expected failures.
- [ ] Add `openpyxl`, implement bounded file parsing and contact upserts.
- [ ] Extend dispatch statuses to queued/generating/sent/replied/failed and process queued rows automatically using a background task with pacing.
- [ ] Replace the required goal field with an optional instruction and a single “رفع وبدء الحملة” action.
- [ ] Run targeted tests and commit.

### Task 4: Results, inbound regression protection and release verification

**Files:**
- Modify: `app/jood_whatsapp_campaign_ui.py`
- Modify: `app/whatsloop_inbound.py`
- Test: `tests/test_jood_whatsapp_professional_workflow.py`
- Test: `tests/test_jood_ai.py`

**Interfaces:**
- Produces: campaign totals/status table and inbound reply status updates only.
- Consumes: campaign and dispatch models; existing inbound generation path remains authoritative.

- [ ] Write failing regression tests proving inbound prompts contain no outbound campaign/default instruction and incoming replies update history/results without mode contamination.
- [ ] Run the regression tests and verify the expected failure only for missing result updates.
- [ ] Add result aggregation and reply linkage without changing inbound prompt construction.
- [ ] Run all WhatsApp/Jood tests, then `python -m unittest discover -s tests -v`.
- [ ] Inspect `git diff`, confirm the protected backup script is untouched, and commit the verified feature.
