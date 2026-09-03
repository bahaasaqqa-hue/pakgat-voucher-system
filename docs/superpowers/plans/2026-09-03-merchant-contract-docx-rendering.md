# Merchant Contract DOCX Rendering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the merchant contract HTML renderer with a deterministic three-page DOCX-template renderer that preserves the approved Pakgat visual layout and existing OTP/Active/legal behavior.

**Architecture:** Keep `ContractData` and the public `render_contract_pdf` entry point compatible. Build a native A4 DOCX template under `app/assets/`, fill it with contract data using `docxtpl`, then use the existing LibreOffice Headless converter to produce the PDF. The application outside the merchant-contract rendering layer remains unchanged.

**Tech Stack:** Python, `docxtpl` / `python-docx-template`, `python-docx`, LibreOffice Headless, pytest.

**Spec:** `docs/superpowers/specs/2026-09-03-merchant-contract-docx-rendering-design.md`

## Global Constraints

- Exactly 3 physical A4 pages.
- Page 1: Pakgat card right, merchant card left, preamble, OTP approval box.
- Page 2: clauses 1–7 only.
- Page 3: clauses 8–13, final approval cards, activation note.
- Preserve legal clauses 1–13 verbatim.
- Preserve OTP behavior and wording; successful OTP does not activate the merchant automatically.
- Preserve final Pakgat approval / `Active` logic.
- Preserve Pakgat signer data.
- Use the approved Pakgat blue logo from the existing asset.
- Do not modify registration, Jood, WhatsApp, unrelated services, or unrelated endpoints.
- Restart only `pakgat-voucher.service` at rollout time.

---

### Task 1: Add DOCX dependencies and regression coverage

**Files:**
- Modify: `requirements.txt`
- Modify: `tests/test_merchant_contract_redesign.py`

**Interfaces:**
- Consumes: existing `ContractData`, `ContractRenderError`, current `render_contract_pdf` patch activation.
- Produces: regression expectations for template location, context generation, OTP/Active wording, clause grouping, and valid PDF bytes.

- [ ] **Step 1: Write failing tests for the new DOCX path**

Add tests that assert the patch exposes a DOCX-template path helper, returns a complete template context with all `ContractData` values and signer constants, preserves the exact OTP/Active sentence, and routes clauses 1–7 separately from 8–13.

- [ ] **Step 2: Run the focused contract test file and confirm RED**

Run:

```bash
python -m pytest tests/test_merchant_contract_redesign.py -q
```

Expected: failures for missing DOCX-template/context functions or missing dependency-backed rendering path.

- [ ] **Step 3: Add the minimal dependency**

Append:

```text
docxtpl==0.20.1
```

`docxtpl` pulls the compatible `python-docx` dependency and is sufficient for placeholder rendering.

- [ ] **Step 4: Keep all existing behavioral assertions**

Retain checks that legal text, OTP wording, final approval wording, and the 3-page content assignment have not changed.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt tests/test_merchant_contract_redesign.py
git commit -m "test: define DOCX merchant contract renderer"
```

### Task 2: Create the approved three-page DOCX template

**Files:**
- Create: `app/assets/merchant_contract_template.docx`
- Reuse: `app/assets/pakgat_contract_logo.b64`

**Interfaces:**
- Consumes: placeholder names defined by Task 3 context.
- Produces: native Word template with fixed A4 layout and placeholders.

- [ ] **Step 1: Build page 1 natively in DOCX**

Use A4 portrait with 8 mm left/right and 6 mm top/bottom margins. Create a three-column header table: blank left, centered Pakgat logo, title on right. Add the thin navy rule, subtitle, compact date/agreement bar, section heading, side-by-side cards with Pakgat right and merchant left, preamble, OTP box, and page-1 footer.

- [ ] **Step 2: Build page 2 with a hard page break**

Repeat the compact header, place `ثالثاً: الشروط والأحكام (1)`, then clauses 1–7 only. Apply `keep_with_next` / `keep_together` paragraph controls so clause title/body pairs do not split. Add the page-2 footer.

- [ ] **Step 3: Build page 3 with a hard page break**

Repeat the compact header, place `ثالثاً: الشروط والأحكام (2)`, clauses 8–13, final approval heading, equal Pakgat/merchant approval cards, activation note, and page-3 footer.

- [ ] **Step 4: Use fixed placeholders**

Use these exact placeholder names in the template:

```text
agreement_number
agreement_date
legal_name
activity
commercial_registration
tax_number
bank_name
iban
national_address
contact_phone
contact_email
website
representative_name
representative_title
pakgat_signer_name
pakgat_signer_title
```

Legal clauses and static OTP/Active copy remain literal template text so they cannot drift during rendering.

- [ ] **Step 5: Validate the DOCX container**

Open the `.docx` as ZIP and verify `word/document.xml`, relationships, media, and section/page-break markup exist.

- [ ] **Step 6: Commit**

```bash
git add app/assets/merchant_contract_template.docx
git commit -m "feat: add Pakgat merchant contract DOCX template"
```

### Task 3: Replace HTML rendering with DOCX template rendering

**Files:**
- Modify: `app/merchant_contract_pdf_otp_patch.py`
- Test: `tests/test_merchant_contract_redesign.py`

**Interfaces:**
- Consumes: `contract_pdf.ContractData`, `contract_pdf.ContractRenderError`, `contract_pdf._libreoffice_converter`.
- Produces:
  - `_contract_template_path() -> Path`
  - `_contract_template_context(data: ContractData) -> dict[str, str]`
  - `render_contract_pdf_otp(data: ContractData, *, converter=...) -> bytes`

- [ ] **Step 1: Implement the template-path helper**

Return `Path(__file__).resolve().parent / "assets" / "merchant_contract_template.docx"` and raise the existing safe render error if the file is missing.

- [ ] **Step 2: Implement the template context**

Map all mutable placeholders to stripped string values from `ContractData` and signer constants. Use `data.website or "لا يوجد"` for an empty website.

- [ ] **Step 3: Render a temporary DOCX**

Load `DocxTemplate(str(template_path))`, call `.render(context)`, and save to a temporary `merchant-agreement.docx`. Convert template/open/save exceptions into `ContractRenderError("Merchant contract DOCX could not be rendered")` without exposing filesystem details.

- [ ] **Step 4: Convert DOCX to PDF through the existing converter**

Call `converter(source_path, root)`, require `merchant-agreement.pdf`, verify `%PDF`, and return its bytes. Reuse existing safe error messages for missing/invalid PDF output.

- [ ] **Step 5: Keep application monkey-patching compatible**

Keep:

```python
contract_pdf.render_contract_pdf = render_contract_pdf_otp
```

If callers/tests still use `build_contract_html`, leave the old HTML builder untouched rather than routing production through it. The production PDF path must use DOCX only.

- [ ] **Step 6: Run focused tests**

```bash
python -m pytest tests/test_merchant_contract_redesign.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/merchant_contract_pdf_otp_patch.py tests/test_merchant_contract_redesign.py
git commit -m "feat: render merchant contracts from DOCX template"
```

### Task 4: Add deterministic renderer tests with a converter stub

**Files:**
- Modify: `tests/test_merchant_contract_redesign.py`

**Interfaces:**
- Consumes: `render_contract_pdf_otp`, generated temporary DOCX.
- Produces: test evidence that production rendering hands a `.docx` to the converter and returns PDF bytes.

- [ ] **Step 1: Add a converter stub test**

Create a stub converter that asserts the source suffix is `.docx`, opens the generated DOCX as ZIP to verify it is a valid Word document, and writes a minimal `%PDF-1.4` output at the expected location.

- [ ] **Step 2: Assert context substitution**

Inspect `word/document.xml` from the temporary DOCX and assert representative dynamic values such as `PKG-MA-2026-09-0001`, merchant legal name, IBAN, and representative name are present while raw Jinja placeholders are absent.

- [ ] **Step 3: Run tests**

```bash
python -m pytest tests/test_merchant_contract_redesign.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_merchant_contract_redesign.py
git commit -m "test: verify DOCX contract rendering flow"
```

### Task 5: Production-equivalent visual QA before rollout

**Files:**
- No application changes unless visual QA identifies template-only fixes.
- Modify if required: `app/assets/merchant_contract_template.docx`

**Interfaces:**
- Consumes: final template and renderer.
- Produces: sample PDF proven to be exactly three pages under LibreOffice Headless.

- [ ] **Step 1: Install the dependency in the production venv without restarting the service**

```bash
sudo -u pakgat /opt/pakgat-voucher-system/.venv/bin/pip install 'docxtpl==0.20.1'
```

- [ ] **Step 2: Generate a representative sample contract through Python**

Use the same `ContractData` fields as production and write the returned bytes to `/tmp/pakgat-contract-docx-test.pdf`.

- [ ] **Step 3: Verify physical page count**

Use an installed PDF inspection utility such as `pdfinfo`; expected result is exactly `Pages: 3`. If no PDF utility exists, inspect via the application's available PDF tooling rather than deploying blindly.

- [ ] **Step 4: Inspect all three rendered pages against the approved reference**

Acceptance checklist: title right, logo centered, Pakgat card right, merchant left, equal card sizing, clean RTL/LTR identifiers, page 2 contains 1–7, page 3 contains 8–13 plus approvals, no clipping/overlap, no extra pages, no large unexplained blank regions.

- [ ] **Step 5: Iterate template-only changes until accepted**

Do not alter legal/OTP/application logic for visual fixes. Only adjust DOCX spacing, table widths, row heights, font sizes, borders, and paragraph properties.

### Task 6: Controlled rollout

**Files:**
- Deploy only: `requirements.txt`, `app/merchant_contract_pdf_otp_patch.py`, `app/assets/merchant_contract_template.docx`.

**Interfaces:**
- Produces: production merchant contracts using DOCX rendering.

- [ ] **Step 1: Fetch `gce-migration` and verify deployed files**

Use `git show origin/gce-migration:<path>` to deploy only the approved renderer files; do not reset or overwrite unrelated local modifications.

- [ ] **Step 2: Install the pinned dependency**

```bash
sudo -u pakgat /opt/pakgat-voucher-system/.venv/bin/pip install -r /opt/pakgat-voucher-system/requirements.txt
```

- [ ] **Step 3: Compile/import smoke check before restart**

```bash
sudo -u pakgat /opt/pakgat-voucher-system/.venv/bin/python -m py_compile /opt/pakgat-voucher-system/app/merchant_contract_pdf_otp_patch.py
```

- [ ] **Step 4: Restart only the voucher service**

```bash
sudo systemctl restart pakgat-voucher.service
sudo systemctl status pakgat-voucher.service --no-pager -l
```

- [ ] **Step 5: Generate one fresh merchant contract and visually verify all three pages**

If verification fails, revert only the contract renderer/template to the previously working commit; do not touch Jood-related services.
