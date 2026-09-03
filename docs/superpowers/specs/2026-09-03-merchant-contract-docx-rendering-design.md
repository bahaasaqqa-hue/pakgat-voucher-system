# Merchant Contract DOCX Rendering Design

## Goal
Replace the fragile HTML-to-PDF rendering path for the merchant partnership contract with a deterministic three-page DOCX template that is filled with merchant/agreement data and converted to PDF by the existing LibreOffice Headless runtime.

The visual source of truth is the approved three-page Pakgat reference image. The final PDF must closely match that layout, including the same Pakgat logo used in the reference.

## Scope
Only the merchant contract rendering layer changes.

Do not change:
- merchant registration flow
- OTP verification flow
- rule that successful OTP does not activate the merchant automatically
- final Pakgat approval / Active logic
- legal clauses 1–13
- Pakgat signer data
- Jood / WhatsApp integrations
- unrelated services or endpoints

## Architecture

### Current
`ContractData -> HTML -> LibreOffice Headless -> PDF`

### Target
`ContractData -> DOCX template fill -> LibreOffice Headless -> PDF`

The public rendering entry point should remain compatible with current callers so the rest of the application does not need to change.

## Template
Add one version-controlled DOCX template under `app/assets/`.

The template is a fixed A4, three-page RTL Arabic document:

### Page 1
- header: title on right, exact approved Pakgat blue logo centered, blank balancing area on left
- thin navy horizontal rule
- centered contract subtitle
- compact agreement number/date bar
- section title: `أولاً: أطراف الاتفاقية`
- two equal-width side-by-side party cards
  - Pakgat on right
  - merchant on left
  - navy headers, white text
  - light label cells and white value cells
  - fixed table widths and row heights
  - Pakgat card padded with visually neutral blank rows if needed to match merchant card height
- section title: `ثانياً: التمهيد`
- compact preamble text
- signing/OTP approval box
- footer: `بكجات | Pakgat.com` / agreement number / `صفحة 1 من 3`

### Page 2
- compact repeated header
- `ثالثاً: الشروط والأحكام (1)`
- clauses 1–7 only
- no clause split across pages
- footer: page 2 of 3

### Page 3
- compact repeated header
- `ثالثاً: الشروط والأحكام (2)`
- clauses 8–13
- section title: `رابعاً: الموافقة الإلكترونية والاعتماد النهائي`
- two equal-width approval cards
  - Pakgat on right
  - merchant on left
- activation/OTP note box
- footer: page 3 of 3

## Data Fields
Template placeholders must cover the existing `ContractData` fields and existing Pakgat signer constants:
- agreement number
- agreement date
- merchant legal name
- activity
- commercial registration
- tax number
- bank name
- IBAN
- national address
- contact phone
- contact email
- website
- representative name
- representative title
- Pakgat signer name/title

LTR-sensitive values (agreement number, dates, phone, IBAN, email, URL, registration/tax numbers) must render correctly within the RTL document.

## Rendering Implementation

Use a DOCX-aware templating/fill mechanism. Preferred implementation: `docxtpl` / `python-docx-template`, because it allows filling placeholders while retaining the template's native Word layout.

Runtime flow:
1. load template from `app/assets/`
2. render placeholders from `ContractData`
3. save a temporary `.docx`
4. call LibreOffice Headless to convert that DOCX to PDF
5. verify output exists and starts with `%PDF`
6. return PDF bytes

LibreOffice remains only as a DOCX-to-PDF converter; it is no longer asked to interpret HTML/CSS.

## Dependency Change
Add the minimum DOCX templating dependency to `requirements.txt`.

No new external service is introduced.

## Error Handling
Raise the existing `ContractRenderError` for:
- missing template
- invalid/unreadable template
- DOCX render failure
- LibreOffice conversion failure
- missing or invalid PDF output

Do not expose internal filesystem paths to callers.

## Testing

### Structural regression tests
Verify:
- renderer uses the DOCX template path
- all required context keys are present
- legal clauses and OTP/Active wording are unchanged
- page-specific content remains assigned to the intended page
- render function returns valid PDF bytes using a test converter stub where practical

### Visual QA
Before production deployment:
1. generate a sample DOCX using representative merchant data
2. render it with LibreOffice using the same headless path as production
3. inspect all three pages at 100% zoom
4. compare against the approved reference image
5. iterate until no clipping, overlap, reversed layout, broken Arabic, or page-count drift remains

Acceptance criteria:
- exactly 3 physical A4 pages
- Pakgat right / merchant left on page 1 and page 3
- logo matches approved reference
- clean RTL Arabic and stable LTR identifiers
- no clause splits
- no extra pages
- no large unexplained blank regions
- visual hierarchy and spacing closely match the approved reference

## Rollout
Deploy only the contract rendering files and dependency change. Restart only `pakgat-voucher.service`.

Do not restart or modify Jood-related services.

If the new renderer fails during verification, keep production on the current contract renderer until the DOCX path passes visual QA.
