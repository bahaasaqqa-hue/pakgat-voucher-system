"""Merchant contract integration helpers.

This module owns additive schema upgrades, Sadq contract lifecycle state, and
signed-contract delivery audit. It deliberately does not alter voucher,
settlement, or merchant activation logic.
"""

from __future__ import annotations

import hmac
import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request as UrlRequest, urlopen

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import DateTime, Engine, Integer, String, Text, inspect, select, text
from sqlalchemy.orm import Mapped, Session, mapped_column

from app import application as core
from app import merchant_finance as finance
from app.jood_outbound import _send_whatsloop_text


AGREEMENT_NUMBER_INDEX = "uq_merchant_contracts_agreement_number"
SADQ_WEBHOOK_TOKEN = os.getenv("SADQ_WEBHOOK_TOKEN", "").strip()
SADQ_API_BASE_URL = os.getenv("SADQ_API_BASE_URL", "https://sandbox-api.sadq-sa.com").rstrip("/")
SADQ_BEARER_TOKEN = os.getenv("SADQ_BEARER_TOKEN", "").strip()
PAKGAT_CONTRACT_SIGNER_NAME = "بهاء السقا"
PAKGAT_CONTRACT_SIGNER_TITLE = "مدير تطوير الأعمال"
PAKGAT_CONTRACT_SIGNER_PHONE = "0504161514"
CONTRACT_TEMPLATE_VERSION = "merchant-partnership-v1"


class MerchantContractApproval(core.Base):
    """Immutable first-party approval snapshot for one merchant contract."""

    __tablename__ = "merchant_contract_approvals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    merchant_contract_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    merchant_id: Mapped[int] = mapped_column(Integer, index=True)
    agreement_number_snapshot: Mapped[str] = mapped_column(String(40))
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    pakgat_signer_name: Mapped[str] = mapped_column(String(255))
    pakgat_signer_title: Mapped[str] = mapped_column(String(255))
    pakgat_signer_phone: Mapped[str] = mapped_column(String(40))
    merchant_snapshot_json: Mapped[str] = mapped_column(Text)
    template_version: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=core.now_utc)


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
    MerchantContractApproval.__table__.create(target, checkfirst=True)


def _merchant_approval_snapshot(merchant: finance.Merchant) -> str:
    snapshot = {
        "merchant_id": merchant.id,
        "code": merchant.code,
        "display_name": merchant.display_name,
        "legal_name": merchant.legal_name,
        "commercial_registration": merchant.commercial_registration,
        "tax_number": merchant.tax_number,
        "contact_phone": merchant.contact_phone,
        "contact_email": merchant.contact_email,
        "bank_name": merchant.bank_name,
        "iban": merchant.iban,
    }
    return json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def approve_contract(
    db: Session,
    contract: finance.MerchantContract,
    approved_at: Optional[datetime] = None,
) -> MerchantContractApproval:
    """Freeze Pakgat first-party approval without activating the merchant."""
    existing = db.scalar(
        select(MerchantContractApproval)
        .where(MerchantContractApproval.merchant_contract_id == contract.id)
        .limit(1)
    )
    if existing is not None:
        return existing
    if contract.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft contracts can be approved")

    merchant = db.get(finance.Merchant, contract.merchant_id)
    if merchant is None:
        raise HTTPException(status_code=404, detail="Merchant not found")

    when = approved_at or core.now_utc()
    if not contract.agreement_number:
        contract.agreement_number = finance.next_agreement_number(db, when)

    approval = MerchantContractApproval(
        merchant_contract_id=contract.id,
        merchant_id=merchant.id,
        agreement_number_snapshot=contract.agreement_number,
        approved_at=when,
        pakgat_signer_name=PAKGAT_CONTRACT_SIGNER_NAME,
        pakgat_signer_title=PAKGAT_CONTRACT_SIGNER_TITLE,
        pakgat_signer_phone=PAKGAT_CONTRACT_SIGNER_PHONE,
        merchant_snapshot_json=_merchant_approval_snapshot(merchant),
        template_version=CONTRACT_TEMPLATE_VERSION,
        created_at=when,
    )
    contract.status = "approved_internal"
    contract.updated_at = when
    db.add(approval)
    db.add(contract)
    db.commit()
    db.refresh(approval)
    db.refresh(contract)
    return approval


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


def download_signed_sadq_pdf(document_id: str) -> tuple[bool, Optional[bytes], str]:
    """Download the final signed Sadq PDF without exposing provider credentials."""
    clean_document_id = str(document_id or "").strip()
    if not clean_document_id:
        return False, None, "sadq_document_id_missing"
    if not SADQ_BEARER_TOKEN:
        return False, None, "sadq_bearer_token_missing"

    url = f"{SADQ_API_BASE_URL}/api/v1/documents/{quote(clean_document_id, safe='')}/signed"
    provider_request = UrlRequest(
        url,
        headers={
            "Authorization": f"Bearer {SADQ_BEARER_TOKEN}",
            "Accept": "application/pdf",
        },
        method="GET",
    )
    try:
        with urlopen(provider_request, timeout=30) as response:
            status = int(getattr(response, "status", response.getcode()))
            content = response.read()
        if not 200 <= status < 300:
            return False, None, f"sadq_http_{status}"
        if not content:
            return False, None, "sadq_signed_pdf_empty"
        if not content.startswith(b"%PDF"):
            return False, None, "sadq_signed_document_not_pdf"
        return True, content, ""
    except HTTPError as exc:
        return False, None, f"sadq_http_{int(getattr(exc, 'code', 0) or 0)}"
    except URLError:
        return False, None, "sadq_network_error"
    except Exception:
        return False, None, "sadq_download_error"


def _send_whatsloop_document(
    phone: str,
    pdf_content: bytes,
    filename: str,
) -> tuple[bool, str]:
    """Document adapter intentionally fails closed until WhatsLoop send-file API is documented."""
    _ = phone, pdf_content, filename
    return False, "whatsloop_document_sender_not_configured"


def _delivery_message(agreement_number: str) -> str:
    return (
        "تم توقيع اتفاقية الشراكة مع Pakgat بنجاح ✅\n"
        f"رقم الاتفاقية: {agreement_number}\n"
        "سيكون التواصل التشغيلي معك عبر رقم الواتساب المسجل لدينا."
    )


def _get_or_create_delivery(
    db: Session,
    contract: finance.MerchantContract,
) -> finance.MerchantContractDelivery:
    delivery = db.scalar(
        select(finance.MerchantContractDelivery).where(
            finance.MerchantContractDelivery.merchant_contract_id == contract.id,
            finance.MerchantContractDelivery.channel == "whatsapp",
        )
    )
    if delivery is not None:
        return delivery
    delivery = finance.MerchantContractDelivery(
        merchant_contract_id=contract.id,
        merchant_id=contract.merchant_id,
        channel="whatsapp",
        status="pending",
        attempt_count=0,
        created_at=core.now_utc(),
        updated_at=core.now_utc(),
    )
    db.add(delivery)
    db.flush()
    return delivery


def _fail_delivery(
    db: Session,
    delivery: finance.MerchantContractDelivery,
    error: str,
) -> finance.MerchantContractDelivery:
    delivery.status = "failed"
    delivery.last_error = str(error or "delivery_failed")[:500]
    delivery.updated_at = core.now_utc()
    db.commit()
    db.refresh(delivery)
    return delivery


def deliver_signed_contract(
    db: Session,
    contract: finance.MerchantContract,
) -> finance.MerchantContractDelivery:
    """Notify the merchant and audit signed-PDF delivery without changing contract state."""
    delivery = _get_or_create_delivery(db, contract)
    if delivery.status == "sent":
        return delivery

    delivery.attempt_count = int(delivery.attempt_count or 0) + 1
    delivery.updated_at = core.now_utc()

    if contract.status != "signed":
        return _fail_delivery(db, delivery, "contract_not_signed")
    if not contract.agreement_number:
        return _fail_delivery(db, delivery, "agreement_number_missing")

    merchant = db.get(finance.Merchant, contract.merchant_id)
    if merchant is None:
        return _fail_delivery(db, delivery, "merchant_not_found")
    phone = core.normalize_saudi_phone(merchant.contact_phone or "")
    if not phone:
        return _fail_delivery(db, delivery, "merchant_contact_phone_missing")
    delivery.destination = phone

    pdf_ok, pdf_content, pdf_error = download_signed_sadq_pdf(contract.sadq_document_id or "")
    if not pdf_ok or pdf_content is None:
        return _fail_delivery(db, delivery, pdf_error or "sadq_signed_pdf_download_failed")

    if not delivery.provider_message_id:
        text_ok, _text_summary = _send_whatsloop_text(
            phone,
            _delivery_message(contract.agreement_number),
        )
        if not text_ok:
            return _fail_delivery(db, delivery, "whatsloop_text_failed")
        delivery.provider_message_id = "text_sent"
        delivery.updated_at = core.now_utc()
        db.flush()

    document_ok, document_result = _send_whatsloop_document(
        phone,
        pdf_content,
        f"{contract.agreement_number}.pdf",
    )
    if not document_ok:
        return _fail_delivery(
            db,
            delivery,
            document_result or "whatsloop_document_delivery_failed",
        )

    delivery.status = "sent"
    delivery.last_error = None
    delivery.sent_at = core.now_utc()
    delivery.updated_at = delivery.sent_at
    if document_result:
        delivery.provider_message_id = str(document_result)[:255]
    db.commit()
    db.refresh(delivery)
    return delivery


def _admin_guard(request: Request):
    try:
        core.require_admin(request)
    except HTTPException:
        return RedirectResponse("/admin/login", status_code=303)
    return None


def _latest_merchant_contract(
    db: Session,
    merchant_id: int,
) -> Optional[finance.MerchantContract]:
    return db.scalar(
        select(finance.MerchantContract)
        .where(finance.MerchantContract.merchant_id == merchant_id)
        .order_by(finance.MerchantContract.created_at.desc())
        .limit(1)
    )


def _contract_delivery(
    db: Session,
    contract_id: int,
) -> Optional[finance.MerchantContractDelivery]:
    return db.scalar(
        select(finance.MerchantContractDelivery)
        .where(
            finance.MerchantContractDelivery.merchant_contract_id == contract_id,
            finance.MerchantContractDelivery.channel == "whatsapp",
        )
        .limit(1)
    )


def merchant_contract_summary_html(db: Session, merchant_id: int) -> str:
    """Render safe contract/Sadq/WhatsApp audit data for the existing merchant page."""
    contract = _latest_merchant_contract(db, merchant_id)
    if contract is None:
        return (
            "<section id='merchant-contract-summary' class='card' "
            "style='padding:18px;margin-bottom:18px'>"
            "<h2>اتفاقية الشراكة</h2>"
            "<p class='muted'>لا توجد اتفاقية شراكة مرتبطة بهذا التاجر بعد.</p>"
            "</section>"
        )

    delivery = _contract_delivery(db, contract.id)
    delivery_status = delivery.status if delivery else "لم تبدأ"
    attempts = int(delivery.attempt_count or 0) if delivery else 0
    destination = delivery.destination if delivery else "—"
    last_error = delivery.last_error if delivery else "—"
    sent_at = delivery.sent_at if delivery else None
    retry_html = ""
    if contract.status == "signed" and (delivery is None or delivery.status != "sent"):
        retry_html = (
            f"<form method='post' action='/admin/merchants/{merchant_id}/contracts/{contract.id}/retry-whatsapp' "
            "style='margin-top:14px'>"
            "<button class='btn btn-blue' type='submit'>إعادة إرسال نسخة العقد</button>"
            "</form>"
        )

    return f"""
    <section id='merchant-contract-summary' class='card' style='padding:18px;margin-bottom:18px'>
      <h2>اتفاقية الشراكة</h2>
      <div class='grid grid-mobile-1' style='grid-template-columns:repeat(2,1fr);gap:10px'>
        <p><strong>رقم الاتفاقية:</strong> <span dir='ltr'>{core.esc(contract.agreement_number or '—')}</span></p>
        <p><strong>حالة العقد:</strong> {core.esc(contract.status)}</p>
        <p><strong>Sadq Document ID:</strong> <span dir='ltr'>{core.esc(contract.sadq_document_id or '—')}</span></p>
        <p><strong>Sadq Request ID:</strong> <span dir='ltr'>{core.esc(contract.sadq_transaction_id or '—')}</span></p>
        <p><strong>تاريخ التوقيع:</strong> {core.fmt_dt(contract.signed_at)}</p>
        <p><strong>حالة إرسال نسخة العقد:</strong> {core.esc(delivery_status)}</p>
        <p><strong>رقم الواتساب:</strong> <span dir='ltr'>{core.esc(destination or '—')}</span></p>
        <p><strong>عدد محاولات الإرسال:</strong> {attempts}</p>
        <p><strong>آخر إرسال ناجح:</strong> {core.fmt_dt(sent_at)}</p>
        <p><strong>آخر خطأ:</strong> <span dir='ltr'>{core.esc(last_error or '—')}</span></p>
      </div>
      <p class='muted' style='margin-bottom:0'>التوقيع يتم عبر صادق، والتحقق من هوية الموقّع يتم عبر نفاذ ضمن رحلة التوقيع المفعلة للعقد.</p>
      {retry_html}
    </section>
    """


@core.app.post("/admin/merchants/{merchant_id}/contracts/{contract_id}/retry-whatsapp")
def admin_retry_contract_whatsapp(
    merchant_id: int,
    contract_id: int,
    request: Request,
    db: Session = Depends(core.get_db),
):
    """Retry the existing WhatsApp delivery audit row for a signed contract."""
    redirect = _admin_guard(request)
    if redirect:
        return redirect
    contract = db.get(finance.MerchantContract, contract_id)
    if contract is None or contract.merchant_id != merchant_id:
        raise HTTPException(status_code=404, detail="Merchant contract not found")
    if contract.status != "signed":
        raise HTTPException(status_code=409, detail="Only signed contracts can be resent")
    deliver_signed_contract(db, contract)
    return RedirectResponse(f"/admin/merchants/{merchant_id}", status_code=303)


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

    if callback.status == "signed":
        try:
            deliver_signed_contract(db, contract)
        except Exception:
            db.rollback()

    return {
        "ok": True,
        "status": contract.status,
        "contract_id": contract.id,
    }


__all__ = [
    "MerchantContractApproval",
    "SadqCallback",
    "SADQ_WEBHOOK_TOKEN",
    "SADQ_API_BASE_URL",
    "SADQ_BEARER_TOKEN",
    "PAKGAT_CONTRACT_SIGNER_NAME",
    "PAKGAT_CONTRACT_SIGNER_TITLE",
    "PAKGAT_CONTRACT_SIGNER_PHONE",
    "CONTRACT_TEMPLATE_VERSION",
    "ensure_merchant_contract_schema",
    "approve_contract",
    "normalize_sadq_status",
    "extract_sadq_callback",
    "download_signed_sadq_pdf",
    "deliver_signed_contract",
    "merchant_contract_summary_html",
    "admin_retry_contract_whatsapp",
    "sadq_webhook",
]
