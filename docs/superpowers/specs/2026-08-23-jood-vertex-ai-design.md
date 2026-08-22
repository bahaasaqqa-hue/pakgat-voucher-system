# Jood Vertex AI Design

## Goal
Turn Jood from a fixed WhatsLoop greeting into a production conversational agent for Pakgat customer service, sales, and merchant conversations, while preserving the verified WhatsLoop signature boundary.

## Architecture
Inbound WhatsLoop events continue through the existing signed webhook. After normalization, eligible inbound text is routed to a new `app/jood_ai.py` module. The module gets an OAuth access token from the GCE metadata service and calls Vertex AI Gemini through the REST API using only Python standard library networking. The generated reply is sent back through the existing WhatsLoop `send-reply` path.

## Reply scope
- Direct one-to-one inbound text: Jood may reply automatically.
- Group inbound text: Jood replies only when the message explicitly contains `جود` or `Jood`.
- Messages sent by Pakgat itself never trigger Jood.
- Empty/non-text events do not trigger AI.

## Identity and guardrails
Use the existing `JOOD_SYSTEM_PROMPT` as the authoritative identity and policy. Add runtime instructions not to invent prices, order states, refund approvals, merchant terms, or customer data. If exact live data is unavailable, Jood should ask for the minimum identifying detail or say the case needs internal follow-up rather than fabricate an answer.

## Failure behavior
- If Vertex authentication, network, provider response, or parsing fails, no AI text is sent to the customer.
- Failure is logged with a safe category/message only; OAuth tokens and provider secrets are never logged.
- Existing WhatsLoop webhook verification remains fail-closed and unchanged.

## Google Cloud
Use project `pakgat-production`, Vertex location `us-central1`, and an environment-overridable Gemini model. Default model: `gemini-2.5-flash`. The VM service account must have Vertex AI User permission and the Vertex AI API enabled. No new API key is stored.

## Testing and deployment
Pure routing, payload construction, response parsing, and provider error behavior are covered with standard-library `unittest` and fake HTTP responses. The GCE deployment safety gate runs the focused Jood AI unit test before restarting the live service. Production acceptance is one WhatsApp message addressed to Jood after deployment.