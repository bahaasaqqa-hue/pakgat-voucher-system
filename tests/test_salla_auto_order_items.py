import unittest

from app.salla_data import _payload_with_order_items


class SallaAutoOrderItemsTests(unittest.TestCase):
    def test_enriches_order_event_from_items_api_list(self):
        payload = {
            "event": "order.updated",
            "merchant": {"id": "650097422"},
            "data": {"id": "123", "status": {"slug": "closed"}},
        }
        items_payload = {
            "status": 200,
            "success": True,
            "data": [
                {"id": 9, "name": "كوبون غسيل", "sku": "PKG-QR-9", "quantity": 2}
            ],
        }

        enriched = _payload_with_order_items(payload, items_payload)

        self.assertIsNotNone(enriched)
        self.assertEqual(enriched["data"]["items"][0]["sku"], "PKG-QR-9")
        self.assertNotIn("items", payload["data"])

    def test_accepts_nested_items_response(self):
        payload = {"event": "order.updated", "data": {"id": "123"}}
        items_payload = {"data": {"items": [{"id": 2, "name": "عرض", "quantity": 1}]}}

        enriched = _payload_with_order_items(payload, items_payload)

        self.assertEqual(len(enriched["data"]["items"]), 1)

    def test_empty_items_response_does_not_replace_existing_event(self):
        payload = {"event": "order.updated", "data": {"id": "123"}}

        self.assertIsNone(_payload_with_order_items(payload, {"data": []}))
        self.assertIsNone(_payload_with_order_items(payload, {"data": {"items": []}}))


if __name__ == "__main__":
    unittest.main()
