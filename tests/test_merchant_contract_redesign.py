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
    assert "object-fit:contain" in html
    assert html.count('<section class="page') == 3
    assert html.count('class="brand-logo"') == 1
    assert 'class="page-number">صفحة 1 من 3' in html
    assert 'class="page-number">صفحة 2 من 3' in html
    assert 'class="page-number">صفحة 3 من 3' in html
    assert "text-align:right" in html
    assert "table-layout:fixed" in html
    assert "background:#f7f9fc" in html
    assert "OTP" in html
    assert "الموافقة الإلكترونية" in html
    assert "الموافقة النهائية" in html
    assert "يقوم التاجر بتحميل هذه الاتفاقية وتوقيعها وختمها" not in html
    assert "display:grid" not in html
    assert "display:flex" not in html
    assert "min-height:267mm" not in html
    assert "صادق" not in html
    assert "نفاذ" not in html


def test_contract_header_and_parties_match_approved_layout():
    html = build_contract_html(_sample())
    assert 'class="brand-title"' in html
    assert 'class="brand-logo-cell"' in html
    assert 'class="brand-spacer"' in html
    assert '.brand-title { width:33.33%; text-align:right;' in html
    assert '.brand-logo-cell { width:33.33%; text-align:center;' in html
    assert '.brand-spacer { width:33.33%;' in html
    assert 'class="party-grid"' in html
    assert html.count('class="party-card"') == 2
    assert html.count('class="party-card-title"') == 2
    assert '.party-card-title { font-size:10pt; font-weight:bold;' in html
    assert 'الطرف الأول' in html
    assert 'الطرف الثاني (التاجر)' in html


def test_contract_keeps_ltr_identifiers_stable_inside_rtl_document():
    html = build_contract_html(_sample())
    assert '<span class="ltr">PKG-MA-2026-09-0001</span>' in html
    assert '<span class="ltr">SA0000000000000000000000</span>' in html
    assert '<span class="ltr">0500000000</span>' in html
