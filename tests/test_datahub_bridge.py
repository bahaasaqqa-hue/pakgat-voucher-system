import types
import unittest
from datetime import datetime, timezone

from app import datahub


class FakeVoucher:
    def __init__(self):
        self.order_id = "ORDER-123"
        self.product_id = "PRODUCT-9"
        self.merchant_name = "Test Merchant"
        self.status = "redeemed"


class FakeDb:
    def get(self, model, voucher_id):
        return FakeVoucher() if voucher_id == 7 else None


class DataHubBridgeTests(unittest.TestCase):
    def test_safe_details_redacts_phone_and_provider_response(self):
        value = datahub._safe_details(
            "order=123; phone=0501234567; http_status=200; response={secret payload}"
        )
        self.assertNotIn("0501234567", value)
        self.assertIn("[phone-redacted]", value)
        self.assertIn("response=[redacted]", value)
        self.assertNotIn("secret payload", value)

    def test_hook_preserves_original_log_and_emits_enriched_event(self):
        original_calls = []
        emitted = []

        def original_log_event(db, action, voucher_id=None, details=None, created_at=None):
            original_calls.append((action, voucher_id, details, created_at))

        fake_module = types.SimpleNamespace(
            log_event=original_log_event,
            Voucher=FakeVoucher,
            _pakgat_ai_datahub_installed=False,
        )

        previous_send = datahub._send_async
        previous_health = datahub.emit_health
        try:
            datahub._send_async = lambda path, payload: emitted.append((path, payload))
            datahub.emit_health = lambda *args, **kwargs: None
            datahub.install_datahub_hooks(fake_module)
            fake_module.log_event(
                FakeDb(),
                "voucher_redeemed",
                7,
                "phone=0501234567; response=ok",
                datetime(2026, 8, 18, tzinfo=timezone.utc),
            )
        finally:
            datahub._send_async = previous_send
            datahub.emit_health = previous_health

        self.assertEqual(len(original_calls), 1)
        self.assertEqual(len(emitted), 1)
        path, payload = emitted[0]
        self.assertEqual(path, "/v1/events")
        self.assertEqual(payload["event_type"], "voucher_redeemed")
        self.assertEqual(payload["external_id"], "voucher:7:voucher_redeemed")
        self.assertEqual(payload["order_id"], "ORDER-123")
        self.assertEqual(payload["product_id"], "PRODUCT-9")
        self.assertEqual(payload["merchant"], "Test Merchant")
        self.assertEqual(payload["payload"]["voucher_status"], "redeemed")
        self.assertNotIn("0501234567", payload["payload"]["details"])


if __name__ == "__main__":
    unittest.main()
