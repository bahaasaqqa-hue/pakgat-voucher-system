# Admin Navigation & Typography Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Pakgat AI Company the primary admin destination, organize the left navigation into clear operational groups, expose Merchant and Settlement pages, and standardize Cairo typography/weights across authenticated admin pages.

**Architecture:** Keep this release presentation-only by extending the existing `app/merchant_ui_cairo.py` response layer, which already runs after the unified admin theme. It will apply Cairo to all authenticated admin HTML, rebuild only the standard `.ua-nav` markup into grouped sections, keep finance-label translation restricted to finance routes, and leave all APIs, POSTs, redirects, WhatsApp/Jood logic, voucher logic, and settlement logic unchanged.

**Tech Stack:** Python 3.12, FastAPI response middleware, HTML/CSS string transformation, unittest.

**Spec:** User-approved navigation and typography requirements from the 2026-08-27 Pakgat admin UI review.

## Global Constraints

- Cairo is the single admin UI font.
- Main headings and section headings use bold weight 700.
- Ordinary navigation, descriptions, tables, controls, and body text use regular/medium weights 400-500.
- Active navigation may use 600; avoid 800/900/950 visual weights in the final override layer.
- `شركة بكجات الذكية` is the first/primary standard admin navigation destination.
- `/admin` remains available as the secondary `ملخص الإدارة` page; no route redirect is introduced in this presentation-only release.
- Add direct standard navigation links for `/admin/merchants` and `/admin/settlements`.
- Keep finance term translation restricted to `/admin`, `/admin/merchants*`, and `/admin/settlements*`.
- Do not modify Jood, WhatsApp, campaigns, Salla business behavior, QR behavior, voucher lifecycle, finance calculations, settlement worker behavior, or API semantics.

---

### Task 1: Lock navigation and typography behavior with tests

**Files:**
- Create: `tests/test_admin_navigation_typography.py`

**Interfaces:**
- Consumes: `app.merchant_ui_cairo.apply_merchant_ui_polish(source: str, path: str) -> str`
- Produces: regression expectations for grouped navigation, Cairo coverage, weight hierarchy, finance translation scope, and non-admin safety.

- [ ] **Step 1: Write failing tests** for grouped standard navigation, primary Company link, Merchant/Settlement links, global Cairo coverage, typography weights, finance translation preservation, and non-admin safety.
- [ ] **Step 2: Run the full regression workflow** and verify the new tests fail before implementation.
- [ ] **Step 3: Commit the red tests.**

### Task 2: Implement grouped navigation and stable typography

**Files:**
- Modify: `app/merchant_ui_cairo.py`

**Interfaces:**
- Keeps: `apply_merchant_ui_polish(source: str, path: str) -> str`
- Adds internal helpers for admin path detection and grouped standard navigation transformation.

- [ ] **Step 1: Expand Cairo styling to all authenticated admin HTML GET surfaces** while keeping translations finance-only.
- [ ] **Step 2: Add grouped standard sidebar markup** with sections: الرئيسية، القسائم، التجار والمالية، التكاملات، النظام.
- [ ] **Step 3: Put `شركة بكجات الذكية` first**, relabel `/admin` as `ملخص الإدارة`, add `/admin/merchants` and `/admin/settlements`, and point the standard Pakgat brand link to `/admin/company`.
- [ ] **Step 4: Apply the stable weight hierarchy**: headings/section labels 700, active navigation/table headers 600, ordinary UI 400-500.
- [ ] **Step 5: Run targeted tests and then the full regression workflow.**
- [ ] **Step 6: Commit the implementation.**

### Task 3: Review, merge, and prepare guarded production deployment

**Files:**
- No additional runtime files unless verification identifies an issue.

- [ ] **Step 1: Review PR diff for presentation-only scope.**
- [ ] **Step 2: Verify CI/full regression succeeds.**
- [ ] **Step 3: Merge to `gce-migration` only after green verification.**
- [ ] **Step 4: Deploy surgically to the production local branch by copying only the approved presentation file and running baseline-vs-after regression checks before restart.**
- [ ] **Step 5: Verify service, admin routes, old voucher API compatibility, and timer states after restart.**
