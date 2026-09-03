import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import application as core
from app import salla_data


class SallaRetentionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        salla_data.SallaOrderSnapshot.__table__.create(self.engine)
        self.db = Session(self.engine)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_customer_reference_is_stable_and_does_not_expose_salla_id(self):
        first = salla_data.customer_reference_hash("778899", "analytics-key")
        second = salla_data.customer_reference_hash("778899", "analytics-key")

        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)
        self.assertNotIn("778899", first)

    def test_extracts_customer_id_from_salla_order_shapes(self):
        self.assertEqual(salla_data.extract_salla_customer_id({"customer": {"id": 55}}), "55")
        self.assertEqual(salla_data.extract_salla_customer_id({"data": {"customer": {"id": "66"}}}), "66")
        self.assertEqual(salla_data.extract_salla_customer_id({"order": {"customer_id": 77}}), "77")

    def test_webhook_capture_stores_only_hashed_customer_reference(self):
        salla_data._capture_order_payload(self.db, {
            "event": "order.updated",
            "data": {"id": "o-private", "customer": {"id": "778899"}},
        })

        row = self.db.query(salla_data.SallaOrderSnapshot).one()
        self.assertEqual(row.customer_ref_hash, salla_data.customer_reference_hash("778899"))
        self.assertNotIn("778899", row.customer_ref_hash)

    def test_retention_metrics_count_only_confirmed_identified_customers(self):
        rows = [
            ("o1", "a", "paid", 100),
            ("o2", "a", "paid", 150),
            ("o3", "b", "completed", 80),
            ("o4", "c", "pending", 90),
            ("o5", None, "paid", 50),
        ]
        for order_id, customer_ref, payment_status, total in rows:
            self.db.add(salla_data.SallaOrderSnapshot(
                order_id=order_id,
                last_event="order.updated",
                payment_status=payment_status,
                total_amount=total,
                paid_amount=total if payment_status in {"paid", "completed"} else 0,
                customer_ref_hash=customer_ref,
            ))
        self.db.commit()

        metrics = salla_data.retention_metrics(self.db)

        self.assertEqual(metrics["identified_confirmed_orders"], 3)
        self.assertEqual(metrics["unique_customers"], 2)
        self.assertEqual(metrics["returning_customers"], 1)
        self.assertEqual(metrics["repeat_orders"], 1)
        self.assertEqual(metrics["repeat_customer_rate"], 50.0)
        self.assertEqual(metrics["coverage_percent"], 75.0)


if __name__ == "__main__":
    unittest.main()
