import unittest
from types import SimpleNamespace

from app.jood_whatsapp_campaign import campaign_contact_allowed


class JoodWhatsAppCampaignTests(unittest.TestCase):
    def test_customer_campaign_targets_only_active_customers(self):
        customer = SimpleNamespace(contact_type="customer", status="active")
        merchant = SimpleNamespace(contact_type="merchant", status="active")
        blocked = SimpleNamespace(contact_type="customer", status="do_not_contact")
        self.assertTrue(campaign_contact_allowed(customer, "customer"))
        self.assertFalse(campaign_contact_allowed(merchant, "customer"))
        self.assertFalse(campaign_contact_allowed(blocked, "customer"))

    def test_merchant_campaign_targets_only_active_merchants(self):
        merchant = SimpleNamespace(contact_type="merchant", status="active")
        customer = SimpleNamespace(contact_type="customer", status="active")
        self.assertTrue(campaign_contact_allowed(merchant, "merchant"))
        self.assertFalse(campaign_contact_allowed(customer, "merchant"))


if __name__ == "__main__":
    unittest.main()
