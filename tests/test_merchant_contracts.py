import os
import unittest
from datetime import datetime, timezone

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import application as core
from app import merchant_finance as finance


class MerchantContractStorageTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        core.Voucher.__table__.create(self.engine)
        core.AuditLog.__table__.create(self.engine)
        for table in finance.FINANCE_TABLES:
            table.create(self.engine)
        self.db = Session(self.engine)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_merchant_contract_has_agreement_number_column(self):
        self.assertIn("agreement_number", finance.MerchantContract.__table__.c)

    def test_delivery_model_is_registered(self):
        self.assertTrue(hasattr(finance, "MerchantContractDelivery"))

    def test_agreement_number_generator_is_available(self):
        self.assertTrue(callable(getattr(finance, "next_agreement_number", None)))

    def test_agreement_number_format_uses_riyadh_year_month(self):
        number = finance.next_agreement_number(
            self.db,
            datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc),
        )
        self.assertRegex(number, r"^PKG-MA-2026-08-\d{4}$")

    def test_agreement_number_sequence_advances_within_month(self):
        merchant = finance.Merchant(code="PKG-M-TEST01", display_name="Test Merchant")
        self.db.add(merchant)
        self.db.flush()
        self.db.add(
            finance.MerchantContract(
                merchant_id=merchant.id,
                agreement_number="PKG-MA-2026-08-0007",
                status="draft",
            )
        )
        self.db.commit()
        number = finance.next_agreement_number(
            self.db,
            datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(number, "PKG-MA-2026-08-0008")

    def test_delivery_is_unique_per_contract_and_channel(self):
        merchant = finance.Merchant(code="PKG-M-TEST02", display_name="Delivery Merchant")
        self.db.add(merchant)
        self.db.flush()
        contract = finance.MerchantContract(merchant_id=merchant.id, status="signed")
        self.db.add(contract)
        self.db.flush()
        self.db.add(
            finance.MerchantContractDelivery(
                merchant_contract_id=contract.id,
                merchant_id=merchant.id,
                channel="whatsapp",
                destination="966500000000",
                status="pending",
            )
        )
        self.db.commit()
        self.db.add(
            finance.MerchantContractDelivery(
                merchant_contract_id=contract.id,
                merchant_id=merchant.id,
                channel="whatsapp",
                destination="966500000000",
                status="pending",
            )
        )
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

    def test_existing_contract_table_is_upgraded_additively(self):
        legacy_engine = create_engine("sqlite:///:memory:")
        try:
            with legacy_engine.begin() as conn:
                conn.execute(text("""
                    CREATE TABLE merchant_contracts (
                        id INTEGER PRIMARY KEY,
                        merchant_id INTEGER NOT NULL,
                        status VARCHAR(40),
                        sadq_document_id VARCHAR(255),
                        sadq_transaction_id VARCHAR(255),
                        signed_document_url VARCHAR(1000),
                        signed_at DATETIME,
                        created_at DATETIME,
                        updated_at DATETIME
                    )
                """))
            finance.ensure_merchant_contract_schema(legacy_engine)
            columns = {column["name"] for column in inspect(legacy_engine).get_columns("merchant_contracts")}
            self.assertIn("agreement_number", columns)
            tables = set(inspect(legacy_engine).get_table_names())
            self.assertIn("merchant_contract_deliveries", tables)
        finally:
            legacy_engine.dispose()


if __name__ == "__main__":
    unittest.main()
