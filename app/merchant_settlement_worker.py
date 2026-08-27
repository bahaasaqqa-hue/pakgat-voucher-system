"""Prepare weekly merchant settlement batches every Thursday.

This worker calculates and groups eligible redeemed voucher payables. It never
transfers money, approves a settlement, or marks a batch paid; those actions
remain explicit admin actions with a recorded bank reference.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import application as core
from app import merchant_finance as finance


def prepare_thursday_settlements(
    db: Session,
    *,
    as_of: datetime | None = None,
) -> dict[str, int]:
    finance.ensure_merchant_finance_schema()
    finance.backfill_local_partners(db)
    finance.reconcile_redeemed_payables(db)

    as_of = as_of or core.now_utc()
    merchants = list(
        db.scalars(
            select(finance.Merchant)
            .where(finance.Merchant.status == "active")
            .order_by(finance.Merchant.id)
        ).all()
    )
    created = 0
    skipped = 0
    for merchant in merchants:
        batch = finance.build_weekly_settlement_batch(db, merchant.id, as_of=as_of)
        if batch:
            created += 1
            core.log_event(
                db,
                "merchant_settlement_batch_prepared",
                details=(
                    f"merchant_id={merchant.id}; batch_id={batch.id}; "
                    f"payable_amount={batch.payable_amount}"
                ),
            )
        else:
            skipped += 1
    return {"created": created, "skipped": skipped}


def run_once() -> dict[str, int]:
    with core.SessionLocal() as db:
        result = prepare_thursday_settlements(db)
    print(
        "merchant_settlement_batches_created="
        f"{result['created']} skipped={result['skipped']}"
    )
    return result


if __name__ == "__main__":
    run_once()


__all__ = ["prepare_thursday_settlements", "run_once"]
