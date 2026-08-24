# Customer Notification Reliability and Feedback Design

## Objective

Make voucher and redemption WhatsApp notifications durable, let a customer confirm receipt or request a human, and collect a 1–5 rating after redemption without adding a separate marketing message.

## Confirmed production facts

- Production runs commit `b3d8e72ea5c467900df3806641e04b5df98218da` as of the Phase A audit.
- The `vouchers` table currently has one active row and no duplicate `(order_id, product_id)` groups.
- There is no production unique constraint on `(order_id, product_id)`.
- Voucher redemption itself is atomic; this project does not change redemption semantics.
- `deploy/gce/pakgat-db-backup.sh` is locally modified on the server and must not be overwritten or reset.

## User experience

The existing voucher-delivery message gains this footer:

> للتأكد أن القسيمة وصلتك، رد برقم واحد فقط:  
> 1 — وصلتني القسيمة  
> 2 — أحتاج مساعدة من خدمة العملاء

The existing redemption-confirmation message gains this footer:

> كيف كانت تجربتك؟ قيّمها من 1 إلى 5، حيث 5 ممتازة.

No separate outbound survey is sent. A valid numeric response is recorded silently to minimize WhatsApp cost. Reply `2` opens a human handoff; it does not let Jood continue an automated conversation.

## Durable delivery model

Create a `customer_notifications` outbox. A row represents one logical notification for one voucher and type (`voucher_issued` or `voucher_redeemed`). The database enforces uniqueness on `(voucher_id, notification_type)`.

Voucher creation and the `voucher_issued` outbox row are committed in the same transaction. Redemption and the `voucher_redeemed` outbox row are likewise committed together. A webhook replay ensures the outbox row exists even when the voucher already exists; it never creates a second logical notification.

The dispatcher claims queued or retryable rows, calls WhatsLoop, and records `sent` or a retryable failure with attempt count, last error, and next-attempt time. The existing direct `BackgroundTasks` send path must not run alongside this path. The delivery guarantee is at-least-once: if the process dies after WhatsLoop accepts a request but before the database marks it sent, a duplicate is possible unless WhatsLoop supports an idempotency key.

The first release includes a command-line dispatcher suitable for a systemd oneshot service and timer. Deployment files are committed, but activation is a separate production step after staging verification.

## Response interpretation

Numeric replies are interpreted only against the sender's most recent unresolved prompt:

1. A pending redemption prompt accepts `1`–`5` as a rating.
2. Otherwise, a pending voucher-issued prompt accepts `1` as receipt confirmation and `2` as a support request.
3. Any other message follows the normal inbound routing rules.

This precedence prevents a rating of `1` or `2` from being mistaken for voucher receipt when a later redemption prompt exists. Phone numbers are normalized using the existing WhatsLoop inbound identity format before lookup.

## Human handoff and Jood pause

Reply `2` records the notification response and creates a `JoodHandoff` linked to the resolved contact. While that contact has an open handoff, inbound messages are persisted but Jood does not generate or send automated replies. Existing Company AI handoff records are the operational queue; this change does not invent an unconfigured Slack, email, or WhatsApp recipient.

Closing a handoff is outside this change because the current model has no explicit closed-state workflow. The initial safe behavior is conservative: once handed off, Jood remains paused until an operator-facing close/resume action is designed and approved. Tests must make this limitation visible.

## Data fields

`CustomerNotification` contains:

- `id`, `voucher_id`, and `notification_type`.
- destination `customer_phone` and rendered `message_body` frozen at creation time.
- delivery `status`, `attempt_count`, `next_attempt_at`, `last_error`, `created_at`, `updated_at`, and `sent_at`.
- response `response_value` and `responded_at`.
- unique constraint `(voucher_id, notification_type)` and indexes needed to find retryable rows and unresolved prompts.

No QR code, verification token, or voucher code is logged in dispatcher errors. Error storage is a sanitized error class/summary, not raw provider responses.

## Rollout and rollback

1. Add tests and schema/model changes using `create_all`-compatible additive DDL.
2. Run the complete test suite locally.
3. Deploy to staging, create a test voucher, simulate one send failure, retry it, and test replies `1`, `2`, and a post-redemption rating.
4. Deploy application code with the direct sender disabled and outbox creation enabled.
5. Install and enable the dispatcher timer only after the application deployment is healthy.

Rollback disables the timer first, then rolls back the application commit. The additive table may remain; dropping it is unnecessary and would destroy delivery/audit history. No migration in this project alters or deletes existing vouchers.

## Acceptance criteria

- A repeated Salla webhook produces one voucher and one logical issuance-notification row.
- A failed WhatsLoop call remains retryable and succeeds on a later dispatcher run.
- No direct and outbox sender can send the same logical notification in parallel.
- Reply `1` records voucher receipt.
- Reply `2` creates one handoff and prevents a Jood auto-reply.
- A rating from `1` through `5` is stored only for the latest pending redemption prompt.
- Invalid or context-free numeric messages remain in normal Jood routing.
- Existing signature verification and atomic voucher redemption tests continue to pass.
