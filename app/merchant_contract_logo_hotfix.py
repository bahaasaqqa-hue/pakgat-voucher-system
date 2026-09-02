"""Production-safe Pakgat contract logo loader.

Normalize transport whitespace and repair missing Base64 padding before decode.
Supports both a normal JPEG Base64 payload and an accidentally double-Base64
encoded payload while retaining a strict JPEG signature check.
"""
from __future__ import annotations

import base64
import binascii

from app import merchant_contract_pdf as contract_pdf


def _decode_b64(value: str | bytes) -> bytes:
    if isinstance(value, bytes):
        compact = b"".join(value.split())
        compact += b"=" * (-len(compact) % 4)
        return base64.b64decode(compact, validate=True)
    compact = "".join(str(value or "").split())
    compact += "=" * (-len(compact) % 4)
    return base64.b64decode(compact, validate=True)


def _decode_logo_payload(encoded_text: str) -> bytes:
    try:
        payload = _decode_b64(encoded_text)
    except (binascii.Error, ValueError):
        raise contract_pdf.ContractRenderError("Pakgat contract logo is invalid") from None

    if payload.startswith(b"\xff\xd8\xff"):
        return payload

    try:
        decoded_again = _decode_b64(payload)
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
