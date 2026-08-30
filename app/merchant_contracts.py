"""Merchant contract integration helpers.

This module owns additive schema upgrades and Sadq contract lifecycle state.
It deliberately does not alter voucher, settlement, or merchant activation
logic.
"""

from __future__ import annotations

import hmac
import os
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy import Engine, inspect, select, text
from sqlalchemy.orm import Session

from app import application as core
from app import merchant_finance as finance


AGREEMENT_NUMBER_INDEX = "uq_merchant_contracts_agreement_number"
SADQ_WEBHOOK_TOKEN = os.getenv("SADQ_WEBHOOK_TOKEN", "").strip()


@dataclass(frozen=True)
class SadqCallback:
    request_id: str
    document_id: str
    status: Optional[str]


def ensure_merchant_contract_schema(engine: Engine | None = None) -> None:
    """Safely add contract integration storage to an existing Pakgat database."""
    target = engine or core.engine
    inspector = inspect(target)
    tables = set(inspector.get_table_names())

    if "merchant_contracts" not in tables:
        finance.MerchantContract.__table__.create(target, checkfirst=True)
    else:
        columns = {column["name"] for column in inspector.get_columns("merchant_contracts")}
        if "agreement_number" not in columns:
            with target.begin() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE merchant_contracts "
                        "ADD COLUMN agreement_number VARCHAR(40)"
                    )
                )

    with target.begin() as conn:
        conn.execute(
            text(
                f"CREATE UNIQUE INDEX IF NOT EXISTS {AGREEMENT_NUMBER_INDEX} "
                "ON merchant_contracts (agreement_number)"
            )
        )

    finance.MerchantContractDelivery.__table__.create(target, checkfirst=True)


def normalize_sadq_status(value) -> Optional[str]:
    """Map Sadq terminal request states to Pakgat contract states."""
    mapping = {
        "2": "signed",
        "completed": "signed",
        "success": "signed",
        "3": "cancelled",
        "cancelled": "cancelled",
        "canceled": "cancelled",
        "voided": "cancelled",
        "4": "rejected",
        "rejected": "rejected",
        "5": "expired",
        "expired": "expired",
    }
    return mapping.get(str(value if value is not None else "").strip().lower())


def extract_sadq_callback(payload: dict) -> SadqCallback:
    """Extract only the identifiers/status Pakgat needs from a Sadq callback."""
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Sadq webhook payload must be an object")
    request_id = str(payload.get("requestId") or payload.get("request_id") or "").strip()
    document_id = str(payload.get("documentId") or payload.get("document_id") or "").strip()
    if not request_id and not document_id:
        raise HTTPException(status_code=422, detail="Sadq requestId or documentId is required")
    return SadqCallback(
        request_id=request_id,
        document_id=document_id,
        status=normalize_sadq_status(payload.get("status")),
    )


def _incoming_webhook_token(request: Request) -> str:
    authorization = str(request.headers.get("authorization") or "").strip()
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return str(request.headers.get("x-sadq-webhook-token") or "").strip()


def _require_webhook_auth(request: Request) -> None:
    if not SADQ_WEBHOOK_TOKEN:
        raise HTTPException(status_code=503, detail="Sadq webhook authentication is not configured")
    supplied = _incoming_webhook_token(request)
    if not supplied or not hmac.compare_digest(supplied, SADQ_WEBHOOK_TOKEN):
        raise HTTPException(status_code=403, detail="Invalid Sadq webhook token")


def _find_contract(db: Session, callback: SadqCallback) -> Optional[finance.MerchantContract]:
    contract = None
    if callback.request_id:
        contract = db.scalar(
            select(finance.MerchantContract)
            .where(finance.MerchantContract.sadq_transaction_id == callback.request_id)
            .limit(1)
        )
    if contract is None and callback.document_id:
        contract = db.scalar(
            select(finance.MerchantContract)
            .where(finance.MerchantContract.sadq_document_id == callback.document_id)
            .limit(1)
        )
    return contract


def _validate_or_fill_sadq_ids(
    contract: finance.MerchantContract,
    callback: SadqCallback,
) -> None:
    if callback.request_id:
        if contract.sadq_transaction_id and contract.sadq_transaction_id != callback.request_id:
            raise HTTPException(status_code=409, detail="Sadq request identifier mismatch")
        if not contract.sadq_transaction_id:
            contract.sadq_transaction_id = callback.request_id
    if callback.document_id:
        if contract.sadq_document_id and contract.sadq_document_id != callback.document_id:
            raise HTTPException(status_code=409, detail="Sadq document identifier mismatch")
        if not contract.sadq_document_id:
            contract.sadq_document_id = callback.document_id


def _contract_note_text(contract: finance.MerchantContract, status: str) -> str:
    agreement = contract.agreement_number or "الاتفاقية"
    if status == "signed":
        return f"تم استلام تأكيد توقيع اتفاقية الشراكة {agreement} من صادق."
    labels = {
        "rejected": "مرفوضة",
        "cancelled": "ملغاة",
        "expired": "منتهية",
    }
    return f"تم تحديث حالة {agreement} في صادق إلى {labels.get(status, status)}."


@core.app.post("/integrations/sadq/webhook")
async def sadq_webhook(request: Request, db: Session = Depends(core.get_db)):
    """Apply authenticated Sadq terminal-state callbacks idempotently."""
    _require_webhook_auth(request)
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid Sadq webhook JSON") from exc

    callback = extract_sadq_callback(payload)
    contract = _find_contract(db, callback)
    if contract is None:
        raise HTTPException(status_code=404, detail="Merchant contract not found")

    _validate_or_fill_sadq_ids(contract, callback)

    if callback.status is None:
        return {
            "ok": True,
            "status": contract.status,
            "contract_id": contract.id,
            "ignored": True,
        }

    if contract.status == callback.status:
        return {
            "ok": True,
            "status": contract.status,
            "contract_id": contract.id,
            "idempotent": True,
        }

    contract.status = callback.status
    now = core.now_utc()
    contract.updated_at = now
    if callback.status == "signed" and contract.signed_at is None:
        contract.signed_at = now

    db.add(
        finance.MerchantNote(
            merchant_id=contract.merchant_id,
            note_type="contract",
            text=_contract_note_text(contract, callback.status),
            created_by="Sadq",
            created_at=now,
        )
    )
    db.commit()
    db.refresh(contract)

    return {
        "ok": True,
        "status": contract.status,
        "contract_id": contract.id,
    }


__all__ = [
    "SadqCallback",
    "SADQ_WEBHOOK_TOKEN",
    "ensure_merchant_contract_schema",
    "normalize_sadq_status",
    "extract_sadq_callback",
    "sadq_webhook",
]
