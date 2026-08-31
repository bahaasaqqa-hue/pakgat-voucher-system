import io
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app import merchant_contract_pdf


class MerchantContractPDFTests(unittest.TestCase):
    def _data(self):
        return merchant_contract_pdf.ContractData(
            agreement_number="PKG-MA-2026-08-0042",
            agreement_date="31 / 08 / 2026",
            legal_name="شركة تجربة التاجر المحدودة",
            commercial_registration="1010999999",
            activity="تجهيز الهدايا",
            tax_number="312000000000003",
            bank_name="البنك الأهلي السعودي",
            iban="SA1111111111111111111111",
            national_address="الرياض - المملكة العربية السعودية",
            contact_phone="0500000000",
            contact_email="merchant@example.com",
            website="https://merchant.example.com",
            representative_name="ممثل التاجر",
            representative_title="المدير العام",
        )

    def test_template_v2_removes_scout_offer_appendix_and_renumbers_terms(self):
        template = merchant_contract_pdf._template_bytes()
        with zipfile.ZipFile(io.BytesIO(template), "r") as archive:
            xml = archive.read("word/document.xml").decode("utf-8")

        for removed in (
            "ثانياً: توثيق مندوب الاستقطاب",
            "بيانات العرض / ملحق العرض",
            "اسم مندوب الاستقطاب",
            "Scout Code",
            "اسم العرض",
        ):
            self.assertNotIn(removed, xml)

        self.assertIn("ثالثاً: الشروط والأحكام", xml)
        self.assertIn("1. التزامات الطرف الأول (Pakgat)", xml)
        self.assertIn("13. أحكام عامة", xml)

    def test_real_template_is_filled_with_merchant_agreement_and_signer_data(self):
        docx = merchant_contract_pdf.build_contract_docx(self._data())

        self.assertTrue(docx.startswith(b"PK"))
        with zipfile.ZipFile(io.BytesIO(docx), "r") as archive:
            xml = archive.read("word/document.xml").decode("utf-8")

        for expected in (
            "PKG-MA-2026-08-0042",
            "31 / 08 / 2026",
            "شركة تجربة التاجر المحدودة",
            "1010999999",
            "تجهيز الهدايا",
            "312000000000003",
            "البنك الأهلي السعودي — SA1111111111111111111111",
            "الرياض - المملكة العربية السعودية",
            "0500000000",
            "merchant@example.com",
            "https://merchant.example.com",
            "ممثل التاجر — المدير العام",
            "ممثل التاجر",
            "المدير العام",
            "بهاء السقا",
            "مدير تطوير الأعمال",
            "0504161514",
        ):
            self.assertIn(expected, xml)

        for placeholder in (
            "{{PAKGAT_SIGNER_NAME}}",
            "{{PAKGAT_SIGNER_TITLE}}",
            "{{PAKGAT_SIGNER_PHONE}}",
            "{{MERCHANT_REP_NAME}}",
            "{{MERCHANT_REP_TITLE}}",
            "{{MERCHANT_PHONE}}",
            "{{AGREEMENT_DATE}}",
        ):
            self.assertNotIn(placeholder, xml)

    def test_render_contract_pdf_returns_pdf_and_uses_headless_converter(self):
        calls = []

        def fake_converter(docx_path, output_dir):
            calls.append((docx_path, output_dir))
            pdf_path = output_dir / (docx_path.stem + ".pdf")
            pdf_path.write_bytes(b"%PDF-1.7\ncontract\n")

        result = merchant_contract_pdf.render_contract_pdf(self._data(), converter=fake_converter)

        self.assertEqual(result, b"%PDF-1.7\ncontract\n")
        self.assertEqual(len(calls), 1)

    def test_libreoffice_uses_isolated_profile_and_finishes_before_nginx_timeout(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            docx_path = root / "merchant-agreement.docx"
            docx_path.write_bytes(b"PK-test")

            with mock.patch.object(merchant_contract_pdf.shutil, "which", return_value="/usr/bin/libreoffice"), mock.patch.object(
                merchant_contract_pdf.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=0, stdout=b"", stderr=b""),
            ) as run:
                merchant_contract_pdf._libreoffice_converter(docx_path, root)

        args, kwargs = run.call_args
        command = args[0]
        self.assertTrue(any(part.startswith("-env:UserInstallation=file://") for part in command))
        self.assertIn("--headless", command)
        self.assertLessEqual(kwargs["timeout"], 45)


if __name__ == "__main__":
    unittest.main()
