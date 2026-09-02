import hashlib
import io
import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from pypdf import PdfReader

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app import merchant_contract_pdf


class MerchantContractPDFTests(unittest.TestCase):
    def _data(self):
        return merchant_contract_pdf.ContractData(
            agreement_number="PKG-MA-2026-09-0042",
            agreement_date="01 / 09 / 2026",
            legal_name="شركة تجربة التاجر المحدودة",
            commercial_registration="1010999999",
            activity="تجهيز الهدايا والهدايا المؤسسية",
            tax_number="312000000000003",
            bank_name="البنك الأهلي السعودي",
            iban="SA1111111111111111111111",
            national_address="الرياض - حي الرمال - المملكة العربية السعودية",
            contact_phone="0500000000",
            contact_email="merchant@example.com",
            website="https://merchant.example.com",
            representative_name="ممثل التاجر",
            representative_title="المدير العام",
        )

    def test_template_is_checksum_locked_valid_docx_and_has_final_structure(self):
        template = merchant_contract_pdf._template_bytes()
        self.assertEqual(hashlib.sha256(template).hexdigest(), merchant_contract_pdf.TEMPLATE_SHA256)
        with zipfile.ZipFile(io.BytesIO(template), "r") as archive:
            self.assertIsNone(archive.testzip())
            xml = archive.read("word/document.xml").decode("utf-8")
        for removed in (
            "ثانياً: توثيق مندوب الاستقطاب",
            "مندوب الاستقطاب",
            "Scout",
            "بيانات العرض / ملحق العرض",
            "ملحق العرض",
            "اسم العرض",
            "تاريخ تسجيل الـ Lead",
        ):
            self.assertNotIn(removed, xml)
        self.assertIn("ثالثاً: الشروط والأحكام", xml)
        for number in range(1, 14):
            self.assertIn(f"{number}. ", xml)
        self.assertIn("1. التزامات الطرف الأول (Pakgat)", xml)
        self.assertIn("13. أحكام عامة", xml)

    def test_real_template_is_filled_with_all_merchant_and_pakgat_data(self):
        docx = merchant_contract_pdf.build_contract_docx(self._data())
        self.assertTrue(docx.startswith(b"PK"))
        with zipfile.ZipFile(io.BytesIO(docx), "r") as archive:
            self.assertIsNone(archive.testzip())
            xml = archive.read("word/document.xml").decode("utf-8")
        for expected in (
            "PKG-MA-2026-09-0042", "01 / 09 / 2026", "شركة تجربة التاجر المحدودة",
            "1010999999", "تجهيز الهدايا والهدايا المؤسسية", "312000000000003",
            "البنك الأهلي السعودي", "SA1111111111111111111111",
            "الرياض - حي الرمال - المملكة العربية السعودية", "0500000000",
            "merchant@example.com", "https://merchant.example.com", "ممثل التاجر",
            "المدير العام", "بهاء السقا", "مدير تطوير الأعمال", "0504161514",
        ):
            self.assertIn(expected, xml)
        self.assertNotIn("{{", xml)
        self.assertNotIn("}}", xml)

    def test_template_checksum_rejects_modified_or_partial_docx(self):
        template_path = merchant_contract_pdf._asset_dir() / merchant_contract_pdf.TEMPLATE_PARTS[-1]
        original = template_path.read_text(encoding="ascii")
        try:
            template_path.write_text(original[:-8], encoding="ascii")
            with self.assertRaises(merchant_contract_pdf.ContractRenderError):
                merchant_contract_pdf._template_bytes()
        finally:
            template_path.write_text(original, encoding="ascii")

    def test_render_contract_pdf_returns_pdf_and_uses_converter(self):
        calls = []
        def fake_converter(docx_path, output_dir):
            calls.append((docx_path, output_dir))
            (output_dir / (docx_path.stem + ".pdf")).write_bytes(b"%PDF-1.7\ncontract\n")
        result = merchant_contract_pdf.render_contract_pdf(self._data(), converter=fake_converter)
        self.assertEqual(result, b"%PDF-1.7\ncontract\n")
        self.assertEqual(len(calls), 1)

    def test_libreoffice_uses_isolated_profile_and_finishes_before_nginx_timeout(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            docx_path = root / "merchant-agreement.docx"
            docx_path.write_bytes(b"PK-test")
            with mock.patch.object(merchant_contract_pdf.shutil, "which", return_value="/usr/bin/libreoffice"), mock.patch.object(
                merchant_contract_pdf.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
            ) as run:
                merchant_contract_pdf._libreoffice_converter(docx_path, root)
        args, kwargs = run.call_args
        command = args[0]
        self.assertTrue(any(part.startswith("-env:UserInstallation=file://") for part in command))
        self.assertIn("--headless", command)
        self.assertLessEqual(kwargs["timeout"], 45)

    @unittest.skipUnless(shutil.which("libreoffice") or shutil.which("soffice"), "LibreOffice not installed")
    def test_real_pdf_is_valid_four_pages_and_contains_key_data(self):
        pdf = merchant_contract_pdf.render_contract_pdf(self._data())
        self.assertTrue(pdf.startswith(b"%PDF"))
        reader = PdfReader(io.BytesIO(pdf))
        self.assertEqual(len(reader.pages), 4)
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
        for marker in ("1010999999", "312000000000003", "0500000000", "merchant@example", "0504161514"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
