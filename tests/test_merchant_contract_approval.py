import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine

from app import merchant_contracts as contracts
from app import merchant_finance as finance


class MerchantContractApprovalTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        finance.Merchant.__table__.create(self.engine)
        finance.MerchantContract.__table__.create(self.engine)
        contracts.ensure_merchant_contract_schema(self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_approval_audit_model_has_required_snapshot_fields(self):
        columns = contracts.MerchantContractApproval.__table__.c
        for name in (
            "merchant_contract_id",
            "merchant_id",
            "agreement_number_snapshot",
            "approved_at",
            "pakgat_signer_name",
            "pakgat_signer_title",
            "pakgat_signer_phone",
            "merchant_snapshot_json",
            "template_version",
        ):
            self.assertIn(name, columns)

    def test_pakgat_signer_constants_match_final_contract_identity(self):
        self.assertEqual(contracts.PAKGAT_CONTRACT_SIGNER_NAME, "بهاء السقا")
        self.assertEqual(contracts.PAKGAT_CONTRACT_SIGNER_TITLE, "مدير تطوير الأعمال")
        self.assertEqual(contracts.PAKGAT_CONTRACT_SIGNER_PHONE, "0504161514")


if __name__ == "__main__":
    unittest.main()
