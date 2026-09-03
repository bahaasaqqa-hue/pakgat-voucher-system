# Pakgat Opportunity Assignment & Agent Reporting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build secure agent reporting for assigned opportunities, newest-first operational views, 48-hour completion archiving, optional evidence upload, and consistent Pakgat AI typography.

**Architecture:** Add a focused `ai_company_agent_reporting.py` module that owns report-link capabilities, append-only agent reports, image validation/storage, public report routes, and lifecycle helpers. Keep the existing manual WhatsLoop assignment route, but append a secure report URL only after explicit admin confirmation. Keep the dedicated opportunities page in `ai_company_opportunity_compact.py`, enriching it with dispatch/report context and automatic archive while leaving Salla, Corporate Benefits, and voucher logic untouched.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy, Pillow, python-multipart, PostgreSQL, unittest.

**Spec:** `docs/superpowers/specs/2026-08-21-opportunity-agent-reporting-design.md`

## Global Constraints

- Branch: `gce-migration`.
- No changes to Salla OAuth/scopes/webhooks, Corporate Benefits, voucher issue/redeem behavior, or WhatsLoop provider configuration.
- Raw report tokens must never be stored; only SHA-256 hashes may be persisted.
- Evidence accepts JPEG/PNG/WebP only, maximum 5 MB, verifies with Pillow, and is re-encoded to WebP.
- Evidence root defaults to `/var/lib/pakgat/opportunity-evidence` and is overrideable with `OPPORTUNITY_EVIDENCE_DIR`.
- A WhatsLoop failure must revoke the capability and must not mark the opportunity assigned.
- `won`/`lost` remain visible for 48 hours, then auto-archive idempotently.
- Existing local production modification `deploy/gce/pakgat-db-backup.sh` must remain untouched.
- `admin_unified_theme` remains the final import in `main.py`.

---

### Task 1: Secure capability and agent-report domain

**Files:**
- Create: `app/ai_company_agent_reporting.py`
- Create: `tests/test_ai_company_agent_reporting.py`
- Modify: `main.py`

**Interfaces:**
- Produces `OpportunityReportLink` and `OpportunityAgentReport` SQLAlchemy models.
- Produces `hash_report_token(raw_token: str) -> str`.
- Produces `create_report_capability(db, dispatch_id: int, opportunity_id: int, agent_id: int, now: datetime | None = None) -> tuple[OpportunityReportLink, str]`.
- Produces `resolve_report_capability(db, raw_token: str, now: datetime | None = None) -> OpportunityReportLink | None`.
- Produces `revoke_report_capability(db, link, now: datetime | None = None) -> None` and `revoke_opportunity_links(db, opportunity_id: int, now: datetime | None = None) -> None`.
- Produces `report_url(raw_token: str) -> str`, `append_report_link(message: str, url: str) -> str`, and `map_agent_action(current_status: str, action: str) -> str`.
- Produces `archive_completed_opportunities(db, now: datetime | None = None) -> int`.

- [ ] **Step 1: Write failing tests for token hashing, capability resolution, action mapping, and 48-hour archive**

```python
class AgentReportingTests(unittest.TestCase):
    def test_raw_token_is_not_persisted(self):
        link, raw = reporting.create_report_capability(self.db, 7, self.opportunity.id, 3, now=self.now)
        self.db.commit()
        self.assertNotEqual(link.token_hash, raw)
        self.assertEqual(link.token_hash, reporting.hash_report_token(raw))

    def test_won_is_archived_only_after_48_hours(self):
        self.opportunity.status = "won"
        self.opportunity.updated_at = self.now - timedelta(hours=47)
        self.db.commit()
        self.assertEqual(reporting.archive_completed_opportunities(self.db, self.now), 0)
        self.opportunity.updated_at = self.now - timedelta(hours=49)
        self.db.commit()
        self.assertEqual(reporting.archive_completed_opportunities(self.db, self.now), 1)
        self.assertEqual(self.opportunity.status, "archived")
```

- [ ] **Step 2: Run red gate**

Run:

```bash
.venv/bin/python -m unittest -v tests/test_ai_company_agent_reporting.py
```

Expected: FAIL because `app.ai_company_agent_reporting` does not exist.

- [ ] **Step 3: Implement models and pure/domain helpers**

Core behavior:

```python
def hash_report_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def map_agent_action(current_status: str, action: str) -> str:
    mapping = {
        "contacted": "contacted",
        "visited": "contacted",
        "interested": "replied",
        "replied": "replied",
        "negotiating": "negotiating",
        "won": "won",
        "lost": "lost",
    }
    if action == "follow_up":
        return current_status if current_status in IN_PROGRESS_STATUSES else "assigned"
    if action not in mapping:
        raise ValueError("Invalid agent report action")
    return mapping[action]
```

Capability creation uses `secrets.token_urlsafe(32)`, stores only SHA-256, expires after 30 days, and revokes earlier active links for the same opportunity before creating the new capability.

- [ ] **Step 4: Register the module before opportunity compact UI**

`main.py` import order:

```python
from app import ai_company_dispatch as _ai_company_dispatch
from app import ai_company_agent_reporting as _ai_company_agent_reporting
from app import ai_company_ar as _ai_company_ar
from app import ai_company_opportunity_compact as _ai_company_opportunity_compact
```

Keep `admin_unified_theme` last.

- [ ] **Step 5: Run domain tests**

Run:

```bash
.venv/bin/python -m unittest -v tests/test_ai_company_agent_reporting.py
```

Expected: PASS.

---

### Task 2: Public mobile agent report form and evidence

**Files:**
- Modify: `app/ai_company_agent_reporting.py`
- Modify: `tests/test_ai_company_agent_reporting.py`

**Interfaces:**
- Produces public `GET /agent/report/{token}` and `POST /agent/report/{token}`.
- Produces admin-protected `GET /admin/company/agent-reports/{report_id}/evidence`.
- Produces `store_verified_evidence(data: bytes, content_type: str, root: Path | None = None) -> tuple[str, str]`.

- [ ] **Step 1: Add failing tests for evidence validation and public-route source guards**

```python
def test_valid_png_is_reencoded_as_random_webp(self):
    filename, media = reporting.store_verified_evidence(self.png_bytes, "image/png", self.temp_dir)
    self.assertTrue(filename.endswith(".webp"))
    self.assertEqual(media, "image/webp")
    self.assertNotIn("original", filename)


def test_non_image_is_rejected(self):
    with self.assertRaises(ValueError):
        reporting.store_verified_evidence(b"not an image", "image/png", self.temp_dir)
```

- [ ] **Step 2: Implement evidence validation**

Read no more than 5 MB + 1 byte from uploads. Reject unsupported MIME. Verify with Pillow, reopen, convert safely to RGB/RGBA as needed, and save a random `secrets.token_hex(16) + ".webp"` under the configured evidence root. If storage fails, remove any partial file and do not create a report.

- [ ] **Step 3: Implement public report GET/POST**

GET resolves hashed token, verifies not revoked/expired/archived, loads only the associated opportunity/agent, and returns a mobile-first Arabic RTL form with `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, and `X-Robots-Tag: noindex, nofollow`.

POST validates action, notes length <= 2000, optional follow-up Saudi local datetime, optional evidence, then appends an `OpportunityAgentReport` and updates `CompanyOpportunity.status` via `map_agent_action` plus `updated_at`.

- [ ] **Step 4: Implement authenticated evidence serving**

Require `core.require_admin(request)`. Load report by ID, ensure `evidence_filename` is present, resolve only the basename under the configured root, and return WebP with no public directory exposure.

- [ ] **Step 5: Run agent-report tests**

```bash
.venv/bin/python -m unittest -v tests/test_ai_company_agent_reporting.py
```

Expected: PASS.

---

### Task 3: Append secure link to manual WhatsLoop assignment

**Files:**
- Modify: `app/ai_company_dispatch.py`
- Modify: `tests/test_ai_company_agent_reporting.py`

**Interfaces:**
- Consumes reporting helpers lazily inside assignment POST to avoid import cycles.
- Stores the exact sent message, including secure report URL, in `OpportunityDispatch.message`.

- [ ] **Step 1: Add failing source/behavior tests**

Assert the assignment handler calls `create_report_capability`, appends `report_url`, stores the final message, revokes the capability on provider failure, and only sets `opportunity.status = "assigned"` on success.

- [ ] **Step 2: Integrate capability creation into assignment POST**

After admin confirmation and agent validation:

```python
from app import ai_company_agent_reporting as reporting

dispatch = OpportunityDispatch(..., status="sending")
db.add(dispatch)
db.flush()
link, raw_token = reporting.create_report_capability(
    db, dispatch.id, opportunity.id, agent.id
)
final_message = reporting.append_report_link(message, reporting.report_url(raw_token))
dispatch.message = final_message[:4000]
db.commit()
ok, provider_status = _send_whatsloop(agent.phone, dispatch.message)
```

On send failure, revoke the newly created link and leave opportunity status unchanged. On success, set dispatch sent fields and opportunity `assigned`.

- [ ] **Step 3: Clarify assignment form UI**

Add a small note under the editable message: `سيضيف النظام تلقائيًا رابطًا آمنًا للمندوب لتحديث النتيجة ورفع إثبات اختياري.` The secure token itself is not exposed in the admin form.

- [ ] **Step 4: Run regression tests**

```bash
.venv/bin/python -m unittest -v \
  tests/test_ai_company_agent_reporting.py \
  tests/test_ai_company_mission_control.py \
  tests/test_ai_company_readiness.py
```

Expected: PASS.

---

### Task 4: Redesign opportunities page and standardize AI typography

**Files:**
- Modify: `app/ai_company_opportunity_compact.py`
- Modify: `app/admin_theme_core.py`
- Modify: `tests/test_admin_unified_theme.py`
- Modify: `tests/test_ai_company_agent_reporting.py`

**Interfaces:**
- Consumes `archive_completed_opportunities`, `OpportunityAgentReport`, `OpportunityDispatch`, and `CompanyAgent`.
- Produces four UI sections: New, In Progress, Recently Completed 48h, Archive.

- [ ] **Step 1: Add failing tests for ordering and typography markers**

Source assertions require new query ordering:

```python
.order_by(ai_company.CompanyOpportunity.created_at.desc(), ai_company.CompanyOpportunity.id.desc())
```

for new rows, and `updated_at DESC, id DESC` for in-progress/recent/archive. Theme assertions require scoped AI typography hooks for H1 22px, H2 17px, H3 14px, body 13px, tables 12px, muted 11px, controls 12px, KPI 28px.

- [ ] **Step 2: Run red gate**

```bash
.venv/bin/python -m unittest -v \
  tests/test_ai_company_agent_reporting.py \
  tests/test_admin_unified_theme.py
```

Expected: FAIL on old score-first ordering and missing typography hooks.

- [ ] **Step 3: Implement four-section operational page**

Before querying call:

```python
archive_completed_opportunities(db)
```

Use:

- New: `created_at DESC, id DESC`
- In progress: `updated_at DESC, id DESC`
- Recent: `won/lost` and `updated_at >= now - timedelta(hours=48)`
- Archive: `status == "archived"`, newest first, collapsed by default.

Build latest successful dispatch per opportunity and latest/all agent reports per opportunity. Render `مسندة إلى: <agent>` prominently, show assignment time and latest agent action, and include evidence links/report history in expandable details.

- [ ] **Step 4: Revoke report links on manual archive**

When admin manually archives an opportunity, call `revoke_opportunity_links(db, opportunity_id)` before commit.

- [ ] **Step 5: Add scoped typography override**

Add only under `body[data-unified-admin-theme='ai']`, with `!important` where needed to defeat legacy inline sizes. Do not alter public/customer pages.

- [ ] **Step 6: Run full verification suite**

```bash
.venv/bin/python -m unittest -v \
  tests/test_ai_company_agent_reporting.py \
  tests/test_admin_unified_theme.py \
  tests/test_ai_company_mission_control.py \
  tests/test_ai_company_readiness.py

.venv/bin/python -m py_compile \
  app/ai_company_agent_reporting.py \
  app/ai_company_dispatch.py \
  app/ai_company_opportunity_compact.py \
  app/admin_theme_core.py \
  main.py
```

Expected: all tests PASS and compile exits 0.

---

### Task 5: One-shot GCE deployment and production verification

**Files:** No repository files changed.

**Interfaces:** Production filesystem must provide writable evidence root.

- [ ] **Step 1: Prepare evidence directory without touching repo backup script**

```bash
SERVICE_USER="$(systemctl show -p User --value pakgat-voucher)"
[ -n "$SERVICE_USER" ] || SERVICE_USER=root
install -d -m 0750 -o "$SERVICE_USER" -g "$SERVICE_USER" /var/lib/pakgat/opportunity-evidence
```

- [ ] **Step 2: Pull once, run tests/compile, then restart once**

Use `git pull --ff-only origin gce-migration`; never `git reset --hard`. Stop before restart if tests or compile fail.

- [ ] **Step 3: Verify production**

Check service active, root HTTP 200, unauthenticated `/admin` redirects to login, `/agent/report/bogus-token` returns friendly invalid-link response, assignment page renders for a controlled opportunity, and an actual controlled assignment includes the report URL.

- [ ] **Step 4: Controlled end-to-end agent report**

Open the secure URL from the controlled assignment, submit one non-destructive action (`contacted`) without evidence first, confirm the report appears under the assigned opportunity, then optionally test one image upload and confirm evidence is viewable only through authenticated admin.
