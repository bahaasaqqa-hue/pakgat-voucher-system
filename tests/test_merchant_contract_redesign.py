"""Contract redesign regression tests."""
from __future__ import annotations

import base64

from app import merchant_contract_pdf_otp_patch  # noqa: F401 - activate OTP contract copy
from app import merchant_contract_pdf as contract_pdf
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
    assert html.count('class="page"') == 3
    assert html.count('class="brand-logo"') == 1
    assert "OTP" in html
    assert "الموافقة الإلكترونية" in html
    assert "الموافقة النهائية" in html
    assert "يقوم التاجر بتحميل هذه الاتفاقية وتوقيعها وختمها" not in html
    assert "display:grid" not in html
    assert "display:flex" not in html
    assert "min-height:267mm" not in html
    assert "صادق" not in html
    assert "نفاذ" not in html


def test_contract_uses_libreoffice_safe_compact_tables():
    html = build_contract_html(_sample())
    assert 'class="merchant-grid"' in html
    assert html.count('class="clause-columns"') == 2
    assert 'class="approval-table"' in html
    assert 'page-break-inside:avoid' in html


def test_contract_logo_asset_is_complete_jpeg():
    path = contract_pdf._asset_dir() / "pakgat_contract_logo.b64"
    encoded = "".join(path.read_text(encoding="ascii").split())
    payload = base64.b64decode(encoded + "=" * (-len(encoded) % 4), validate=True)
    assert payload.startswith(b"\xff\xd8\xff")
    assert payload.endswith(b"\xff\xd9")
    assert len(payload) > 15000


def test_contract_keeps_ltr_identifiers_stable_inside_rtl_document():
    html = build_contract_html(_sample())
    assert '<span class="ltr">PKG-MA-2026-09-0001</span>' in html
    assert '<span class="ltr">SA0000000000000000000000</span>' in html
    assert '<span class="ltr">0500000000</span>' in html
