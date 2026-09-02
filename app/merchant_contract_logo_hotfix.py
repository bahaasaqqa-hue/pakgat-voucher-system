"""Production-safe Pakgat contract logo loader.

The stored asset may arrive as normal Base64 or accidentally double-Base64
encoded through text transport. Normalize whitespace, decode once, and only
perform a second decode when the first result is still ASCII Base64 text.
"""
from __future__ import annotations

import base64
import binascii

from app import merchant_contract_pdf as contract_pdf


def _decode_logo_payload(encoded_text: str) -> bytes:
    encoded = "".join(str(encoded_text or "").split())
    try:
        payload = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise contract_pdf.ContractRenderError("Pakgat contract logo is invalid") from None

    if payload.startswith(b"\xff\xd8\xff"):
        return payload

    # Some text transports encoded the Base64 string itself a second time.
    try:
        inner = b"".join(payload.split())
        decoded_again = base64.b64decode(inner, validate=True)
    except (binascii.Error, ValueError):
        decoded_again = b""

    if decoded_again.startswith(b"\xff\xd8\xff"):
        return decoded_again

    raise contract_pdf.ContractRenderError("Pakgat contract logo is invalid")


def _logo_data_uri_transport_safe() -> str:
    path = contract_pdf._asset_dir() / "pakgat_contract_logo.b64"
    if not path.is_file():
        raise contract_pdf.ContractRenderError("Pakgat contract logo is missing")
    payload = _decode_logo_payload(path.read_text(encoding="ascii"))
    return "data:image/jpeg;base64," + base64.b64encode(payload).decode("ascii")


contract_pdf._logo_data_uri = _logo_data_uri_transport_safe

__all__ = ["_decode_logo_payload", "_logo_data_uri_transport_safe"]
