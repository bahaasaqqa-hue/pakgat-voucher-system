"""Build the approved Pakgat merchant agreement and render it as PDF."""

from __future__ import annotations

import base64
import html
import io
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


PAKGAT_SIGNER_NAME = "بهاء السقا"
PAKGAT_SIGNER_TITLE = "مدير تطوير الأعمال"
PAKGAT_SIGNER_PHONE = "0504161514"


class ContractRenderError(RuntimeError):
    """Safe contract-generation error."""


@dataclass(frozen=True)
class ContractData:
    agreement_number: str
    agreement_date: str
    legal_name: str
    commercial_registration: str
    activity: str
    tax_number: str
    bank_name: str
    iban: str
    national_address: str
    contact_phone: str
    contact_email: str
    website: str
    representative_name: str
    representative_title: str


def _asset_dir() -> Path:
    return Path(__file__).resolve().parent / "assets"


def _template_bytes() -> bytes:
    names = (
        "merchant_contract_template_00.b64",
        "merchant_contract_template_01.b64",
        "merchant_contract_template_02.b64",
        "merchant_contract_template_03a.b64",
        "merchant_contract_template_03b.b64",
        "merchant_contract_template_03c.b64",
        "merchant_contract_template_04.b64",
        "merchant_contract_template_05.b64",
        "merchant_contract_template_06.b64",
        "merchant_contract_template_07.b64",
    )
    parts = [_asset_dir() / name for name in names]
    if any(not part.is_file() for part in parts):
        raise ContractRenderError("Merchant contract template is missing")
    encoded = "".join(part.read_text(encoding="ascii").strip() for part in parts)
    try:
        payload = base64.b64decode(encoded, validate=True)
    except Exception:
        raise ContractRenderError("Merchant contract template is invalid") from None
    if not payload.startswith(b"PK"):
        raise ContractRenderError("Merchant contract template is not a DOCX file")
    return payload


def _xml_escape(value: str) -> str:
    return html.escape(str(value or "").strip(), quote=False)


def _replace_row_value(xml: str, label: str, value: str) -> str:
    row_pattern = re.compile(r"<w:tr\b.*?</w:tr>", re.DOTALL)
    replacement = _xml_escape(value)
    replaced = False

    def replace_row(match: re.Match[str]) -> str:
        nonlocal replaced
        row = match.group(0)
        if replaced or label not in row:
            return row
        new_row, count = re.subn(
            r"(<w:t(?:\s[^>]*)?>)_{5,}(</w:t>)",
            lambda item: item.group(1) + replacement + item.group(2),
            row,
            count=1,
        )
        if count:
            replaced = True
            return new_row
        return row

    result = row_pattern.sub(replace_row, xml)
    if not replaced:
        raise ContractRenderError(f"Merchant contract template field is missing: {label}")
    return result


def _replace_required_placeholder(xml: str, placeholder: str, value: str) -> str:
    if placeholder not in xml:
        raise ContractRenderError(f"Merchant contract template placeholder is missing: {placeholder}")
    return xml.replace(placeholder, _xml_escape(value))


def build_contract_docx(data: ContractData) -> bytes:
    source = io.BytesIO(_template_bytes())
    output = io.BytesIO()
    with ZipFile(source, "r") as archive, ZipFile(output, "w", ZIP_DEFLATED) as rendered:
        for info in archive.infolist():
            payload = archive.read(info.filename)
            if info.filename == "word/document.xml":
                xml = payload.decode("utf-8")
                agreement_placeholder = "رقم الاتفاقية: ______________"
                date_placeholder = "التاريخ: ____ / ____ / 20____"
                if agreement_placeholder not in xml or date_placeholder not in xml:
                    raise ContractRenderError("Merchant contract header placeholders are missing")
                xml = xml.replace(
                    agreement_placeholder,
                    "رقم الاتفاقية: " + _xml_escape(data.agreement_number),
                    1,
                )
                xml = xml.replace(
                    date_placeholder,
                    "التاريخ: " + _xml_escape(data.agreement_date),
                    1,
                )
                fields = (
                    ("اسم المنشأة / الطرف الثاني", data.legal_name),
                    ("السجل التجاري / الرقم الموحد", data.commercial_registration),
                    ("النشاط", data.activity),
                    ("الرقم الضريبي", data.tax_number),
                    ("البنك وIBAN", f"{data.bank_name} — {data.iban}"),
                    ("العنوان", data.national_address),
                    ("رقم الجوال", data.contact_phone),
                    ("البريد الإلكتروني", data.contact_email),
                    ("الموقع الإلكتروني", data.website or "لا يوجد"),
                    (
                        "اسم الممثل وصفته",
                        f"{data.representative_name} — {data.representative_title}",
                    ),
                )
                for label, value in fields:
                    xml = _replace_row_value(xml, label, value)

                signature_fields = (
                    ("{{PAKGAT_SIGNER_NAME}}", PAKGAT_SIGNER_NAME),
                    ("{{PAKGAT_SIGNER_TITLE}}", PAKGAT_SIGNER_TITLE),
                    ("{{PAKGAT_SIGNER_PHONE}}", PAKGAT_SIGNER_PHONE),
                    ("{{MERCHANT_REP_NAME}}", data.representative_name),
                    ("{{MERCHANT_REP_TITLE}}", data.representative_title),
                    ("{{MERCHANT_PHONE}}", data.contact_phone),
                    ("{{AGREEMENT_DATE}}", data.agreement_date),
                )
                for placeholder, value in signature_fields:
                    xml = _replace_required_placeholder(xml, placeholder, value)

                if "{{" in xml or "}}" in xml:
                    raise ContractRenderError("Merchant contract contains unresolved placeholders")
                payload = xml.encode("utf-8")
            rendered.writestr(info, payload)
    result = output.getvalue()
    if not result.startswith(b"PK"):
        raise ContractRenderError("Generated merchant contract is invalid")
    return result


def _libreoffice_converter(docx_path: Path, output_dir: Path) -> None:
    executable = shutil.which("libreoffice") or shutil.which("soffice")
    if not executable:
        raise ContractRenderError("LibreOffice is not installed on the server")

    # LibreOffice serializes work through its user profile. A shared/default
    # profile can deadlock concurrent web requests. Give every conversion a
    # private profile inside the request temp directory so attempts are isolated.
    profile_dir = output_dir / "libreoffice-profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    profile_uri = profile_dir.resolve().as_uri()

    try:
        process = subprocess.run(
            [
                executable,
                f"-env:UserInstallation={profile_uri}",
                "--headless",
                "--nologo",
                "--nodefault",
                "--nofirststartwizard",
                "--convert-to",
                "pdf",
                "--outdir",
                str(output_dir),
                str(docx_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=40,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ContractRenderError("Merchant contract PDF conversion failed") from None
    if process.returncode != 0:
        raise ContractRenderError("Merchant contract PDF conversion failed")


def render_contract_pdf(data: ContractData, *, converter=_libreoffice_converter) -> bytes:
    docx = build_contract_docx(data)
    with tempfile.TemporaryDirectory(prefix="pakgat-contract-") as temp:
        root = Path(temp)
        docx_path = root / "merchant-agreement.docx"
        docx_path.write_bytes(docx)
        converter(docx_path, root)
        pdf_path = root / "merchant-agreement.pdf"
        if not pdf_path.exists():
            raise ContractRenderError("Merchant contract PDF was not generated")
        pdf = pdf_path.read_bytes()
        if not pdf.startswith(b"%PDF"):
            raise ContractRenderError("Generated merchant contract PDF is invalid")
        return pdf


__all__ = [
    "PAKGAT_SIGNER_NAME",
    "PAKGAT_SIGNER_TITLE",
    "PAKGAT_SIGNER_PHONE",
    "ContractData",
    "ContractRenderError",
    "build_contract_docx",
    "render_contract_pdf",
]
