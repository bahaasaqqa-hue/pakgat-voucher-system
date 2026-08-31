"""Bridge Sadq contract completion into the self-service onboarding lifecycle.

The existing Sadq webhook owns contract state. This additive SQLAlchemy hook
observes only a transition to ``signed`` and moves the corresponding onboarding
application to Pakgat review. It never activates a merchant.
"""

from __future__ import annotations

from sqlalchemy import event, inspect as sa_inspect, select
from sqlalchemy.orm import Session

from app import application as core
from app import merchant_finance as finance
from app import merchant_onboarding as onboarding
from app import merchant_onboarding_sadq_start as sadq_start


def _is_signed_transition(contract: finance.MerchantContract, session: Session) -> bool:
    if contract.status != "signed":
        return False
    if contract in session.new:
        return True
    return bool(sa_inspect(contract).attrs.status.history.has_changes())


def _onboarding_schema_available(session: Session) -> bool:
    """Return whether this Session's database has the onboarding application table."""
    try:
        bind = session.get_bind()
        return bool(sa_inspect(bind).has_table(onboarding.MerchantOnboardingApplication.__tablename__))
    except Exception:
        return False


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
    candidates = [
        obj
        for obj in list(session.new) + list(session.dirty)
        if isinstance(obj, finance.MerchantContract) and _is_signed_transition(obj, session)
    ]
    if not candidates or not _onboarding_schema_available(session):
        return
    for contract in candidates:
        _sync_one(session, contract)


# The core onboarding module intentionally registered a fail-closed submit route.
# Replace that single route only after all onboarding primitives are loaded.
sadq_start.install_submit_route()


__all__ = ["sync_signed_contract_to_onboarding"]
