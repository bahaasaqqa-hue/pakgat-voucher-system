"""Bridge Sadq contract completion into the self-service onboarding lifecycle.

The existing Sadq webhook owns contract state.  This additive SQLAlchemy hook
observes only a transition to ``signed`` and moves the corresponding onboarding
application to Pakgat review.  It never activates a merchant.
"""

from __future__ import annotations

from sqlalchemy import event, inspect as sa_inspect, select
from sqlalchemy.orm import Session

from app import application as core
from app import merchant_finance as finance
from app import merchant_onboarding as onboarding


def _contract_just_became_signed(contract: finance.MerchantContract) -> bool:
    if contract.status != "signed":
        return False
    state = sa_inspect(contract)
    history = state.attrs.status.history
    return contract in state.session.new if state.session is not None else False


def _is_signed_transition(contract: finance.MerchantContract, session: Session) -> bool:
    if contract.status != "signed":
        return False
    if contract in session.new:
        return True
    history = sa_inspect(contract).attrs.status.history
    return bool(history.has_changes())


def _sync_one(session: Session, contract: finance.MerchantContract) -> None:
    with session.no_autoflush:
        application = session.scalar(
            select(onboarding.MerchantOnboardingApplication)
            .where(onboarding.MerchantOnboardingApplication.merchant_id == contract.merchant_id)
            .limit(1)
        )
    if application is None or application.status in {"approved", "rejected"}:
        return

    now = core.now_utc()
    application.status = "pending_review"
    application.review_note = None
    application.updated_at = now
    merchant = session.get(finance.Merchant, contract.merchant_id)
    if merchant is not None and merchant.status != "rejected":
        merchant.status = "pending"
        merchant.updated_at = now
        session.add(merchant)
    session.add(application)


@event.listens_for(Session, "before_flush")
def sync_signed_contract_to_onboarding(session: Session, flush_context, instances) -> None:
    """Move a signed onboarding contract to Pakgat review in the same DB commit."""
    _ = flush_context, instances
    candidates = list(session.new) + list(session.dirty)
    for obj in candidates:
        if isinstance(obj, finance.MerchantContract) and _is_signed_transition(obj, session):
            _sync_one(session, obj)


__all__ = ["sync_signed_contract_to_onboarding"]
