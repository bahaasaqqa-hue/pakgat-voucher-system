"""Merchant contract DOCX rendering regression tests."""
from __future__ import annotations

import zipfile
from io import BytesIO

from app import merchant_contract_pdf_otp_patch as patch
from app.merchant_contract_pdf import ContractData, build_contract_docx, render_contract_pdf


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


def _doc_xml(docx_bytes: bytes) -> str:
    with zipfile.ZipFile(BytesIO(docx_bytes)) as archive:
        return archive.read("word/document.xml").decode("utf-8")


def test_contract_is_native_docx_and_keeps_three_page_structure():
    docx = build_contract_docx(_sample())
    assert docx.startswith(b"PK")
    with zipfile.ZipFile(BytesIO(docx)) as archive:
        names = set(archive.namelist())
        assert "word/document.xml" in names
        assert any(name.startswith("word/media/") for name in names)
        xml = archive.read("word/document.xml").decode("utf-8")
        assert xml.count("w:sectPr") >= 3
        assert "أولاً: أطراف الاتفاقية" in xml
        assert "ثانياً: التمهيد" in xml
        assert "ثالثاً: الشروط والأحكام (1)" in xml
        assert "ثالثاً: الشروط والأحكام (2)" in xml
        assert "رابعاً: الموافقة الإلكترونية والاعتماد النهائي" in xml
        assert "الطرف الثاني (التاجر)" in xml
        assert "الطرف الأول" in xml


def test_contract_preserves_dynamic_values_legal_copy_and_otp_logic():
    xml = _doc_xml(build_contract_docx(_sample()))
    for value in (
        "PKG-MA-2026-09-0001", "02-09-2026", "متجر الاختبار",
        "1010101010", "310000000000003", "SA0000000000000000000000",
        "0500000000", "merchant@example.test", "ممثل المنشأة",
    ):
        assert value in xml
    for number, title, body in patch.CLAUSES:
        assert str(number) in xml
        assert title in xml
        assert body in xml
    assert "الميزانيات الإعلانية" in xml
    assert patch.ACTIVATION_COPY in xml
    assert "لا يتم تفعيل حساب التاجر تلقائياً" in xml
    assert "الحالة: لا يصبح الحساب Active إلا بعد الاعتماد النهائي" in xml
    assert "يقوم التاجر بتحميل هذه الاتفاقية وتوقيعها وختمها" not in xml


def test_renderer_passes_docx_to_converter_and_returns_pdf():
    seen = {}

    def converter(source_path, output_dir):
        seen["suffix"] = source_path.suffix
        payload = source_path.read_bytes()
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            assert "word/document.xml" in archive.namelist()
        (output_dir / "merchant-agreement.pdf").write_bytes(b"%PDF-1.4\n%stub\n")

    pdf = patch.render_contract_pdf_otp(_sample(), converter=converter)
    assert seen["suffix"] == ".docx"
    assert pdf.startswith(b"%PDF")


def test_renderer_monkey_patch_is_active():
    assert render_contract_pdf is patch.render_contract_pdf_otp
    assert build_contract_docx is patch.build_contract_docx_otp
