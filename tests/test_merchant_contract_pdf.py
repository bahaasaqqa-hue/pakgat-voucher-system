"""Presentation-level regression tests for the Pakgat merchant contract PDF."""

from __future__ import annotations

import unittest

from app.merchant_contract_pdf import ContractData, build_contract_html


class MerchantContractPresentationTests(unittest.TestCase):
    def setUp(self):
        self.data = ContractData(
            agreement_number="PKG-MA-2026-09-0001",
            agreement_date="02-09-2026",
            legal_name="شركة الاختبار للتجارة",
            commercial_registration="1010101010",
            activity="تجارة التجزئة",
            tax_number="310000000000003",
            bank_name="بنك الاختبار",
            iban="SA0000000000000000000000",
            national_address="الرياض",
            contact_phone="0500000000",
            contact_email="merchant@example.test",
            website="https://example.test",
            representative_name="ممثل المنشأة",
            representative_title="المدير العام",
        )

    def test_contract_is_three_balanced_pages_with_brand_logo(self):
        html = build_contract_html(self.data)
        self.assertEqual(html.count('class="contract-page"'), 3)
        self.assertIn("data:image/jpeg;base64,", html)
        self.assertIn("اتفاقية شراكة", html)
        self.assertIn(self.data.agreement_number, html)

    def test_contract_uses_manual_signature_flow_only(self):
        html = build_contract_html(self.data)
        self.assertNotIn("صادق", html)
        self.assertNotIn("نفاذ", html)
        self.assertIn("يوقّع التاجر العقد ويختمه", html)
        self.assertIn("موافقة Pakgat النهائية", html)
        self.assertIn("توقيع وختم الطرفين", html)

    def test_contract_contains_saved_merchant_profile(self):
        html = build_contract_html(self.data)
        for value in (
            self.data.legal_name,
            self.data.commercial_registration,
            self.data.tax_number,
            self.data.bank_name,
            self.data.iban,
            self.data.representative_name,
            self.data.representative_title,
        ):
            self.assertIn(value, html)


if __name__ == "__main__":
    unittest.main()
