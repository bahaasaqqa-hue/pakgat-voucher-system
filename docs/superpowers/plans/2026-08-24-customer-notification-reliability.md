# Customer Notification Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver voucher notifications reliably and process receipt, support, and post-redemption rating replies without extra survey messages.

**Architecture:** Store each logical customer notification in a transactional database outbox, dispatch it through one retryable worker path, and resolve numeric inbound replies against the latest unresolved prompt. Reuse `JoodHandoff` as the human queue and suppress Jood whenever an open handoff exists.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy 2, PostgreSQL/SQLite tests, unittest, systemd, WhatsLoop.

**Spec:** `docs/superpowers/specs/2026-08-24-customer-notification-reliability-design.md`

## Global Constraints

- Do not send a separate survey message; append prompts to existing voucher and redemption messages.
- Do not run the existing direct sender and the outbox dispatcher for the same logical notification.
- Store no QR code, verification token, voucher code, phone, or raw provider response in logs/errors.
- Treat delivery as at-least-once and do not claim provider-level exactly-once behavior.
- Do not modify or reset production's locally changed `deploy/gce/pakgat-db-backup.sh`.
- Production activation follows staging verification and is not part of a code push.

---

### Task 1: Transactional customer notification outbox

**Files:**
- Create: `app/customer_notifications.py`
- Modify: `app/application.py`
- Test: `tests/test_voucher_webhook_reliability.py`
- Test: `tests/test_customer_notifications.py`

**Interfaces:**
- Produces: `CustomerNotification`, `ensure_customer_notification(db, voucher, notification_type, message_body)`, `dispatch_due_customer_notifications(db, send)`.
- Consumes: existing `Voucher`, WhatsLoop sending configuration, and SQLAlchemy session.

- [ ] **Step 1: Extend the existing failing replay test** to assert one voucher and one `voucher_issued` outbox row after two identical webhooks, with the row still retryable after a simulated initial failure.
- [ ] **Step 2: Run** `.venv-test/bin/python -m unittest tests.test_voucher_webhook_reliability -v` and confirm the replay/retry assertion fails.
- [ ] **Step 3: Add `CustomerNotification`** with a database unique constraint on `(voucher_id, notification_type)`, retry metadata, frozen message body, and response fields.
- [ ] **Step 4: Refactor voucher creation** so voucher and issuance outbox insertion share one commit; ensure the outbox row on the existing-voucher replay path.
- [ ] **Step 5: Remove the issuance direct-send scheduling** from the webhook, then implement a claim/send/update dispatcher whose injected sender returns success or raises a sanitized failure.
- [ ] **Step 6: Run** `.venv-test/bin/python -m unittest tests.test_customer_notifications tests.test_voucher_webhook_reliability -v` and confirm all focused tests pass.
- [ ] **Step 7: Commit** with `feat: add durable customer notification outbox`.

### Task 2: Redemption notification and message prompts

**Files:**
- Modify: `app/application.py`
- Modify: `app/customer_notifications.py`
- Test: `tests/test_customer_notifications.py`

**Interfaces:**
- Consumes: `ensure_customer_notification` from Task 1.
- Produces: issuance copy with reply choices and redemption copy with the 1–5 rating prompt.

- [ ] **Step 1: Add failing message-copy tests** that require the issuance message to contain choices `1` and `2`, and the redemption message to contain ratings `1`–`5`.
- [ ] **Step 2: Add a failing redemption transaction test** requiring one `voucher_redeemed` outbox row and no direct WhatsLoop scheduling.
- [ ] **Step 3: Run the focused tests** and confirm both behaviors fail for the intended reasons.
- [ ] **Step 4: Append the approved Arabic prompts** to the existing rendered messages and reserve the redemption outbox row in the redemption transaction.
- [ ] **Step 5: Run** `.venv-test/bin/python -m unittest tests.test_customer_notifications -v` and confirm the focused tests pass.
- [ ] **Step 6: Commit** with `feat: add voucher response and rating prompts`.

### Task 3: Numeric response resolution and handoff pause

**Files:**
- Modify: `app/customer_notifications.py`
- Modify: `app/jood_company_ops.py`
- Modify: `app/whatsloop_inbound.py`
- Test: `tests/test_customer_notification_responses.py`
- Test: `tests/test_jood_whatsapp_routing.py`

**Interfaces:**
- Produces: `resolve_customer_response(db, sender_phone, text) -> CustomerResponseResult | None` and `has_open_handoff(db, contact_id) -> bool`.
- Consumes: unresolved outbox prompts, normalized inbound sender identity, `create_handoff`, and the existing inbound event persistence.

- [ ] **Step 1: Add failing tests** for receipt `1`, support `2`, ratings `1` and `5`, invalid `6`, context-free `1`, redemption precedence, duplicate response idempotency, and one handoff only.
- [ ] **Step 2: Add a failing routing test** proving a message is persisted but Jood is not invoked when its contact has an open handoff.
- [ ] **Step 3: Run the focused tests** and confirm missing resolver/pause behavior fails.
- [ ] **Step 4: Implement response resolution** using the latest unresolved sent prompt, redemption-first precedence, one atomic response update, and no outbound acknowledgment for receipt/rating.
- [ ] **Step 5: Implement handoff lookup** and call the resolver after inbound persistence but before Jood generation; reply `2` creates the handoff and returns without an automated reply.
- [ ] **Step 6: Run** `.venv-test/bin/python -m unittest tests.test_customer_notification_responses tests.test_jood_whatsapp_routing -v` and confirm all focused tests pass.
- [ ] **Step 7: Commit** with `feat: process voucher feedback and pause Jood`.

### Task 4: Dispatcher service and operational documentation

**Files:**
- Create: `app/customer_notification_worker.py`
- Create: `deploy/gce/pakgat-customer-notifications.service`
- Create: `deploy/gce/pakgat-customer-notifications.timer`
- Modify: `deploy/gce/README.md`
- Test: `tests/test_customer_notification_worker.py`

**Interfaces:**
- Consumes: `dispatch_due_customer_notifications` from Task 1 and production `DATABASE_URL`/WhatsLoop environment.
- Produces: a finite oneshot command and a disabled-by-default systemd timer deployment unit.

- [ ] **Step 1: Add failing worker tests** for an empty queue, success, retryable failure, retry delay, and sanitized error persistence.
- [ ] **Step 2: Implement the finite worker entry point** that processes a bounded batch and exits nonzero only for configuration/database failure, not for one provider delivery failure.
- [ ] **Step 3: Add systemd service/timer units** that use `/etc/pakgat/pakgat.env`, run as `pakgat`, and never alter the backup service or script.
- [ ] **Step 4: Document staging activation, production activation, health query, and rollback** in `deploy/gce/README.md`; activation commands must not run automatically.
- [ ] **Step 5: Run** `.venv-test/bin/python -m unittest tests.test_customer_notification_worker -v` and confirm the worker tests pass.
- [ ] **Step 6: Commit** with `ops: add customer notification dispatcher timer`.

### Task 5: Regression gate and delivery

**Files:**
- Modify only files required by failures found in this task.

**Interfaces:**
- Consumes: all prior task outputs.
- Produces: a reviewable GitHub branch/commit; no automatic production deployment.

- [ ] **Step 1: Run** `.venv-test/bin/python -m compileall -q app tests` and require exit code 0.
- [ ] **Step 2: Run** `.venv-test/bin/python -m unittest discover -s tests -p 'test_*.py' -v` and require every test to pass.
- [ ] **Step 3: Inspect** `git diff --check`, `git status --short`, and the complete diff; remove local `.venv-test` artifacts from the worktree without touching source.
- [ ] **Step 4: Verify the rollback boundary** by confirming the changes contain no destructive DDL, no secret values, no production SSH/gcloud execution, and no edit to `deploy/gce/pakgat-db-backup.sh`.
- [ ] **Step 5: Push the reviewed branch** to GitHub and report the exact commit hash plus staging test commands; do not merge or deploy to production until staging evidence is approved.
