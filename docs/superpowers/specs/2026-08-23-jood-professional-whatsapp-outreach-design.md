# Jood Professional WhatsApp Outreach — Design

Date: 2026-08-23
Status: Approved in chat
Scope: WhatsApp only. Voice is explicitly excluded.

## Goal

Replace the current required-per-send instruction flow with a professional two-mode WhatsApp workflow:

1. Send to one contact immediately.
2. Upload an Excel/CSV contact list and run the outreach campaign automatically.

The existing WhatsApp number and inbound website customer-service behavior must remain operational and must not be altered by outbound campaign prompts.

## Non-negotiable isolation

Inbound and outbound are separate orchestration paths that share contact history but never share task instructions.

- Inbound website/WhatsApp messages continue through the existing customer-support and sales route.
- Outbound first-touch messages use a stored default prompt selected by contact type.
- Campaign-specific instructions never become the global Jood identity or inbound system prompt.
- A merchant outbound campaign cannot switch an inbound customer conversation into merchant mode.
- Existing WhatsLoop webhook verification, private-chat routing, reply generation, sanitization, history, handoff, and do-not-contact behavior remain intact.

## Stored defaults

Add persistent settings for:

- Customer outreach default prompt.
- Merchant outreach default prompt.

The defaults describe Pakgat, greeting style, offer/partnership presentation, qualification, permitted next steps, truthful WhatsApp follow-up, and prohibited fabricated claims.

Administrators edit these settings once. If a per-contact or per-campaign override is blank, the applicable stored default is used automatically. A non-empty override supplements the default; it does not replace safety policies or Jood identity.

## Individual outreach

The page contains:

- Phone number (required).
- Contact type: customer or merchant (required).
- Name, business, city and notes (optional).
- Special instruction (optional).
- “تواصل الآن” button.

Submission upserts the contact, resolves the applicable default prompt, generates one personalized message, sends it through WhatsLoop, records the dispatch and conversation turn, and displays the result.

## Bulk outreach

The campaign page accepts .xlsx or .csv with phone required and optional name, business, city, notes and contact type columns.

“رفع وبدء الحملة” performs:

1. Parse and validate the file.
2. Normalize Saudi numbers.
3. Upsert contacts.
4. Remove duplicates and exclude do-not-contact contacts.
5. Create a campaign using the applicable stored default plus an optional campaign instruction.
6. Queue all eligible contacts and start background processing.
7. Continue automatically without a per-contact button.

Dispatches are idempotent per campaign/contact. Failed sends retain their error and can be retried safely without resending successful rows.

## Results

Campaign results show total, queued, generating, sent, replied, interested, follow-up, handoff, do-not-contact and failed counts. Each row shows contact, last message, provider status, timestamps and failure reason. Incoming replies continue through the existing inbound route and update contact history/stage without changing the inbound customer-service prompt.

## Operational safeguards

- Do-not-contact enforced before generation and before delivery.
- Campaign/contact uniqueness prevents duplicate sends.
- A bounded send rate prevents bursts.
- Provider and AI failures are recorded without falsely marking delivery.
- No invented prices, offers, links, agreements, delivery status or completed actions.
- Existing website customer support is covered by regression tests.

## Testing

Tests must be written first and observed failing before implementation. Coverage includes:

- Blank individual override resolves to stored default.
- Blank campaign override resolves to stored default.
- Explicit instruction supplements the default.
- Customer and merchant defaults remain isolated.
- Inbound website/customer replies never receive outbound campaign instructions.
- CSV/XLSX parsing, normalization, deduplication and do-not-contact filtering.
- Automatic queue progression and idempotency.
- Failed rows are retryable and sent rows are not duplicated.
- Existing WhatsLoop inbound and Jood AI regression suites remain green.

## Delivery

Implement on the approved GitHub branch, run targeted tests and the complete suite, and deploy only after verification. Preserve the known unrelated change in deploy/gce/pakgat-db-backup.sh.
