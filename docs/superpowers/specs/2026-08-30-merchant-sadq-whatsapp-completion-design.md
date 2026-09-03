# Merchant Sadq Completion & WhatsApp Design

## Goal
When a merchant contract is completed in Sadq, Pakgat records the signed state on the existing merchant profile, preserves the Sadq document/request identifiers, sends the signed contract to the merchant's registered WhatsApp contact, records the communication outcome, and leaves merchant activation as a separate Pakgat decision.

## Scope
This design starts at the moment Sadq reports that an already-created signature request has completed. It does not create the contract text, upload a new contract to Sadq, or invent Sadq authentication/request-creation endpoints. Those steps remain separate until the exact account-specific Sadq request-creation contract/Postman collection is available.

The implementation must not change voucher issuance, voucher redemption, Salla webhook behavior, existing customer notifications, settlement calculations, or existing WhatsLoop inbound behavior.

## Existing System Reuse
Pakgat already has:

- `Merchant` as the stable merchant entity.
- `MerchantContract` with `merchant_id`, `status`, `sadq_document_id`, `sadq_transaction_id`, `signed_document_url`, and `signed_at`.
- `/admin/merchants/{merchant_id}` as the merchant detail page.
- `/admin/merchants/{merchant_id}/edit` with merchant legal/contact/bank data and a contract/Sadq section.
- Merchant notes/activity storage.
- Existing WhatsLoop/Jood outbound infrastructure.

This feature extends those components additively rather than creating a second merchant or contract system.

## Contract Status Model
`MerchantContract.status` uses these values for this flow:

- `draft` — contract exists locally but is not yet in a signing flow.
- `sent` — Sadq request identifiers have been stored and signing is pending.
- `signed` — Sadq reports successful completion.
- `rejected` — Sadq reports rejection.
- `cancelled` — Sadq reports cancellation/voiding.
- `expired` — Sadq reports expiration.

A `signed` contract is immutable from the completion workflow. Repeated completed webhooks must not create duplicate notes or duplicate merchant WhatsApp deliveries.

Merchant operational status remains independent. A merchant may have `MerchantContract.status == "signed"` while `Merchant.status == "pending"`. Pakgat activation is performed separately by an admin.

## Agreement Number
Add an immutable `agreement_number` to `MerchantContract`.

Format:

`PKG-MA-YYYY-MM-NNNN`

Example:

`PKG-MA-2026-08-0047`

The sequence is generated per year/month and must be unique. Once assigned, it is never reused or rewritten. Existing contract rows without an agreement number may receive one only through an explicit backfill/admin action; the completion webhook does not silently invent one for historical records.

## Sadq Completion Endpoint
Add Pakgat endpoint:

`POST /integrations/sadq/webhook`

The endpoint is public only to Sadq and must validate a configured shared header token before reading the payload. The configured value is `SADQ_WEBHOOK_TOKEN`; production must fail closed when the token is missing.

The endpoint accepts JSON and extracts identifiers from the Sadq completion payload using the documented concepts `requestId`/request identifier and `documentId`/file identifier. It locates an existing `MerchantContract` by `sadq_transaction_id` first and then `sadq_document_id`.

Supported terminal state normalization:

- Sadq completed/success -> `signed`
- Sadq rejected -> `rejected`
- Sadq cancelled/voided -> `cancelled`
- Sadq expired -> `expired`

Unknown or non-terminal states are acknowledged without changing the contract.

The handler must be idempotent. If the same completion payload is received again for a contract already marked `signed`, it returns success without sending WhatsApp again.

## Signed Document Retrieval
Sadq documents are retrieved from the documented sandbox/production document endpoint:

`GET /api/v1/documents/{id}/signed`

The Sadq base URL is configured through `SADQ_API_BASE_URL`; sandbox value is `https://sandbox-api.sadq-sa.com`.

Retrieval uses `Authorization: Bearer <token>` from `SADQ_BEARER_TOKEN`. The feature does not derive a bearer token from Account Secret/username/password because the exact account authentication endpoint is not part of the public reference currently available to this implementation.

If `SADQ_BEARER_TOKEN` is configured, Pakgat may download the signed PDF after completion and hand the bytes to the outbound document sender. If it is not configured or retrieval fails, the contract remains `signed`; WhatsApp delivery is recorded as failed/pending and an admin retry action is available. A document retrieval failure must never roll back Sadq's signed state.

No Sadq credentials, bearer token, or Account Secret are exposed to merchant-facing HTML or JavaScript.

## WhatsApp Delivery
After the first successful transition to `signed`, Pakgat sends a WhatsApp message to `Merchant.contact_phone` using the existing Pakgat/WhatsLoop outbound integration.

Arabic copy:

> تم توقيع اتفاقية الشراكة مع Pakgat بنجاح ✅\nرقم الاتفاقية: {agreement_number}\nأرفقنا لك نسخة الاتفاقية الموقعة للاحتفاظ بها.\nسيكون التواصل التشغيلي معك عبر رقم الواتساب المسجل لدينا.

The message and the signed PDF belong to one delivery attempt. If the existing WhatsLoop API requires separate text and media requests, both requests share one local delivery record and the delivery is successful only when the required requests succeed.

The destination phone is always the normalized value derived from `Merchant.contact_phone`. The webhook payload must never override the merchant's Pakgat contact phone.

## Delivery Audit
Add `MerchantContractDelivery` table with:

- `id`
- `merchant_contract_id`
- `merchant_id`
- `channel` (`whatsapp`)
- `destination`
- `status` (`pending`, `sent`, `failed`)
- `provider_message_id` nullable
- `attempt_count`
- `last_error` nullable
- `sent_at` nullable
- `created_at`
- `updated_at`

Unique constraint: one logical delivery per `(merchant_contract_id, channel)`.

Retries update the same delivery row and increment `attempt_count`; they do not create duplicate logical deliveries.

## Merchant Activity
On first successful Sadq completion add one merchant note/activity entry:

`تم اكتمال توقيع اتفاقية الشراكة {agreement_number} عبر صادق.`

On successful WhatsApp delivery add:

`تم إرسال نسخة الاتفاقية الموقعة إلى واتساب التاجر.`

On failed delivery add an operational note only after the delivery attempt finishes, containing a safe error summary without credentials or full provider payloads.

## Merchant Admin UI
Extend `/admin/merchants/{merchant_id}` and the existing edit/profile contract section to show:

- Agreement number.
- Contract status.
- Sadq document ID.
- Sadq request/transaction ID.
- Signed date.
- WhatsApp delivery status.
- WhatsApp delivery attempts.
- Last safe delivery error when failed.
- `إعادة إرسال العقد على واتساب` button when the contract is signed and delivery is not successful.

The retry button is admin-authenticated and idempotent. It never changes merchant activation status or contract signed status.

## Merchant Activation
Sadq completion does not activate a merchant.

After signing, the normal merchant status may remain `pending`. Pakgat admins continue to choose `active`, `suspended`, or `pending` through existing merchant administration. This separation implements the business rule that the merchant signs first and Pakgat decides afterward whether to activate the service.

## Security
- Validate `SADQ_WEBHOOK_TOKEN` before processing webhook JSON.
- Do not log Sadq secrets or authorization headers.
- Do not expose the signed document through an unauthenticated public URL.
- Admin signed-document access remains behind existing admin authentication.
- Normalize WhatsApp destination from the merchant profile, not from inbound webhook data.
- Reject webhook payloads that cannot be matched to an existing contract; do not auto-create merchants or contracts from an external callback.

## Error Handling
- Duplicate webhook: acknowledge with no duplicate side effects.
- Unknown contract: return 404 and log a safe event.
- Invalid webhook token: return 401/403 with no payload processing.
- Unknown/non-terminal Sadq status: return 200 and no state change.
- Signed PDF download failure: keep contract signed; create/update failed delivery state.
- WhatsApp failure: keep contract signed; expose retry action.
- Merchant without contact phone: keep contract signed; delivery becomes failed with `merchant_contact_phone_missing`.

## Testing
Regression and feature tests must prove:

1. Valid completed webhook moves a matching contract to `signed`.
2. Merchant status is not changed by Sadq completion.
3. Duplicate completed webhook does not send WhatsApp twice.
4. Invalid webhook token produces no state change.
5. Unknown contract is not auto-created.
6. Signed-document retrieval uses `/api/v1/documents/{id}/signed` and server-side bearer auth only.
7. PDF retrieval failure leaves contract signed and records failed delivery.
8. Successful delivery records destination, attempts, sent timestamp, and merchant activity.
9. Missing merchant phone records a delivery failure without changing contract status.
10. Admin retry is auth-protected and reuses the same logical delivery row.
11. Existing voucher/customer WhatsApp regression tests remain unchanged and passing.
12. Existing merchant finance/settlement tests remain unchanged and passing.

## Deployment Configuration
Add documented environment variables only; never commit secrets:

- `SADQ_API_BASE_URL=https://sandbox-api.sadq-sa.com` for sandbox.
- `SADQ_BEARER_TOKEN` for authenticated document retrieval when available.
- `SADQ_WEBHOOK_TOKEN` shared only between Pakgat and Sadq webhook configuration.

The Account ID, Account Secret, username, password, and static sandbox OTP supplied out-of-band are not stored in source control.

## Out of Scope
- Creating or editing the legal contract text.
- Creating Sadq signature requests.
- Obtaining Sadq bearer tokens from account credentials without the exact authentication API contract.
- Offer annex creation/approval.
- Changing merchant commission or finance calculations.
- Automatic merchant activation after signature.
