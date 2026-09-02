"""Deterministic three-page LibreOffice export for the merchant agreement."""
from __future__ import annotations

import base64
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from app import merchant_contract_pdf as contract_pdf

_BREAK_RE = re.compile(r'</section>\s*<section class="page">', re.I)
_PAGE_BREAK_STYLE = (
    '<style:style style:name="PakgatPageBreak" style:family="paragraph">'
    '<style:paragraph-properties fo:break-before="page"/>'
    '</style:style>'
)


def _inject_page_break_markers(html: str) -> str:
    marker = 1

    def repl(_match: re.Match[str]) -> str:
        nonlocal marker
        marker += 1
        return f'</section><p>[[PAKGAT_PAGE_BREAK_{marker}]]</p><section class="page">'

    rendered, count = _BREAK_RE.subn(repl, html)
    if count != 2:
        raise contract_pdf.ContractRenderError("Merchant contract page structure is invalid")
    return rendered


def _patch_odt_page_breaks(source: Path, target: Path) -> None:
    try:
        with zipfile.ZipFile(source, "r") as zin:
            entries = {name: zin.read(name) for name in zin.namelist()}
    except (OSError, zipfile.BadZipFile):
        raise contract_pdf.ContractRenderError("Merchant contract ODT conversion failed") from None

    try:
        content = entries["content.xml"].decode("utf-8")
    except (KeyError, UnicodeDecodeError):
        raise contract_pdf.ContractRenderError("Merchant contract ODT conversion failed") from None

    if 'style:name="PakgatPageBreak"' not in content:
        needle = "</office:automatic-styles>"
        if needle not in content:
            raise contract_pdf.ContractRenderError("Merchant contract ODT styles are invalid")
        content = content.replace(needle, _PAGE_BREAK_STYLE + needle, 1)

    for marker in (2, 3):
        pattern = rf'<text:p[^>]*>\s*\[\[PAKGAT_PAGE_BREAK_{marker}\]\]\s*</text:p>'
        content, count = re.subn(
            pattern,
            '<text:p text:style-name="PakgatPageBreak"/>',
            content,
            count=1,
        )
        if count != 1:
            raise contract_pdf.ContractRenderError("Merchant contract page marker is missing")

    entries["content.xml"] = content.encode("utf-8")
    try:
        with zipfile.ZipFile(target, "w") as zout:
            mimetype = entries.pop("mimetype", b"application/vnd.oasis.opendocument.text")
            zout.writestr("mimetype", mimetype, compress_type=zipfile.ZIP_STORED)
            for name, payload in entries.items():
                zout.writestr(name, payload, compress_type=zipfile.ZIP_DEFLATED)
    except OSError:
        raise contract_pdf.ContractRenderError("Merchant contract ODT patch failed") from None


def _run_libreoffice(source: Path, output_dir: Path, target_format: str, profile_name: str) -> None:
    executable = shutil.which("libreoffice") or shutil.which("soffice")
    if not executable:
        raise contract_pdf.ContractRenderError("LibreOffice is not installed on the server")
    profile_dir = output_dir / profile_name
    profile_dir.mkdir(parents=True, exist_ok=True)
    try:
        process = subprocess.run(
            [
                executable,
                f"-env:UserInstallation={profile_dir.resolve().as_uri()}",
                "--headless",
                "--nologo",
                "--nodefault",
                "--nofirststartwizard",
                "--convert-to",
                target_format,
                "--outdir",
                str(output_dir),
                str(source),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=45,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise contract_pdf.ContractRenderError("Merchant contract PDF conversion failed") from None
    if process.returncode != 0:
        raise contract_pdf.ContractRenderError("Merchant contract PDF conversion failed")


def render_contract_pdf_final(data: contract_pdf.ContractData, *, converter=None) -> bytes:
    """Render HTML -> ODT, inject real ODT page breaks, then export to PDF."""
    with tempfile.TemporaryDirectory(prefix="pakgat-contract-final-") as temp:
        root = Path(temp)
        html_path = root / "merchant-agreement.html"
        html_path.write_text(_inject_page_break_markers(contract_pdf.build_contract_html(data)), encoding="utf-8")

        try:
            uri = contract_pdf._logo_data_uri()
            logo_payload = base64.b64decode(uri.split(",", 1)[1])
        except Exception:
            raise contract_pdf.ContractRenderError("Pakgat contract logo is invalid") from None
        if not (logo_payload.startswith(b"\xff\xd8\xff") and logo_payload.endswith(b"\xff\xd9")):
            raise contract_pdf.ContractRenderError("Pakgat contract logo is invalid")
        (root / "pakgat-logo.jpg").write_bytes(logo_payload)

        _run_libreoffice(html_path, root, "odt", "libreoffice-html-profile")
        odt_path = root / "merchant-agreement.odt"
        if not odt_path.exists():
            raise contract_pdf.ContractRenderError("Merchant contract ODT was not generated")

        patched_odt = root / "merchant-agreement-final.odt"
        _patch_odt_page_breaks(odt_path, patched_odt)
        _run_libreoffice(patched_odt, root, "pdf", "libreoffice-pdf-profile")

        pdf_path = root / "merchant-agreement-final.pdf"
        if not pdf_path.exists():
            raise contract_pdf.ContractRenderError("Merchant contract PDF was not generated")
        pdf = pdf_path.read_bytes()
        if not pdf.startswith(b"%PDF"):
            raise contract_pdf.ContractRenderError("Generated merchant contract PDF is invalid")
        return pdf


contract_pdf.render_contract_pdf = render_contract_pdf_final

__all__ = [
    "_inject_page_break_markers",
    "_patch_odt_page_breaks",
    "render_contract_pdf_final",
]
