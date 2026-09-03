import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import application as core
from app.security_watch import security_watch_rows


class SecurityWatchTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        core.AuditLog.__table__.create(self.engine)
        core.CustomerNotification.__table__.create(self.engine)
        self.db = Session(self.engine)

    def tearDown(self):
        self.db.close(); self.engine.dispose()

    def test_security_watch_uses_recorded_failures_and_never_secrets(self):
        self.db.add(core.AuditLog(action="salla_webhook_rejected", details="Invalid signature"))
        self.db.commit()
        with patch("app.security_watch.Path.is_file", return_value=True):
            rows = security_watch_rows(self.db)
        values = " ".join(value for _, value, _ in rows)
        labels = {label: state for label, _, state in rows}
        self.assertEqual(labels["Webhook سلة مرفوض"], "pending")
        self.assertIn("لا تُعرض", values)
        self.assertNotIn(core.ADMIN_SECRET, values)


if __name__ == "__main__":
    unittest.main()
