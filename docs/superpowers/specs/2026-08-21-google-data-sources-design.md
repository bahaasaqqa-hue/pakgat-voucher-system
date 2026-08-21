# Pakgat AI Company — GA4 + Search Console Integration Design

Date: 2026-08-21
Branch: `gce-migration`

## Goal

Connect Google Analytics 4 and Google Search Console to Pakgat AI Company on the existing Google Compute Engine/PostgreSQL production stack, without depending on Salla approval and without changing Salla OAuth, webhooks, Corporate Benefits, Customer Groups, or Special Offers.

The integration must show only verified Google data. Missing credentials, missing permissions, API failures, or stale data must remain visible as an unavailable/degraded state rather than being replaced by invented metrics.

## Authentication

Use the Google Compute Engine service account available to the production VM through Application Default Credentials (ADC). Do not commit service-account JSON files, private keys, tokens, or secrets to GitHub.

The service account must receive only the external permissions needed to read the Pakgat properties:

- GA4 property: Viewer role.
- Search Console property: read access to the Pakgat site property.

Configuration values that identify resources, such as the GA4 property ID and Search Console site URL, are supplied through `/etc/pakgat/pakgat.env` and are not credentials.

Expected environment variables:

- `GOOGLE_GA4_PROPERTY_ID`
- `GOOGLE_SEARCH_CONSOLE_SITE_URL`
- `GOOGLE_DATA_SYNC_ENABLED` with default `false` until permissions are verified.

## Dependencies

Add Google-supported Python client/auth dependencies to `requirements.txt`:

- `google-auth`
- `google-analytics-data`
- `google-api-python-client`

No browser OAuth flow is required on the server.

## Data model

Add one append-only snapshot table for Google source results. A single table keeps the integration small and auditable while supporting both sources.

`GoogleDataSnapshot`

- `id`
- `source` — `ga4` or `search_console`
- `period_start`
- `period_end`
- `payload_json`
- `status` — `ok`, `error`, or `unconfigured`
- `error_message`
- `created_at`

Snapshots are historical evidence. New syncs insert new rows rather than overwriting previous rows.

## GA4 reader

A dedicated reader in `app/google_data_sources.py` will query the configured GA4 property for a bounded recent period. Initial dashboard metrics:

- active users
- sessions
- screen/page views
- engagement rate
- conversions/key events when returned by the property

The reader returns a normalized Python dictionary and never writes directly to HTML.

## Search Console reader

The same module will query Search Console for the configured Pakgat property. Initial metrics:

- clicks
- impressions
- CTR
- average position
- top queries
- top pages

The initial implementation uses a bounded recent period and limits query/page result counts so dashboard rendering remains predictable.

## Sync flow

`sync_google_sources(db)` performs the following sequence:

1. Validate resource configuration.
2. Obtain ADC from the GCE runtime.
3. Read GA4.
4. Store a GA4 snapshot.
5. Read Search Console.
6. Store a Search Console snapshot.
7. Update Source Inventory status from actual successful snapshots.
8. Record failures without fabricating data.

A failure in one Google source must not prevent the other source from syncing.

## Source Inventory behavior

`Google Analytics` and `Google Search Console` become `Readable` only when there is a recent successful snapshot for that exact source.

States:

- no configuration: `Needs Integration`
- configured but no successful read: `Needs Integration`
- recent successful read: `Readable`
- latest read fails after prior success: keep the source visibly degraded in detail text and do not claim a fresh successful connection

The existing Salla scope-aware readiness logic remains untouched.

## Admin UI

### `/admin/company/visits`

Replace the placeholder with real GA4 data when available. Show:

- active users
- sessions
- views
- engagement rate
- last successful sync time

If no valid snapshot exists, show `بانتظار الربط` or the sanitized connection error.

### `/admin/company/seo`

Replace the placeholder with Search Console metrics when available. Show:

- clicks
- impressions
- CTR
- average position
- top queries
- top pages
- last successful sync time

### Manual refresh

Add a protected POST action under `/admin/company/google/sync` and a visible `تحديث بيانات Google` button on the Google-related admin pages. The action requires the existing admin authentication.

No public endpoint can trigger Google synchronization.

## Scheduling

Phase 1 ships manual sync first. After successful production verification, the existing AI Company monitor may call the same sync function on a controlled schedule. This avoids introducing a second scheduling architecture.

## Error handling and safety

- Never log access tokens or credential objects.
- Store only sanitized error text.
- Apply API timeouts/retry behavior through the Google clients where supported.
- One source failure does not roll back a successful snapshot from the other source.
- Do not display a metric unless its snapshot status is `ok`.
- `GOOGLE_DATA_SYNC_ENABLED=false` prevents live API calls until the service account has been granted access.

## Testing

Use TDD for the implementation.

Unit tests must cover:

- unconfigured sources remain `Needs Integration`
- a successful snapshot makes only its matching source `Readable`
- stale/failed data does not become a fabricated success
- GA4 payload normalization
- Search Console payload normalization
- one-source failure does not block persistence for the other source
- admin pages render waiting state without snapshots and real values with snapshots

Production verification after deployment:

1. Python unit tests pass.
2. Modified modules compile.
3. `pakgat-voucher` restarts and remains `active`.
4. Local HTTP health returns success.
5. With sync disabled, no Google API request occurs.
6. After granting the GCE service account access and enabling sync, manual sync produces successful GA4/Search Console snapshots.
7. `/admin/company/visits`, `/admin/company/seo`, and Source Inventory show the real synchronized state.

## Explicit non-goals

This change does not:

- modify Salla OAuth scopes or tokens
- change Salla webhooks
- enable `CORPORATE_LIVE`
- create or modify Salla Customer Groups
- enable or provision Special Offers
- add Google Ads integration
- add social-media publishing
- change storefront tracking tags

## Rollout

1. Implement code and tests with live synchronization disabled by default.
2. Deploy safely to GCE and verify no regression.
3. Identify the VM service-account email.
4. Grant that account Viewer/read access in GA4 and Search Console.
5. Set the GA4 property ID and Search Console site URL in the GCE environment.
6. Enable `GOOGLE_DATA_SYNC_ENABLED=true`.
7. Run one manual sync and verify snapshots and dashboard values.
8. Only after the manual production test succeeds, consider adding periodic sync to the existing monitor.
