"""Periodic Google VM monitor for Pakgat AI Company.

Runs from a systemd timer. It never sends customer messages and never changes
Salla settings. It records operational snapshots, source status and internal alerts.
"""

from app import application as core
from app.ai_company import collect_company_snapshot, evaluate_alerts, save_snapshot
from app.ai_company_sources import refresh_source_inventory


def main() -> None:
    with core.SessionLocal() as db:
        refresh_source_inventory(db)
        snapshot = collect_company_snapshot(db)
        evaluate_alerts(db, snapshot)
        save_snapshot(db, snapshot)
        core.log_event(
            db,
            "ai_company_monitor",
            details=(
                f"health={snapshot['overall_score']}; "
                f"technology={snapshot['technology_score']}; "
                f"voucher={snapshot['voucher_score']}"
            ),
        )
    print(
        "Pakgat AI monitor OK "
        f"health={snapshot['overall_score']} "
        f"technology={snapshot['technology_score']} "
        f"voucher={snapshot['voucher_score']}"
    )


if __name__ == "__main__":
    main()
