"""Production-safe Pakgat contract logo loader.

GitHub/text transports may wrap the base64 asset across lines. The contract
renderer originally used validate=True on the raw text, which rejects harmless
whitespace. Normalize whitespace first while retaining the JPEG signature check.
"""
from __future__ import annotations

import base64

from app import merchant_contract_pdf as contract_pdf


def _logo_data_uri_whitespace_safe() -> str:
    path = contract_pdf._asset_dir() / "pakgat_contract_logo.b64"
    if not path.is_file():
        raise contract_pdf.ContractRenderError("Pakgat contract logo is missing")
    try:
        encoded = "".join(path.read_text(encoding="ascii").split())
        payload = base64.b64decode(encoded, validate=True)
    except Exception:
        raise contract_pdf.ContractRenderError("Pakgat contract logo is invalid") from None
    if not payload.startswith(b"\xff\xd8\xff"):
        raise contract_pdf.ContractRenderError("Pakgat contract logo is invalid")
    return "data:image/jpeg;base64," + base64.b64encode(payload).decode("ascii")


contract_pdf._logo_data_uri = _logo_data_uri_whitespace_safe

__all__ = ["_logo_data_uri_whitespace_safe"]
