"""Build the approved Pakgat merchant agreement and render it as PDF."""

from __future__ import annotations

import base64
import hashlib
import html
import io
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

PAKGAT_SIGNER_NAME = "بهاء السقا"
PAKGAT_SIGNER_TITLE = "مدير تطوير الأعمال"
PAKGAT_SIGNER_PHONE = "0504161514"

TEMPLATE_PARTS = (
    "merchant_contract_final_00.b64",
    "merchant_contract_final_01.b64",
    "merchant_contract_final_02.b64",
    "merchant_contract_final_03a.b64",
    "merchant_contract_final_03b.b64",
    "merchant_contract_final_04.b64",
)
TEMPLATE_SHA256 = "24681ccf9215e84b624fd26cb9cb35137f24b44db72191e973d99cc0be16fcfe"


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
    """Reassemble one approved DOCX from checksum-locked parts and fail closed."""
    parts = [_asset_dir() / name for name in TEMPLATE_PARTS]
    if any(not part.is_file() for part in parts):
        raise ContractRenderError("Merchant contract template is missing")
    encoded = "".join(part.read_text(encoding="ascii").strip() for part in parts)
    try:
        payload = base64.b64decode(encoded, validate=True)
    except Exception:
        raise ContractRenderError("Merchant contract template is invalid") from None
    actual = hashlib.sha256(payload).hexdigest()
    if actual != TEMPLATE_SHA256:
        raise ContractRenderError("Merchant contract template checksum mismatch")
    try:
        with ZipFile(io.BytesIO(payload), "r") as archive:
            if archive.testzip() is not None:
                raise ContractRenderError("Merchant contract template is invalid")
            archive.getinfo("word/document.xml")
    except (BadZipFile, KeyError):
        raise ContractRenderError("Merchant contract template is invalid") from None
    return payload


def _xml_escape(value: str) -> str:
    return html.escape(str(value or "").strip(), quote=False)


def _replace_required_placeholder(xml: str, placeholder: str, value: str) -> str:
    if placeholder not in xml:
        raise ContractRenderError(
            f"Merchant contract template placeholder is missing: {placeholder}"
        )
    return xml.replace(placeholder, _xml_escape(value))


def build_contract_docx(data: ContractData) -> bytes:
    source = io.BytesIO(_template_bytes())
    output = io.BytesIO()
    replacements = (
        ("{{AGREEMENT_NUMBER}}", data.agreement_number),
        ("{{AGREEMENT_DATE}}", data.agreement_date),
        ("{{MERCHANT_NAME}}", data.legal_name),
        ("{{MERCHANT_CR}}", data.commercial_registration),
        ("{{MERCHANT_ACTIVITY}}", data.activity),
        ("{{MERCHANT_TAX_NUMBER}}", data.tax_number),
        ("{{MERCHANT_BANK}}", data.bank_name),
        ("{{MERCHANT_IBAN}}", data.iban),
        ("{{MERCHANT_ADDRESS}}", data.national_address),
        ("{{MERCHANT_PHONE}}", data.contact_phone),
        ("{{MERCHANT_EMAIL}}", data.contact_email),
        ("{{MERCHANT_WEBSITE}}", data.website or "لا يوجد"),
        ("{{MERCHANT_REP_NAME}}", data.representative_name),
        ("{{MERCHANT_REP_TITLE}}", data.representative_title),
    )
    with ZipFile(source, "r") as archive, ZipFile(output, "w", ZIP_DEFLATED) as rendered:
        for info in archive.infolist():
            payload = archive.read(info.filename)
            if info.filename == "word/document.xml":
                xml = payload.decode("utf-8")
                for placeholder, value in replacements:
                    xml = _replace_required_placeholder(xml, placeholder, value)
                if "{{" in xml or "}}" in xml:
                    raise ContractRenderError("Merchant contract contains unresolved placeholders")
                for fixed in (PAKGAT_SIGNER_NAME, PAKGAT_SIGNER_TITLE, PAKGAT_SIGNER_PHONE):
                    if fixed not in xml:
                        raise ContractRenderError("Merchant contract Pakgat representative data is missing")
                payload = xml.encode("utf-8")
            rendered.writestr(info, payload)
    result = output.getvalue()
    try:
        with ZipFile(io.BytesIO(result), "r") as rendered:
            if rendered.testzip() is not None:
                raise ContractRenderError("Generated merchant contract is invalid")
    except BadZipFile:
        raise ContractRenderError("Generated merchant contract is invalid") from None
    return result


def _libreoffice_converter(docx_path: Path, output_dir: Path) -> None:
    executable = shutil.which("libreoffice") or shutil.which("soffice")
    if not executable:
        raise ContractRenderError("LibreOffice is not installed on the server")
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
    "TEMPLATE_PARTS",
    "TEMPLATE_SHA256",
    "PAKGAT_SIGNER_NAME",
    "PAKGAT_SIGNER_TITLE",
    "PAKGAT_SIGNER_PHONE",
    "ContractData",
    "ContractRenderError",
    "build_contract_docx",
    "render_contract_pdf",
]
