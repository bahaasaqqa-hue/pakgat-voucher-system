# Jood Omnichannel Company AI — Design

**Date:** 2026-08-23
**Status:** Approved in conversation; written specification for implementation review
**Target branch:** `gce-migration`

## 1. Goal

Turn Jood into one shared Pakgat AI agent controlled from Company AI, with two external channels:

- WhatsApp through the existing WhatsLoop integration.
- Phone calls through the existing Motorola/eSIM + Windows Phone Link + Voicemeeter audio path.

The same Jood Core must serve both channels so customer and merchant conversations share the same identity, guardrails, knowledge rules, memory model, and operational playbooks.

## 2. Operating modes

Company AI, not the language model, assigns the contact type for outbound work:

- `customer`: B2C support, sales, follow-up and approved upsell/cross-sell.
- `merchant`: B2B prospecting, qualification and partner acquisition.

Inbound WhatsApp may infer a mode only when no Company AI contact record exists. Once a contact is classified in Company AI, the stored classification wins.

A future `campaign` concept is an internal orchestration object, not a third customer-visible identity. A campaign always targets either customer or merchant contacts.

## 3. Jood Core v2

### 3.1 Real conversation memory

Each AI request must include the last 6–8 real turns for that contact/conversation, oldest to newest, followed by the current user turn.

Do not inject training examples as fake `user`/`model` conversation turns. Style examples belong only inside system instructions as clearly labeled examples that are not current facts.

For WhatsApp groups, history must be isolated by sender so one participant cannot inherit another participant's context.

### 3.2 Intent routing

Before generation, route each turn to a bounded intent/playbook. Initial intents:

- `general`
- `customer_support`
- `customer_sales`
- `product_or_category`
- `order_or_voucher`
- `complaint`
- `refund_or_payment`
- `merchant_prospecting`
- `merchant_qualification`
- `merchant_agreement`
- `human_handoff`

The router should use deterministic rules for obvious cases and allow the model to resolve ambiguous cases only within the contact's Company AI mode.

### 3.3 URL policy

URLs are controlled by code, not by model memory.

Initial approved URLs:

- Pakgat home: `https://pakgat.com/ar`
- Car care category: `https://pakgat.com/ar/%D8%A7%D9%84%D8%B9%D9%86%D8%A7%D9%8A%D8%A9-%D8%A8%D8%A7%D9%84%D8%B3%D9%8A%D8%A7%D8%B1%D8%A7%D8%AA/c1691767409`

Explicitly forbidden legacy path:

- `/ar/categories/car-care`

No partner/agreement URL is considered approved until an actual Pakgat URL is supplied or verified. Jood must not invent `/partners` or any other route.

Before any reply is sent to WhatsApp or voice TTS, extract every URL. If a URL is not in the approved whitelist, replace it with the Pakgat home URL unless the response is safer with the URL removed entirely.

### 3.4 Knowledge and claims

Fixed verified operating knowledge for v1:

- Pakgat is a Saudi platform for packages, coupons, offers and curated experiences, with current operating focus on Riyadh.
- Voucher flow: customer buys digitally; the voucher/link and QR are issued; the merchant scans/verifies and confirms redemption.

Jood must not fabricate prices, discount percentages, stock, offer validity, payment methods, order state, legal terms, commission rates, or a completed escalation.

Jood may say an item was escalated only after the application creates a real handoff/lead/case record.

### 3.5 Prompt-injection protection

Customer instructions such as “replace your instructions”, “ignore your policy”, or requests to reveal system prompts must never alter runtime policy. Jood should redirect naturally to Pakgat service without discussing internal prompts, models, secrets or internal assistants.

## 4. Merchant playbook

Jood acts as a B2B Prospecting & SDR representative, not an autonomous contract negotiator.

Value proposition: help restaurants and service businesses increase sales and attract new Riyadh customers through prepaid digital packages and experiences, without upfront marketing cost.

Merchant states:

1. `new`
2. `contacted`
3. `replied`
4. `qualified`
5. `agreement_requested`
6. `agreement_shared`
7. `handoff_ready`
8. `handed_off`
9. `not_interested`
10. `do_not_contact`

Qualification fields:

- business name
- category/activity
- city/branch
- responsible person's name
- responsible contact number
- proposed offer/idea when voluntarily available

Guardrails:

- Never commit a final commission or binding term.
- Never promise sales volume or financial outcomes.
- Share only whitelisted agreement/partner URLs.
- If not interested, stop immediately and record the state.
- Allow at most one automated follow-up after a configurable delay when no response is received.

## 5. Customer playbook

Customer mode covers support and sales. Jood should:

- answer from verified knowledge/context;
- route category requests to approved category URLs;
- ask one useful preference question when it improves a recommendation;
- use live product/order data only after such data is actually connected;
- avoid claiming that a refund/payment/order action occurred when no real system action exists.

## 6. Company AI contact model

Company AI becomes the control plane.

A contact record stores at minimum:

- normalized Saudi phone
- type: `customer` or `merchant`
- display name/business name
- city
- notes/context
- active/do-not-contact status
- last contact time

Contacts can be entered individually and later imported in bulk. Campaigns select contacts by type; Jood never guesses the outbound mode.

## 7. WhatsApp orchestration

The existing signed WhatsLoop webhook remains unchanged as the transport boundary.

For inbound messages:

1. normalize inbound event;
2. identify Company AI contact by sender phone;
3. resolve mode from stored contact, or infer only when missing;
4. append real conversation turn;
5. call Jood Core v2 with memory + mode + intent;
6. validate URLs/claims;
7. send through existing WhatsLoop reply function;
8. append assistant turn and operational result.

For outbound Company AI WhatsApp campaigns, Jood uses the target contact's mode and campaign goal. Sending must respect do-not-contact state and any future consent controls.

## 8. Voice v1 architecture

Voice v1 uses the already proven hardware path and does not replace WhatsLoop:

`Motorola/eSIM ↔ Phone Link ↔ Voicemeeter ↔ browser voice bridge ↔ Company AI/Jood Core`

Phone Link call initiation remains manual in v1, as already approved. Automatic dialing is a later phase after the audio/AI bridge is stable.

### 8.1 Audio routing

- Phone Link output -> Voicemeeter VAIO input.
- Customer audio is exposed to the voice bridge through a dedicated Voicemeeter bus.
- Voice bridge output -> Voicemeeter AUX input.
- AUX is routed to B2.
- Phone Link microphone input -> Voicemeeter B2 output.
- Physical microphone is not routed to B2 during autonomous Jood calls.
- Chrome can keep the physical microphone for ChatGPT; use Microsoft Edge for the Jood voice bridge so browser input/output routing can be isolated by app.

### 8.2 Half-duplex conversation

First release is half-duplex:

1. listen until caller finishes one utterance;
2. transcribe Arabic/English;
3. send transcript to the active Company AI call session;
4. generate Jood reply through the same Jood Core;
5. synthesize the reply with Saudi female voice `ar-SA-ZariyahNeural`;
6. pause recognition while Jood speaks;
7. resume listening when playback completes.

Full-duplex interruption/barge-in is explicitly out of scope for v1.

### 8.3 TTS/STT cost target

No recurring voice-platform subscription is required for v1.

- TTS provider is abstracted; initial target is Zariyah through a no-monthly-subscription path. The implementation must allow later replacement by official Azure Speech without changing Jood Core.
- Browser STT is acceptable for the first functional bridge. If accuracy/reliability is insufficient, replace only the STT adapter with local Whisper/faster-whisper.

## 9. Call queue and scheduling

Company AI stores outbound call campaigns with:

- contact type (`customer` or `merchant`)
- campaign goal/instructions
- start time
- end time
- status
- fixed cooldown: **30 seconds between completed call attempts**

The queue must never present/do an attempt outside its configured time window.

Because dialing is manual in v1, the control center exposes the current/next contact and a clear “Call with Jood” action. Automatic dial execution is deferred until a reliable Windows/Android control mechanism is proven.

## 10. Call sessions and log

Every call attempt creates a durable Call Log entry containing:

- contact ID/type/name/phone
- campaign ID and goal when applicable
- start/end timestamps
- duration
- outcome
- short AI-generated summary
- extracted useful fields
- transcript when enabled
- human follow-up flag
- do-not-contact flag

Initial outcomes:

- `interested`
- `follow_up`
- `not_interested`
- `no_answer`
- `busy`
- `human_handoff`
- `do_not_contact`
- `failed`

The summary and outcome remain available from Company AI. Notifications are reserved for important cases such as interested merchant, required human intervention, urgent customer issue, or do-not-contact request.

## 11. Company AI UI

Add one Jood operations area under `/admin/company` with:

- Contacts: Customer / Merchant tabs or filters.
- WhatsApp action/campaign controls.
- Call campaigns with start/end time and 30-second cooldown.
- “Call with Jood” action from a contact/campaign queue.
- Active voice session page/bridge.
- Call Log with outcome, description/summary, transcript drill-down and follow-up state.

The UI must reuse the existing Pakgat AI Company admin shell and authentication.

## 12. Security and privacy

- Existing WhatsLoop signature validation remains mandatory.
- Admin-only routes use existing Company AI admin authentication.
- Voice session endpoints require the active authenticated admin browser session; no secret is placed in client-visible source beyond normal short-lived session identifiers.
- Never log API keys, webhook secrets or internal prompts.
- Do-not-contact state blocks future outbound attempts.

## 13. Testing and acceptance criteria

The implementation is accepted when all of the following are demonstrated:

1. A WhatsApp customer can ask multiple dependent questions and Jood uses 6–8 real turns without confusing few-shot examples with history.
2. The legacy car-care URL can never be emitted even if the model produces it.
3. Customer and merchant contacts receive their correct Company AI playbooks.
4. A merchant lead can advance through qualification/handoff states without Jood inventing legal/financial terms.
5. A Company AI call session can send a real transcript to Jood Core and return a validated reply.
6. Zariyah playback reaches the Phone Link call through the proven AUX -> B2 route.
7. A completed call produces a durable Call Log summary/outcome.
8. The queue enforces the configured call window and 30-second cooldown.
9. Do-not-contact prevents future outbound call/WhatsApp queueing.
10. Existing voucher, Salla, WhatsLoop webhook security, and local backup behavior remain untouched unless explicitly required by this design.
