"""Contract redesign regression tests."""
from app import merchant_contract_pdf_otp_patch  # noqa: F401 - activate OTP contract copy
from app.merchant_contract_pdf import ContractData, build_contract_html


def _sample():
    return ContractData(
        agreement_number="PKG-MA-2026-09-0001", agreement_date="02-09-2026",
        legal_name="متجر الاختبار", commercial_registration="1010101010",
        activity="تجارة التجزئة", tax_number="310000000000003",
        bank_name="بنك الاختبار", iban="SA0000000000000000000000",
        national_address="الرياض", contact_phone="0500000000",
        contact_email="merchant@example.test", website="pakgat.com",
        representative_name="ممثل المنشأة", representative_title="المدير العام",
    )


def test_contract_is_branded_otp_signing_and_three_pages():
    html = build_contract_html(_sample())
    assert "بكجات" in html
    assert 'src="pakgat-logo.jpg"' in html
    assert html.count('<section class="page"') == 3
    assert html.count('class="brand-logo"') == 3
    assert 'صفحة 1 من 3' in html
    assert 'صفحة 2 من 3' in html
    assert 'صفحة 3 من 3' in html
    assert "OTP" in html
    assert "الموافقة الإلكترونية" in html
    assert "الموافقة النهائية" in html
    assert "يقوم التاجر بتحميل هذه الاتفاقية وتوقيعها وختمها" not in html
    assert "display:grid" not in html
    assert "display:flex" not in html
    assert "position:fixed" not in html.replace(" ", "")
    assert "صادق" not in html
    assert "نفاذ" not in html


def test_contract_uses_libreoffice_safe_tables_and_explicit_page_breaks():
    html = build_contract_html(_sample())
    assert html.count('class="page-break"') == 2
    assert '.page-break { page-break-before:always;' in html
    assert html.count('class="brand" dir="ltr"') == 3
    assert 'width="33%" class="brand-logo-cell" align="center"' in html
    assert 'width="33%" class="brand-title" align="right"' in html
    assert 'class="party-grid" dir="ltr"' in html
    assert 'width="50%" class="merchant-cell"' in html
    assert 'width="50%" class="pakgat-cell"' in html
    assert html.count('class="party-card-title"') == 2
    assert 'class="signing-box"' in html
    assert 'class="activation-box"' in html
    assert 'class="approval-grid" dir="ltr"' in html

    page2 = html.split('id="contract-page-2">', 1)[1].split('id="contract-page-3">', 1)[0]
    page3 = html.split('id="contract-page-3">', 1)[1]
    assert "7. السرية وحماية البيانات" in page2
    assert "8. حدود الصلاحيات والتعديلات" not in page2
    assert "8. حدود الصلاحيات والتعديلات" in page3
    assert "13. أحكام عامة" in page3
    assert "رابعاً: الموافقة الإلكترونية والاعتماد النهائي" in page3


def test_contract_keeps_ltr_identifiers_stable_inside_rtl_document():
    html = build_contract_html(_sample())
    assert '<span class="ltr">PKG-MA-2026-09-0001</span>' in html
    assert '<span class="ltr">SA0000000000000000000000</span>' in html
    assert '<span class="ltr">0500000000</span>' in html
