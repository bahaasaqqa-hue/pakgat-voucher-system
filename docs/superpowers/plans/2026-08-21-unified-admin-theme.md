# Pakgat Unified Admin Theme Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every authenticated HTML page under `/admin` use one Pakgat AI design system while preserving all existing routes and business behavior.

**Architecture:** Add a pure HTML theming core plus one final FastAPI response middleware imported last from `main.py`. Standard admin pages are wrapped in a shared sidebar/workspace shell; existing AI Company pages keep their internal AI layout but receive the same design tokens and a compact global-admin navigation strip, preventing double wrapping.

**Tech Stack:** Python, FastAPI/Starlette, server-rendered HTML, existing CSS/HTML components, unittest.

**Spec:** `docs/superpowers/specs/2026-08-21-unified-admin-theme-design.md`

## Global Constraints

- Apply to every HTML route whose path starts with `/admin`.
- `/admin/login` is branded but has no authenticated sidebar.
- Redirects, JSON, QR/image responses, downloads and POST-only action responses are not rewritten.
- Do not modify voucher logic, Salla OAuth/scopes/webhooks, Corporate live flags, Customer Groups, Special Offers, database schema or API calls.
- Do not invent metrics or statuses.
- Preserve the existing Mission Control content and avoid double wrapping `.ai-layout` pages.
- Import the final theme module last so current and future admin HTML gets normalized consistently.

---

### Task 1: Pure Admin Theme Renderer

**Files:**
- Create: `app/admin_theme_core.py`
- Create: `tests/test_admin_unified_theme.py`

**Interfaces:**
- Produces: `apply_admin_theme(html: str, path: str, logo_data_uri: str) -> str`
- Produces: `active_nav_key(path: str) -> str`
- Produces: `ADMIN_NAV_ITEMS`

- [ ] **Step 1: Write failing tests**

Tests assert that standard admin HTML gets `ua-shell`, the old `.topbar` is removed, required navigation links exist, the active link follows the path, AI pages are not double wrapped, login gets branding without authenticated navigation, non-admin HTML is unchanged, and transformation is idempotent.

- [ ] **Step 2: Verify tests fail before implementation**

Run:
```bash
python -m unittest -v tests/test_admin_unified_theme.py
```
Expected: import/module failure because `app.admin_theme_core` does not exist.

- [ ] **Step 3: Implement pure renderer**

Create a dependency-free module containing:
```python
ADMIN_NAV_ITEMS = (
    ("dashboard", "لوحة الإدارة", "/admin", "⌂"),
    ("company", "شركة بكجات الذكية", "/admin/company", "✦"),
    ("new_voucher", "قسيمة جديدة", "/admin/vouchers/new", "+"),
    ("audit", "سجل العمليات", "/admin/audit", "▤"),
    ("integrations", "تكامل سلة", "/admin/integrations", "⇄"),
    ("partners", "بيانات الشركاء", "/admin/local-partners", "◇"),
)
```

The renderer must:
- remove the legacy `<header class='topbar'>...` on authenticated standard admin pages;
- wrap standard pages in `.ua-shell`, `.ua-sidebar`, `.ua-workspace`, `.ua-top`, `.ua-content`;
- add logout as a POST form;
- inject shared CSS for cards, inputs, selects, textareas, tables, buttons, badges, alerts, pagination and responsive behavior;
- preserve existing body content and form actions;
- for `.ai-layout`, inject only shared theme CSS plus `.ua-ai-global` navigation, not another shell;
- for `/admin/login`, inject `.ua-login-brand` and login-specific styling only;
- do nothing outside `/admin`;
- return unchanged HTML if `data-unified-admin-theme` already exists.

- [ ] **Step 4: Run tests**

Run:
```bash
python -m unittest -v tests/test_admin_unified_theme.py
```
Expected: all tests pass.

---

### Task 2: FastAPI Final HTML Middleware

**Files:**
- Create: `app/admin_unified_theme.py`
- Modify: `main.py`
- Modify: `tests/test_admin_unified_theme.py`

**Interfaces:**
- Consumes: `apply_admin_theme()` from Task 1.
- Consumes: `PAKGAT_LOGO_DATA_URI` from `app.ai_company_mission_control_ui`.
- Produces: final `@core.app.middleware("http")` response transformer.

- [ ] **Step 1: Add source-structure tests**

Tests assert:
```python
self.assertIn('@core.app.middleware("http")', middleware_source)
self.assertGreater(main_source.find("admin_unified_theme"), main_source.find("corporate_ai_bridge"))
```
They also assert the middleware checks `/admin`, status redirects and `text/html` before reading/replacing the response body.

- [ ] **Step 2: Verify the new tests fail**

Run:
```bash
python -m unittest -v tests/test_admin_unified_theme.py
```
Expected: failures because middleware/import do not exist yet.

- [ ] **Step 3: Implement middleware and final import**

The middleware flow is:
```python
response = await call_next(request)
if not request.url.path.startswith("/admin"):
    return response
if 300 <= response.status_code < 400:
    return response
if "text/html" not in response.headers.get("content-type", ""):
    return response
body = b"".join([chunk async for chunk in response.body_iterator])
html = body.decode("utf-8", errors="replace")
rendered = apply_admin_theme(html, request.url.path, PAKGAT_LOGO_DATA_URI)
return HTMLResponse(rendered, status_code=response.status_code, headers=safe_headers)
```

Preserve response headers except recomputed `content-length`; do not alter redirect or non-HTML responses.

Import in `main.py` after `corporate_ai_bridge`:
```python
from app import admin_unified_theme as _admin_unified_theme  # noqa: F401 - final global admin visual shell
```

- [ ] **Step 4: Run tests and compile**

Run:
```bash
python -m unittest -v tests/test_admin_unified_theme.py tests/test_ai_company_mission_control.py tests/test_ai_company_readiness.py
python -m py_compile app/admin_theme_core.py app/admin_unified_theme.py main.py
```
Expected: all tests pass and compile exits 0.

---

### Task 3: Final Regression Review and One-Pull Deployment Gate

**Files:**
- Review only: `app/admin_theme_core.py`
- Review only: `app/admin_unified_theme.py`
- Review only: `main.py`
- Review only: `tests/test_admin_unified_theme.py`

**Interfaces:**
- Validates the complete theme without touching business logic.

- [ ] **Step 1: Compare against the pre-theme commit**

Run a commit comparison from the current production branch head before this project and verify changed production files are limited to the new theme modules plus `main.py`; tests/docs may also change.

- [ ] **Step 2: Verify required navigation and safety markers**

Confirm source includes:
```text
/admin
/admin/company
/admin/vouchers/new
/admin/audit
/admin/integrations
/admin/local-partners
/admin/login
/admin/logout
```
and excludes any Salla scope/OAuth/Corporate-live modifications.

- [ ] **Step 3: Run the complete relevant verification set**

Run:
```bash
python -m unittest -v tests/test_admin_unified_theme.py tests/test_ai_company_mission_control.py tests/test_ai_company_readiness.py
python -m py_compile app/admin_theme_core.py app/admin_unified_theme.py app/ai_company_mission_control.py app/ai_company_mission_control_ui.py main.py
```
Expected: zero failures and compile exit 0.

- [ ] **Step 4: Produce one GCE deployment block**

The deployment block performs one `git pull --ff-only`, runs the same tests/compile before restart, restarts `pakgat-voucher` once, verifies `active`, checks root HTTP 200, confirms unauthenticated `/admin` remains a 303 to `/admin/login`, prints final HEAD and preserves the known local `deploy/gce/pakgat-db-backup.sh` modification.