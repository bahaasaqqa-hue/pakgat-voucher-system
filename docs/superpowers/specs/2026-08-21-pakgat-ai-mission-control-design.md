# Pakgat AI — Mission Control Design

Date: 2026-08-21
Target: `https://voucher.pakgat.com/admin/company`
Branch: `gce-migration`

## Goal

Rebuild the Pakgat AI Control Center home page as a clean, executive AI mission-control interface on the existing FastAPI/GCE application. The design must make the system feel active and intelligent while remaining factual: no invented visits, growth percentages, trends, AI confidence, or source status.

## Scope

This change is limited to the protected Pakgat AI Company admin experience under `/admin/company`, with the home page as the primary deliverable. It does not modify the Pakgat storefront, Salla theme/V3, Salla OAuth scopes, Salla webhooks, Corporate Benefits, Customer Groups, or Special Offers.

## Technical approach

Keep the existing server-rendered FastAPI application. Do not introduce React, a Node build pipeline, or Tailwind at runtime. Implement the approved SaaS visual language with the existing HTML response pattern and focused CSS, plus a small pure-Python mission-control context module that derives display data from existing database rows.

The page must remain deployable with the current GCE process and must not require a frontend build step.

## Visual system

- Workspace background: `#F8FAFC` / `#F1F5F9` family.
- Main text/sidebar: `#0F172A` family.
- Primary action blue: `#2563EB` / `#3B82F6` family.
- AI accent: restrained blue-violet glow only for AI/system intelligence cues.
- Success/warning/critical colors remain semantic and limited.
- Cards: white, `18–22px` radius, subtle border and soft shadow.
- Arabic RTL layout, with compact executive information density.
- Motion is subtle: pulse/glow/hover transitions only; no gaming-style neon effects.

## AI Core

The sidebar gains an AI Core identity element with a subtle CSS pulse/glow animation. Its status must be derived from real operational data:

- Operational if the core runtime/health is available.
- Show the factual number of currently usable core sources.
- Show no fabricated background-process claims.

The sidebar footer remains an authenticated admin/operator identity area and includes a Live/Operational indicator.

## AI Command Bar

Add a functional command bar on `/admin/company`. It is not a fake LLM chat box. It is a protected command interface over existing safe admin actions.

Supported intents in the first release:

- run/refresh company cycle → existing `/admin/company/run-company`
- opportunities → `/admin/company/opportunities`
- approvals/decisions → `/admin/company/governance`
- sources/integrations → `/admin/company/sources`
- technology/security → `/admin/company/technology`
- SEO/Google → `/admin/company/seo`
- systems → `/admin/company/systems`
- executive brief → `/admin/company/brief`

Unknown text returns to the dashboard with a visible, non-destructive guidance message. Every accepted command can be logged through the existing audit/event system. No external action is performed by free text.

## KPI strip

The top row shows factual executive KPIs only:

1. Operational Health — existing health score; label must state that it measures runtime/technology/voucher health, not blueprint completion.
2. System Completion — derived from the 12-system status map; show complete/partial/pending counts.
3. New Opportunities — actual count from `CompanyOpportunity`.
4. Orders — actual locally captured Salla order snapshots.

Visits are not shown as a numeric KPI until GA4 is actually connected. Sparklines are rendered only when historical factual snapshots exist; otherwise the card uses a neutral state rather than a fabricated line.

## Situation Room

The central Situation Room answers four executive questions from existing data:

- What changed? — newest real alerts/opportunities/tasks/decisions where timestamps exist.
- What did the system detect? — current highest-priority alerts and opportunities.
- What needs a decision? — pending approvals.
- What requires attention if untouched? — severity/priority-based operational attention items.

Each item displays its source and governance level where available. The UI may use labels such as `AUTO`, `APPROVAL`, and `CEO ONLY`, but must not fabricate confidence percentages.

## Decision Matrix

Pending approvals are presented as a compact decision matrix. The matrix uses factual fields already stored on `CompanyApproval`:

- priority
- approval level
- source
- action type
- age/created time

A deterministic display weight may be derived from those fields for sorting only. The weight is a queue-priority score, not an AI confidence score. Approve/Review controls reuse the existing governance endpoints.

## Opportunity Matrix

Open opportunities are ranked from existing fields:

- stored `score` when present
- priority
- status
- recency

Expose a deterministic `mission_score` in the UI to rank attention. If the stored opportunity score is missing, use priority/status/recency only. The page must clearly label this as an attention/priority score, not predicted revenue or confidence.

## Data trust

Every decision/opportunity/situation item displays source text and, when available, the last update/creation time. Source status comes from the current Source Inventory. No source is presented as live merely because configuration exists.

## Activity rail

Show a small live-activity rail derived from the latest existing internal records: alerts, tasks, opportunities, approvals/decisions, and company health snapshots. This is a recent-activity view of stored evidence, not a simulated event stream.

## CSS and responsiveness

Implement Mission Control styling in the current `ai_company_dashboard_v2.py` shell or a focused companion module. Desktop uses a compact sidebar and multi-column executive layout. Below tablet width, cards collapse to a single column and the sidebar becomes non-sticky. All interactions use 160–220ms transitions.

## Backend/context boundary

Create a focused pure-Python module `app/ai_company_mission_control.py` for deterministic ranking and context helpers. Keep database querying/rendering in the dashboard module following the existing application pattern.

Pure helpers should cover:

- command intent normalization/routing
- system completion summary reuse
- approval queue weight
- opportunity attention score
- human-readable age/freshness labels when needed

## Testing

Use TDD. Tests must cover:

- command text routes only to allowed internal destinations
- unknown command is non-destructive
- approval weighting ranks P0/CEO-level work above low-priority work
- opportunity attention score uses stored score when available and behaves deterministically without it
- no fabricated visit/growth/confidence metrics are introduced by the context helpers
- dashboard source contains the new AI Core, Command Bar, Situation Room, Decision Matrix, and Opportunity Matrix sections

## Deployment verification

After implementation:

1. Mission-control unit tests pass.
2. Existing readiness tests continue to pass.
3. Modified Python modules compile.
4. GCE pulls the exact branch head.
5. `pakgat-voucher` restarts and remains `active`.
6. Local HTTP returns a valid response.
7. Authenticated `/admin/company` visually shows the new Mission Control home page.

## Non-goals

- No storefront changes.
- No Salla theme/V3 changes.
- No React migration.
- No Tailwind runtime dependency.
- No Salla OAuth/Webhook/Corporate/Special Offer change.
- No invented charts, visits, growth rates, confidence percentages, or predictions.
