from app import application as core
from app.customer_notifications import dispatch_due_customer_notifications, send_whatsloop_text


def main() -> int:
    with core.SessionLocal() as db:
        result = dispatch_due_customer_notifications(db, send_whatsloop_text)
    print(f"customer_notifications sent={result.sent} failed={result.failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
