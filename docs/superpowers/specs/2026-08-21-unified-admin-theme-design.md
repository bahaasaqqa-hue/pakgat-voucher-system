# Pakgat Voucher Admin — Unified Theme Design

Date: 2026-08-21
Branch: `gce-migration`

## Goal

Make every authenticated administrative page under `https://voucher.pakgat.com/admin` use one coherent Pakgat AI visual system, so no navigation inside the admin area falls back to the old blue topbar/theme.

The scope is visual and structural only. Existing business logic, routes, forms, Salla integration behavior, voucher generation, corporate logic, approvals, audit actions, database models, and authentication behavior must remain unchanged unless a rendering compatibility fix is strictly required.

## Scope

The unified theme applies to every HTML page whose path starts with `/admin`, including current and future admin sub-routes registered by the application.

Examples include:

- `/admin`
- `/admin/vouchers/new`
- voucher detail/admin voucher pages
- `/admin/audit`
- `/admin/integrations`
- partner/company data pages
- `/admin/company`
- every `/admin/company/...` page
- corporate benefits admin pages
- source inventory, governance, opportunities, hunter, store operations, SEO, technology, analytics, Salla/admin views, and any other internal admin route

The only pages intentionally not wrapped in the authenticated application shell are:

- `/admin/login` — branded login page, no authenticated sidebar
- `/admin/logout` — action endpoint, no page shell

Redirects, JSON endpoints, downloads, QR/image responses, and POST-only action endpoints are not visually wrapped.

## Chosen Architecture

Use one final application-level module imported last from `main.py`: `app/admin_unified_theme.py`.

It provides a final HTML middleware that runs after the existing route handlers and feature-specific rendering layers. For authenticated HTML requests under `/admin`, it normalizes the page into one global shell without changing route handlers.

This avoids rewriting every existing endpoint and minimizes risk to voucher/Salla/Corporate logic.

The middleware has two rendering modes:

1. **Standard Admin Mode** for `/admin` and non-AI admin pages.
2. **AI Company Mode** for `/admin/company...`, preserving Mission Control-specific content while replacing duplicated/legacy outer chrome with the same shared visual system.

Both modes use the same design tokens, brand header/sidebar, controls, tables, forms, spacing, typography, responsiveness, and navigation language.

## Design System

### Brand

Use the approved Pakgat logo already embedded for Mission Control. The brand appears in a compact form in the global sidebar/header.

Primary visual language:

- background: `#F8FAFC`
- sidebar: `#0F172A` / deep navy gradient
- primary action: `#2563EB`
- AI accent: restrained blue/violet
- success: green
- warning: amber
- destructive/logout: red
- cards: white with subtle border/shadow

No gaming-style excessive glow. AI pulse is limited to the small Pakgat/AI live-state indicator.

### Typography

Arabic-first RTL layout. Use a modern system-safe Arabic font stack without introducing an external font dependency that could fail in production.

### Global components

All admin pages share consistent styling for:

- page title and subtitle
- cards
- KPI cards
- buttons
- destructive buttons
- form inputs/selects/textareas
- labels
- tables
- search/filter bars
- badges/status pills
- alerts
- pagination
- empty states
- detail blocks
- responsive layouts

Existing HTML markup is normalized primarily through CSS selectors so route code does not need to be rewritten page by page.

## Global Navigation

The authenticated shell contains one stable navigation system.

Primary links:

- لوحة الإدارة — `/admin`
- شركة بكجات الذكية — `/admin/company`
- قسيمة جديدة — `/admin/vouchers/new`
- سجل العمليات — `/admin/audit`
- تكامل سلة — `/admin/integrations`
- بيانات الشركاء — existing partner/admin route resolved from current application navigation

AI Company pages retain access to their detailed AI navigation, but it is presented as a contextual secondary navigation within the same outer theme rather than a separate unrelated website.

A logout action remains clearly visible but separated visually from normal navigation.

The active section is highlighted from the current path.

## `/admin` Home Redesign

The current legacy home is rebuilt visually using its real voucher data, preserving all existing search/filter/detail actions.

The page keeps:

- total voucher count
- active count
- redeemed count
- expired count
- search
- status filter
- voucher table
- voucher detail action

The content moves into the same compact executive visual system as Pakgat AI:

- compact KPI row
- clean search/filter card
- modern data table
- consistent badges
- compact responsive pagination

No business behavior changes.

## Existing Admin Pages

Existing pages are not rewritten from scratch unless necessary. The unified shell and CSS transform their current cards, inputs, tables, buttons, headers, and spacing.

Pages with highly custom layouts can expose a small page-specific class/hook, but the default should work automatically for the majority of pages.

This ensures that a newly added admin page using the existing `page_shell(..., admin=True)` convention inherits the same theme automatically.

## AI Company Compatibility

`/admin/company` retains the compact Mission Control dashboard already built:

- KPI row
- Executive Summary
- approvals
- Market Watch
- Product/Pricing Intelligence
- Merchant Hunter
- Voucher & WhatsApp
- SEO/Catalog
- Sourcing
- Technology/Systems
- collapsible Situation Room and matrices

All `/admin/company/...` detail pages inherit the same global outer shell and design tokens.

The final unified middleware must detect and avoid double-wrapping the current `.ai-layout` shell. Mission Control content stays intact while outer navigation becomes visually consistent with the rest of admin.

## Data Integrity Rules

The redesign must never invent data.

- No fake visits.
- No fake growth percentages.
- No fake sparklines.
- No Render production status.
- GA4 remains waiting until connected.
- Operational Health remains distinct from system completion.
- Existing DB values and source inventory drive displayed statuses.

## Authentication and Security

Authentication logic is untouched.

The theme middleware does not bypass or alter `require_admin`, cookies, token validation, redirects, logout, Salla signatures, webhook validation, or Corporate controls.

Unauthenticated requests continue to redirect to `/admin/login` according to existing route behavior.

The login page receives only branded CSS/visual treatment and no authenticated navigation.

## HTML Response Rules

The final middleware only modifies responses when all are true:

- request path starts with `/admin`
- response is HTML
- response is not a redirect
- route is not `/admin/login` unless applying login-specific styling

It does not modify:

- JSON responses
- webhook responses
- image/QR responses
- file downloads
- redirect bodies
- API endpoints outside admin

## Implementation Boundaries

Primary new file:

- `app/admin_unified_theme.py`

Expected modifications:

- `main.py` — import unified theme last
- `app/application.py` — only if a minimal common markup hook is needed; avoid changing route business logic
- existing Mission Control UI — only compatibility hooks if required
- tests for unified shell behavior

Do not modify Salla scopes, OAuth, webhooks, Corporate live flags, customer groups, special offers, voucher redemption behavior, database schema, or Salla API calls as part of this project.

## Testing

TDD tests cover:

1. `/admin` HTML receives unified shell markers.
2. `/admin/vouchers/new`, `/admin/audit`, and `/admin/integrations` receive the same shell.
3. `/admin/company` is not double-wrapped.
4. representative `/admin/company/...` page uses the unified visual system.
5. `/admin/login` has branded login styling but no authenticated sidebar.
6. redirects remain redirects and are not converted to HTML pages.
7. JSON/non-HTML responses remain unchanged.
8. global navigation includes all principal admin sections.
9. active navigation state follows current path.
10. legacy `.topbar` is not visible on wrapped authenticated pages.
11. Mission Control content markers remain present after unified wrapping.
12. existing Mission Control/readiness tests continue to pass.

Production verification after deployment:

- all tests pass
- modified Python modules compile
- service remains `active`
- local HTTP root returns success
- unauthenticated `/admin` still redirects to login
- authenticated manual browser review confirms the same theme on every major admin navigation destination

## Rollout

One deployment only after the complete admin theme is implemented and verified on `gce-migration`.

Deployment sequence:

1. pull final branch once on GCE
2. run all relevant tests
3. compile modified modules
4. restart `pakgat-voucher` once
5. verify HTTP/service
6. browser-check all major admin destinations

The known local modification `deploy/gce/pakgat-db-backup.sh` must remain untouched.
