"""Contract redesign regression tests."""
from __future__ import annotations

import base64
import unittest

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


class MerchantContractRedesignTests(unittest.TestCase):
    def test_contract_is_branded_otp_signing_and_three_pages(self):
        html = build_contract_html(_sample())
        self.assertIn("بكجات", html)
        self.assertIn('src="pakgat-logo.jpg"', html)
        self.assertEqual(html.count('class="page"'), 3)
        self.assertEqual(html.count('class="brand-logo"'), 1)
        self.assertIn("OTP", html)
        self.assertIn("الموافقة الإلكترونية", html)
        self.assertIn("الموافقة النهائية", html)
        self.assertNotIn("يقوم التاجر بتحميل هذه الاتفاقية وتوقيعها وختمها", html)
        self.assertNotIn("display:grid", html)
        self.assertNotIn("display:flex", html)
        self.assertNotIn("min-height:267mm", html)
        self.assertNotIn("صادق", html)
        self.assertNotIn("نفاذ", html)

    def test_contract_uses_libreoffice_safe_compact_tables(self):
        html = build_contract_html(_sample())
        self.assertIn('class="merchant-grid"', html)
        self.assertEqual(html.count('class="clause-columns"'), 2)
        self.assertIn('class="approval-table"', html)
        self.assertIn('page-break-inside:avoid', html)

    def test_contract_logo_asset_is_complete_jpeg(self):
        path = contract_pdf._asset_dir() / "pakgat_contract_logo.b64"
        encoded = "".join(path.read_text(encoding="ascii").split())
        payload = base64.b64decode(encoded + "=" * (-len(encoded) % 4), validate=True)
        self.assertTrue(payload.startswith(b"\xff\xd8\xff"))
        self.assertTrue(payload.endswith(b"\xff\xd9"))
        self.assertGreater(len(payload), 15000)

    def test_contract_keeps_ltr_identifiers_stable_inside_rtl_document(self):
        html = build_contract_html(_sample())
        self.assertIn('<span class="ltr">PKG-MA-2026-09-0001</span>', html)
        self.assertIn('<span class="ltr">SA0000000000000000000000</span>', html)
        self.assertIn('<span class="ltr">0500000000</span>', html)


if __name__ == "__main__":
    unittest.main()
