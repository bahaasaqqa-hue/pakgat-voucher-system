"""Merchant contract integration helpers.

This module owns additive schema upgrades and, in later steps, Sadq completion
and signed-contract delivery. It deliberately does not alter voucher or finance
calculations.
"""

from __future__ import annotations

from sqlalchemy import Engine, inspect, text

from app import application as core
from app import merchant_finance as finance


AGREEMENT_NUMBER_INDEX = "uq_merchant_contracts_agreement_number"


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


__all__ = ["ensure_merchant_contract_schema"]
