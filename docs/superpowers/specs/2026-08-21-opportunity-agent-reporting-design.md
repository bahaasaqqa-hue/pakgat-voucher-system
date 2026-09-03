# Pakgat Opportunity Assignment & Agent Reporting Design

Date: 2026-08-21
Branch: `gce-migration`

## Goal

Improve `/admin/company/opportunities` so opportunities are operationally clear from discovery through assignment, agent follow-up, completion, and automatic archive, while keeping Pakgat AI typography and visual density consistent.

## Scope

This project covers only the Pakgat AI opportunity workflow and AI-page presentation consistency.

It includes:

- newest-first opportunity ordering
- explicit assigned state visibility with assigned agent identity
- secure external agent-report link sent in the existing WhatsLoop assignment message
- mobile-friendly agent report form without login/OTP
- optional evidence image upload
- append-only report history
- completion states retained for 48 hours before automatic archive
- improved opportunities page information architecture
- standardized typography across Pakgat AI pages

It does not change Salla OAuth/scopes/webhooks, Corporate Benefits, voucher issuance/redemption, WhatsLoop provider configuration, or unrelated database logic.

## Existing Flow Kept

The existing explicit approval model remains unchanged:

1. Admin opens an opportunity.
2. Admin chooses an active agent.
3. Admin reviews/edits the WhatsApp message.
4. Admin explicitly confirms send.
5. Only after WhatsLoop returns success does the opportunity become `assigned`.

A failed WhatsApp send does not mark the opportunity assigned.

## Opportunity Ordering

### New

`status = new` rows are ordered strictly by:

1. `created_at DESC`
2. `id DESC` as deterministic tie-breaker

Score must not move an older opportunity above a newer opportunity in the New section.

### In progress

Statuses `review`, `approved`, `active`, `assigned`, `contacted`, `replied`, and `negotiating` are ordered by:

1. `updated_at DESC`
2. `id DESC`

### Recently completed

Statuses `won` and `lost` with `updated_at >= now - 48 hours` appear in a dedicated `مكتملة مؤخرًا` section, newest completion first.

### Archive

Rows with status `archived` are ordered by `updated_at DESC`, then `id DESC`.

`won` or `lost` rows older than 48 hours are automatically changed to `archived` when the opportunities workflow is refreshed/read. This is idempotent.

## Assigned Visibility

An assigned opportunity remains visible under `تحت التنفيذ`; it never moves directly to archive.

For assigned/in-progress rows the UI shows:

- status badge
- assigned agent name if a successful dispatch exists
- assignment timestamp
- latest agent-report action and timestamp when available

The row must make `مسندة إلى: <agent name>` visually unmistakable.

## Secure Agent Report Link

Each successful opportunity assignment receives a report-link capability associated with that dispatch.

### Security model

Use an unguessable random token generated with Python `secrets`.

The external URL shape is:

`https://voucher.pakgat.com/agent/report/<token>`

The raw token is shown only in the WhatsApp URL. The database stores only a SHA-256 hash of the token.

A token is valid only when:

- it matches an active dispatch report link
- it has not been revoked
- it has not expired
- the opportunity is not archived

Default expiry is 30 days from issuance. Archiving the opportunity also makes the link unusable.

The page reveals only the information needed for the assigned opportunity; it provides no admin navigation and no access to other opportunities.

## Database Additions

### `opportunity_report_links`

One active report capability per successful dispatch.

Fields:

- `id`
- `dispatch_id` indexed
- `opportunity_id` indexed
- `agent_id` indexed
- `token_hash` unique/indexed
- `expires_at`
- `revoked_at` nullable
- `created_at`

### `opportunity_agent_reports`

Append-only agent reporting history.

Fields:

- `id`
- `opportunity_id` indexed
- `dispatch_id` indexed
- `agent_id` indexed
- `action` indexed
- `notes` nullable, max 2000 chars
- `follow_up_at` nullable
- `evidence_filename` nullable
- `evidence_content_type` nullable
- `created_at`

No existing table columns are altered.

SQLAlchemy `Base.metadata.create_all()` creates the two tables during application startup, following the repository's current pattern.

## Agent Report Actions

Allowed actions are explicit and server-validated:

- `contacted` — تم التواصل
- `visited` — تمت الزيارة
- `interested` — مهتم
- `replied` — تم الرد
- `negotiating` — قيد التفاوض
- `follow_up` — متابعة لاحقًا
- `won` — ناجحة
- `lost` — غير ناجحة

Action-to-opportunity status mapping:

- `contacted` -> `contacted`
- `visited` -> `contacted`
- `interested` -> `replied`
- `replied` -> `replied`
- `negotiating` -> `negotiating`
- `follow_up` -> keep current in-progress status; if currently `assigned`, keep `assigned`
- `won` -> `won`
- `lost` -> `lost`

Every accepted report updates `CompanyOpportunity.updated_at`.

Reports do not overwrite previous reports.

## Agent Report Page

The report page is mobile-first and Arabic RTL.

It shows:

- Pakgat branding
- opportunity ID
- opportunity title
- assigned agent name
- action selector
- notes textarea
- optional follow-up date/time
- optional evidence image
- submit button

After submission, show a clear success screen and retain the same secure link for additional updates while valid.

## Evidence Image Upload

Evidence is optional.

Accepted formats:

- JPEG
- PNG
- WebP

Maximum upload size: 5 MB.

Validation is server-side and uses both MIME type and Pillow image verification. Files are re-encoded to WebP before storage so arbitrary uploaded bytes are never served directly.

Storage root defaults to:

`/var/lib/pakgat/opportunity-evidence`

and can be overridden by environment variable:

`OPPORTUNITY_EVIDENCE_DIR`

File names are random UUID/secure names and never derived from the user's original filename.

Images are not public static files. Admin evidence is served through an authenticated `/admin/...` route that checks admin access before reading the stored file.

## WhatsLoop Message

The existing editable assignment message remains editable.

Before sending, the server appends a dedicated reporting block containing the secure report link, for example conceptually:

`تحديث نتيجة الفرصة: <secure link>`

The admin does not need to manually paste the token.

The exact message stored in `OpportunityDispatch.message` is the actual message sent, including the report URL, so the audit record reflects what the agent received.

A report link is created before the outbound send, but if the send fails it is revoked and the opportunity is not marked assigned.

## Admin Opportunity Page Redesign

The page uses four operational sections:

1. `فرص جديدة`
2. `تحت التنفيذ`
3. `مكتملة مؤخرًا · 48 ساعة`
4. `الأرشيف`

The archive remains collapsed by default.

Top KPI cards are compact and standardized:

- جديدة
- تحت التنفيذ
- مكتملة مؤخرًا
- الأرشيف

Opportunity rows/cards show:

- opportunity number
- status
- source
- title
- created/updated time
- score as secondary metadata, not primary ordering
- assigned agent when present
- latest agent action when present
- compact actions
- expandable details/report history

## Typography Standardization

The unified admin theme applies fixed Pakgat AI typography regardless of legacy inline styles.

Target desktop sizes:

- page H1: 22px
- section H2: 17px
- card H3: 14px
- body: 13px
- table cells: 12px
- muted/supporting text: 11px
- buttons/inputs: 12px
- KPI value: 28px

Mobile sizes reduce only where necessary, not page-by-page.

The override is scoped to `body[data-unified-admin-theme='ai']` so it does not alter public voucher/customer pages.

## Automatic Archive

Function `archive_completed_opportunities(db, now=None)` updates `won`/`lost` opportunities older than 48 hours to `archived`.

It runs before rendering `/admin/company/opportunities` and may also be reused by company refresh cycles later.

It must be safe to call repeatedly.

Each automatic transition writes one audit event `opportunity_auto_archived` for the affected opportunity.

## Audit Events

New events:

- `opportunity_report_link_created`
- `opportunity_agent_report_submitted`
- `opportunity_evidence_uploaded`
- `opportunity_auto_archived`

Existing dispatch/stage audit events remain unchanged.

No secret token or raw private URL token is written into audit logs.

## Error Handling

- invalid/expired/revoked token: friendly 404/expired report page without revealing whether another opportunity exists
- invalid action: HTTP 400
- oversized/invalid image: return report form with a clear validation error; do not create partial report
- storage write failure: do not create a report claiming an image was stored; return safe error
- WhatsLoop failure: revoke the newly-created report capability and retain current opportunity status

## Testing

Tests cover:

1. new opportunities sort by `created_at DESC`, independent of score
2. in-progress rows sort by `updated_at DESC`
3. assigned opportunity stays in progress and renders assigned-agent identity
4. secure tokens are hashed in storage and raw token is not persisted
5. WhatsLoop message receives a report URL automatically
6. failed send revokes report capability and does not mark assignment
7. valid report token resolves the correct dispatch/opportunity/agent
8. invalid/expired/revoked token is rejected
9. each report appends history
10. action mapping updates opportunity status correctly
11. `won`/`lost` stay in recently completed for 48 hours
12. older completed rows auto-archive idempotently
13. JPEG/PNG/WebP evidence under 5 MB is accepted, verified, re-encoded, and stored with random name
14. invalid/non-image/oversized files are rejected
15. evidence download route requires admin authentication
16. typography hooks enforce standard AI sizes
17. existing Mission Control, readiness, dispatch, and unified-theme tests remain green

## Deployment

One deployment to GCE after tests and compile succeed.

Production verification must include:

- service `active`
- HTTP root 200
- admin auth redirect still works
- assignment page renders
- one controlled test assignment produces a report URL
- report page opens from that URL
- test report submission appears in admin history
- evidence route remains admin-protected

The existing local modification `deploy/gce/pakgat-db-backup.sh` must remain untouched.