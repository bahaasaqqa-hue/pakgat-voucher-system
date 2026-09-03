"""One-time loader for the Pakgat pilot opportunity scan.

The loader is intentionally temporary/test-oriented. It runs once per database,
identified by an audit marker, so normal application restarts do not keep
recreating the pilot opportunities.
"""

from __future__ import annotations

from sqlalchemy import select

from app import application as core
from app.ai_company_pilot_scan import run_pilot_scan


MARKER = "pilot_opportunity_scan_autoload_v1"


def autoload_once() -> None:
    try:
        with core.SessionLocal() as db:
            already_loaded = db.scalar(
                select(core.AuditLog.id)
                .where(core.AuditLog.action == MARKER)
                .limit(1)
            )
            if already_loaded:
                return

            created, skipped = run_pilot_scan(db)
            core.log_event(
                db,
                MARKER,
                details=f"created={created}; skipped={skipped}",
            )
            print(
                "Pakgat pilot opportunity scan autoloaded "
                f"created={created} skipped={skipped}"
            )
    except Exception as exc:
        # A pilot feed must never prevent the production voucher service from
        # starting. The admin can still run the scan manually from the dashboard.
        print(
            "Pakgat pilot opportunity autoload skipped: "
            f"{type(exc).__name__}: {str(exc)[:300]}"
        )


autoload_once()
