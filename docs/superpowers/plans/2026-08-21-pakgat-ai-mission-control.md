# Pakgat AI Mission Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild `/admin/company` as a factual, executive Pakgat AI Mission Control with a functional command bar, live AI Core, Situation Room, weighted decision queue, opportunity attention matrix, and evidence-based activity rail.

**Architecture:** Keep the existing FastAPI server-rendered dashboard and GCE deployment path. Add one pure helper module for deterministic command routing and ranking, then consume those helpers from `ai_company_dashboard_v2.py` using existing SQLAlchemy models and routes. No external AI, React, Tailwind build pipeline, Salla scope change, or fabricated metric is introduced.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy, server-rendered HTML/CSS, `unittest`.

**Spec:** `docs/superpowers/specs/2026-08-21-pakgat-ai-mission-control-design.md`

## Global Constraints

- Target only `https://voucher.pakgat.com/admin/company` and existing protected `/admin/company/*` pages.
- Do not modify Pakgat storefront, Salla theme/V3, Salla OAuth scopes/webhooks, Corporate Benefits, Customer Groups, or Special Offers.
- Do not invent visits, trends, growth percentages, AI confidence, predicted revenue, or source states.
- Keep deployment compatible with the existing GCE pull/restart process; no Node/React/Tailwind runtime build step.
- Use existing database rows as evidence and existing governance endpoints for approve/review actions.

---

### Task 1: Pure Mission-Control Ranking and Command Helpers

**Files:**
- Create: `tests/test_ai_company_mission_control.py`
- Create: `app/ai_company_mission_control.py`

**Interfaces:**
- Produces: `resolve_command(text: str) -> tuple[str | None, str]`
- Produces: `approval_weight(priority: str, approval_level: str, created_at=None, now=None) -> int`
- Produces: `opportunity_attention_score(stored_score, priority: str, status: str, created_at=None, now=None) -> int`
- Produces: `freshness_label(created_at, now=None) -> str`

- [ ] **Step 1: Write failing command-routing tests**

```python
class MissionControlTests(unittest.TestCase):
    def test_command_routes_only_to_allowed_internal_pages(self):
        self.assertEqual(resolve_command("اعرض الفرص")[0], "/admin/company/opportunities")
        self.assertEqual(resolve_command("القرارات والموافقات")[0], "/admin/company/governance")
        self.assertEqual(resolve_command("حالة المصادر")[0], "/admin/company/sources")
        self.assertEqual(resolve_command("شغل الشركة")[0], "RUN_COMPANY")

    def test_unknown_command_is_non_destructive(self):
        target, message = resolve_command("احذف كل شيء")
        self.assertIsNone(target)
        self.assertIn("غير مدعوم", message)
```

- [ ] **Step 2: Run the command tests and verify RED**

Run: `.venv/bin/python -m unittest -v tests/test_ai_company_mission_control.py`
Expected: FAIL because `app.ai_company_mission_control` does not exist.

- [ ] **Step 3: Add failing deterministic-weight tests**

```python
    def test_approval_weight_prioritizes_p0_and_ceo(self):
        self.assertGreater(approval_weight("P0", "CEO ONLY"), approval_weight("P2", "APPROVAL"))

    def test_opportunity_attention_uses_real_score_when_present(self):
        high = opportunity_attention_score(90, "P1", "new")
        low = opportunity_attention_score(20, "P1", "new")
        self.assertGreater(high, low)

    def test_opportunity_attention_is_deterministic_without_score(self):
        self.assertGreater(
            opportunity_attention_score(None, "P0", "new"),
            opportunity_attention_score(None, "P3", "review"),
        )
```

- [ ] **Step 4: Implement the minimal pure helper module**

Implement exact allowed command destinations and deterministic integer weights. Clamp opportunity attention to `0..100`. `freshness_label` returns Arabic relative-age labels from timestamps and never fabricates data.

- [ ] **Step 5: Run the mission-control tests and verify GREEN**

Run: `.venv/bin/python -m unittest -v tests/test_ai_company_mission_control.py`
Expected: all tests PASS.

- [ ] **Step 6: Commit Task 1**

Commit message: `Add Mission Control ranking helpers`

---

### Task 2: Functional Protected AI Command Bar

**Files:**
- Modify: `app/ai_company_dashboard_v2.py`
- Test: `tests/test_ai_company_mission_control.py`

**Interfaces:**
- Consumes: `resolve_command`
- Produces protected route: `POST /admin/company/command`

- [ ] **Step 1: Add a failing source-level test for the protected command endpoint and UI**

Test reads `app/ai_company_dashboard_v2.py` and asserts the source contains:

```python
self.assertIn('@core.app.post("/admin/company/command")', source)
self.assertIn("AI Command Bar", source)
self.assertIn("action='/admin/company/command'", source)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv/bin/python -m unittest -v tests/test_ai_company_mission_control.py`
Expected: FAIL because command route/UI does not exist.

- [ ] **Step 3: Implement the protected command endpoint**

Behavior:

```python
@core.app.post("/admin/company/command")
async def mission_control_command(request: Request, db: Session = Depends(core.get_db)):
    redirect = _admin_redirect(request)
    if redirect:
        return redirect
    form = await request.form()
    target, message = resolve_command(str(form.get("command") or ""))
    if target == "RUN_COMPANY":
        from app.ai_company_run_company import run_connected_company_cycle
        run_connected_company_cycle(db)
        return RedirectResponse("/admin/company?command=run", status_code=303)
    if target:
        core.log_event(db, "mission_control_command", details=f"target={target}")
        return RedirectResponse(target, status_code=303)
    return RedirectResponse("/admin/company?command=unknown", status_code=303)
```

Do not execute arbitrary URLs, shell commands, deletes, writes, or external communication.

- [ ] **Step 4: Implement the Command Bar UI**

Add a visible input and submit button near the top of the dashboard, plus quick chips linking to opportunities, approvals, sources, and technology. Unknown command state shows a small safe guidance message.

- [ ] **Step 5: Run mission-control tests and compile**

Run:

```bash
.venv/bin/python -m unittest -v tests/test_ai_company_mission_control.py
.venv/bin/python -m py_compile app/ai_company_mission_control.py app/ai_company_dashboard_v2.py
```

Expected: PASS / no compile output.

- [ ] **Step 6: Commit Task 2**

Commit message: `Add protected Mission Control command bar`

---

### Task 3: Situation Room, Decision Matrix, Opportunity Matrix, Activity Rail

**Files:**
- Modify: `app/ai_company_dashboard_v2.py`
- Test: `tests/test_ai_company_mission_control.py`

**Interfaces:**
- Consumes: `approval_weight`, `opportunity_attention_score`, `freshness_label`
- Consumes existing models: `CompanyApproval`, `CompanyDecision`, `CompanyAlert`, `CompanyTask`, `CompanyOpportunity`, `CompanyMetricSnapshot`

- [ ] **Step 1: Add failing source-level section tests**

```python
for marker in ("Situation Room", "Decision Matrix", "Opportunity Matrix", "Activity Rail", "AI Core"):
    self.assertIn(marker, source)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv/bin/python -m unittest -v tests/test_ai_company_mission_control.py`
Expected: FAIL until the sections exist.

- [ ] **Step 3: Query factual rows in `company_dashboard_v2`**

Load bounded lists:

- pending approvals: newest 8
- open alerts: severity P0/P1/P2, newest 8
- open/new opportunities: highest stored score/newest, max 8
- open tasks: newest 6
- latest decisions: newest 4
- latest health snapshots: newest 8 for optional factual trend points

Do not query or display fabricated visits or Google metrics.

- [ ] **Step 4: Build deterministic context**

For each approval, calculate queue weight with `approval_weight` and sort descending. For each opportunity, calculate `mission_score` with `opportunity_attention_score` and sort descending. Build activity entries only from actual row timestamps and source/action labels.

- [ ] **Step 5: Render the Situation Room**

Render four compact executive lanes:

- `ما الذي تغيّر؟`
- `ما الذي اكتشفه النظام؟`
- `ما الذي يحتاج قرارًا؟`
- `ما الذي يحتاج انتباهًا؟`

Every row includes source and freshness when available. Empty lanes show a neutral Arabic empty-state message.

- [ ] **Step 6: Render Decision Matrix**

Show title, source, priority, governance badge, deterministic queue weight, freshness, and existing Approve/Review controls. Never call the weight confidence.

- [ ] **Step 7: Render Opportunity Matrix**

Show title, source, status, priority, attention score, freshness, and link to full opportunities. Label the score `درجة أولوية` or `Attention Score`.

- [ ] **Step 8: Render evidence-based Activity Rail**

Combine recent real alerts/tasks/opportunities/approvals/decisions/snapshots, sort by timestamp, cap at 8 items, and display source + time. No simulated stream.

- [ ] **Step 9: Run tests and compile**

Run:

```bash
.venv/bin/python -m unittest -v tests/test_ai_company_mission_control.py tests/test_ai_company_readiness.py
.venv/bin/python -m py_compile app/ai_company_mission_control.py app/ai_company_dashboard_v2.py app/ai_company_sources.py
```

Expected: all tests PASS; compile succeeds.

- [ ] **Step 10: Commit Task 3**

Commit message: `Build Mission Control executive intelligence panels`

---

### Task 4: Mission Control Visual System and AI Core

**Files:**
- Modify: `app/ai_company_dashboard_v2.py`
- Test: `tests/test_ai_company_mission_control.py`

**Interfaces:**
- Consumes all Task 1–3 context.
- Produces responsive SaaS/AI presentation for `/admin/company` without frontend build tooling.

- [ ] **Step 1: Add failing visual-marker tests**

Assert source contains CSS markers for:

```python
"@keyframes aiCorePulse"
".mc-command"
".mc-situation"
".mc-matrix"
".mc-activity"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv/bin/python -m unittest -v tests/test_ai_company_mission_control.py`
Expected: FAIL until the new visual system exists.

- [ ] **Step 3: Implement the visual system**

Update CSS to use:

- `#F8FAFC`/`#F1F5F9` workspace
- `#0F172A` sidebar/primary ink
- `#2563EB`/`#3B82F6` primary interaction
- restrained violet/blue AI glow
- white 18–22px cards with soft shadows
- 160–220ms hover/focus transitions
- responsive RTL grid

Add AI Core in sidebar with CSS-only pulse and factual operational/source-count text.

- [ ] **Step 4: Keep KPI strip factual**

Top KPIs are Operational Health, System Completion, New Opportunities, and Orders. Historical health sparkline may render only from actual `CompanyMetricSnapshot` scores; if insufficient history, show a neutral mini-state instead.

- [ ] **Step 5: Run full tests and compile**

Run:

```bash
.venv/bin/python -m unittest -v tests/test_ai_company_mission_control.py tests/test_ai_company_readiness.py
.venv/bin/python -m py_compile app/ai_company_mission_control.py app/ai_company_dashboard_v2.py app/ai_company_sources.py main.py
```

Expected: all tests PASS and compilation succeeds.

- [ ] **Step 6: Review final diff against non-goals**

Compare from the pre-Mission-Control branch head and verify the net changed production files are limited to Mission Control/readiness UI modules and tests/docs; no Salla OAuth/Webhook/Corporate/Special Offer production file is modified.

- [ ] **Step 7: Commit Task 4**

Commit message: `Polish Pakgat AI Mission Control interface`

---

### Task 5: GCE Deployment Verification

**Files:**
- No code changes expected.

- [ ] **Step 1: Pull the exact `gce-migration` head on GCE**

Run from `/opt/pakgat-voucher-system`:

```bash
git fetch origin gce-migration
git pull --ff-only origin gce-migration
```

Preserve the known local modification in `deploy/gce/pakgat-db-backup.sh`.

- [ ] **Step 2: Run production-side tests and compilation**

```bash
.venv/bin/python -m unittest -v tests/test_ai_company_mission_control.py tests/test_ai_company_readiness.py
.venv/bin/python -m py_compile app/ai_company_mission_control.py app/ai_company_dashboard_v2.py app/ai_company_sources.py main.py
```

- [ ] **Step 3: Restart and verify service**

```bash
systemctl restart pakgat-voucher
sleep 3
systemctl is-active pakgat-voucher
curl -sS -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8000/
git rev-parse HEAD
git status --short --branch
```

Expected: service `active`, HTTP response valid, deployed HEAD equals remote `gce-migration`, and the existing local backup-script modification remains preserved.

- [ ] **Step 4: Authenticated visual verification**

Open `https://voucher.pakgat.com/admin/company` and verify AI Core, Command Bar, Situation Room, Decision Matrix, Opportunity Matrix, Activity Rail, factual KPI labels, and responsive layout.
