# Implementation Plan Correction

For Task 1 of `2026-08-30-merchant-sadq-whatsapp-completion.md`, `next_agreement_number(db, when=None)` is implemented in `app.merchant_finance`, not `app.merchant_contracts`. This keeps the storage/identity task independent before the Sadq webhook module is created. All later tasks consume `finance.next_agreement_number` if needed.
