"""Compatibility helpers for merchant contract OTP audit access."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from sqlalchemy import inspect, select

from app import merchant_contract_otp as otp
from app import merchant_manual_contract as manual


def safe_latest_signature_challenge(db, contract_id: int):
    try:
        if not inspect(db.connection()).has_table(otp.MerchantContractOtpChallenge.__tablename__):
            return None
    except Exception:
        return None
    return db.scalar(
        select(otp.MerchantContractOtpChallenge)
        .where(otp.MerchantContractOtpChallenge.contract_id == contract_id)
        .order_by(
            otp.MerchantContractOtpChallenge.created_at.desc(),
            otp.MerchantContractOtpChallenge.id.desc(),
        )
        .limit(1)
    )


def semantic_contract_fingerprint(merchant, application, contract) -> str:
    data = manual.contract_data_for(merchant, application, contract)
    payload = {
        "version": "merchant-partnership-otp-v2",
        "contract": asdict(data),
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


otp.latest_signature_challenge = safe_latest_signature_challenge
otp.contract_fingerprint = semantic_contract_fingerprint

__all__ = ["safe_latest_signature_challenge", "semantic_contract_fingerprint"]
