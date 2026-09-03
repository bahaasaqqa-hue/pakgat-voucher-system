import importlib.util
import os
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("MERCHANT_PORTAL_SECRET", "test-only-merchant-portal-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from starlette.requests import Request

from app import application as core
from app import merchant_finance as finance
from app import merchant_portal as portal


class MerchantPortalEntryTests(unittest.TestCase):
    def test_merchant_portal_module_exists_and_routes_are_registered(self):
        self.assertIsNotNone(importlib.util.find_spec("app.merchant_portal"))
        paths = {
            (getattr(route, "path", ""), method)
            for route in core.app.routes
            for method in (getattr(route, "methods", set()) or set())
        }
        self.assertIn(("/merchant", "GET"), paths)
        self.assertIn(("/merchant/login/request", "POST"), paths)
        self.assertIn(("/merchant/login/verify", "POST"), paths)
        self.assertIn(("/merchant/dashboard", "GET"), paths)
        self.assertIn(("/merchant/logout", "POST"), paths)

    def test_main_registers_merchant_portal_module(self):
        source = Path("main.py").read_text(encoding="utf-8")
        self.assertIn("merchant_portal", source)


class MerchantPortalSecurityTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        finance.Merchant.__table__.create(self.engine)
        finance.MerchantContract.__table__.create(self.engine)
        finance.MerchantProductLink.__table__.create(self.engine)
        self.db = Session(self.engine)
        self.merchant = finance.Merchant(
            code="PKG-M-PORTAL",
            display_name="Portal Merchant",
            legal_name="Portal Merchant LLC",
            contact_phone="0500000000",
            status="pending",
        )
        self.db.add(self.merchant)
        self.db.flush()
        self.contract = finance.MerchantContract(
            merchant_id=self.merchant.id,
            agreement_number="PKG-MA-2026-08-0100",
            status="signed",
            signed_at=core.now_utc(),
        )
        self.product = finance.MerchantProductLink(
            merchant_id=self.merchant.id,
            product_id="prod-portal-1",
            sku="PORTAL-SKU-1",
            product_name_snapshot="بوكس تجربة التاجر",
            product_status="active",
        )
        self.db.add_all([self.contract, self.product])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _ensure_portal_table(self):
        self.assertTrue(hasattr(portal, "MerchantPortalOtpChallenge"))
        portal.MerchantPortalOtpChallenge.__table__.create(self.engine, checkfirst=True)

    def _request(self, path: str, cookie: str = ""):
        headers = []
        if cookie:
            headers.append((b"cookie", f"pakgat_merchant={cookie}".encode("utf-8")))
        return Request(
            {
                "type": "http",
                "method": "GET",
                "path": path,
                "headers": headers,
                "query_string": b"",
                "scheme": "https",
                "server": ("pakgat.com", 443),
                "client": ("127.0.0.1", 12345),
            }
        )

    def test_known_merchant_otp_is_sent_and_only_hash_is_stored(self):
        self._ensure_portal_table()
        self.assertTrue(hasattr(portal, "request_merchant_otp"))
        with patch.object(portal.secrets, "randbelow", return_value=123456), patch.object(
            portal, "_send_whatsloop_text", return_value=(True, "HTTP 200")
        ) as send:
            challenge_token, delivered = portal.request_merchant_otp(self.db, "0500000000")
        self.assertTrue(delivered)
        self.assertTrue(challenge_token)
        send.assert_called_once()
        sent_phone, sent_message = send.call_args.args
        self.assertEqual(sent_phone, "966500000000")
        self.assertIn("123456", sent_message)
        row = self.db.query(portal.MerchantPortalOtpChallenge).one()
        self.assertNotEqual(row.otp_hash, "123456")
        self.assertNotIn("123456", row.otp_hash)
        self.assertEqual(row.destination, "966500000000")
        self.assertEqual(row.status, "pending")

    def test_unknown_phone_is_generic_and_never_creates_merchant(self):
        self._ensure_portal_table()
        self.assertTrue(hasattr(portal, "request_merchant_otp"))
        before = self.db.query(finance.Merchant).count()
        with patch.object(portal, "_send_whatsloop_text", return_value=(True, "HTTP 200")) as send:
            challenge_token, delivered = portal.request_merchant_otp(self.db, "0555555555")
        self.assertIsNone(challenge_token)
        self.assertFalse(delivered)
        send.assert_not_called()
        self.assertEqual(self.db.query(finance.Merchant).count(), before)

    def test_resend_within_sixty_seconds_does_not_send_twice(self):
        self._ensure_portal_table()
        self.assertTrue(hasattr(portal, "request_merchant_otp"))
        with patch.object(portal.secrets, "randbelow", return_value=123456), patch.object(
            portal, "_send_whatsloop_text", return_value=(True, "HTTP 200")
        ) as send:
            first_token, first_delivered = portal.request_merchant_otp(self.db, "0500000000")
            second_token, second_delivered = portal.request_merchant_otp(self.db, "0500000000")
        self.assertTrue(first_delivered)
        self.assertFalse(second_delivered)
        self.assertEqual(second_token, first_token)
        send.assert_called_once()
        self.assertEqual(self.db.query(portal.MerchantPortalOtpChallenge).count(), 1)

    def test_correct_otp_marks_challenge_used(self):
        self._ensure_portal_table()
        self.assertTrue(hasattr(portal, "request_merchant_otp"))
        self.assertTrue(hasattr(portal, "verify_merchant_otp"))
        with patch.object(portal.secrets, "randbelow", return_value=123456), patch.object(
            portal, "_send_whatsloop_text", return_value=(True, "HTTP 200")
        ):
            token, _ = portal.request_merchant_otp(self.db, "0500000000")
        merchant_id = portal.verify_merchant_otp(self.db, token, "123456")
        self.assertEqual(merchant_id, self.merchant.id)
        row = self.db.query(portal.MerchantPortalOtpChallenge).one()
        self.assertEqual(row.status, "used")
        self.assertIsNotNone(row.used_at)
        self.assertIsNone(portal.verify_merchant_otp(self.db, token, "123456"))

    def test_five_wrong_attempts_block_even_correct_code(self):
        self._ensure_portal_table()
        self.assertTrue(hasattr(portal, "request_merchant_otp"))
        self.assertTrue(hasattr(portal, "verify_merchant_otp"))
        with patch.object(portal.secrets, "randbelow", return_value=123456), patch.object(
            portal, "_send_whatsloop_text", return_value=(True, "HTTP 200")
        ):
            token, _ = portal.request_merchant_otp(self.db, "0500000000")
        for _ in range(5):
            self.assertIsNone(portal.verify_merchant_otp(self.db, token, "000000"))
        row = self.db.query(portal.MerchantPortalOtpChallenge).one()
        self.assertEqual(row.attempt_count, 5)
        self.assertEqual(row.status, "failed")
        self.assertIsNone(portal.verify_merchant_otp(self.db, token, "123456"))

    def test_expired_challenge_cannot_authenticate(self):
        self._ensure_portal_table()
        self.assertTrue(hasattr(portal, "request_merchant_otp"))
        self.assertTrue(hasattr(portal, "verify_merchant_otp"))
        with patch.object(portal.secrets, "randbelow", return_value=123456), patch.object(
            portal, "_send_whatsloop_text", return_value=(True, "HTTP 200")
        ):
            token, _ = portal.request_merchant_otp(self.db, "0500000000")
        row = self.db.query(portal.MerchantPortalOtpChallenge).one()
        row.expires_at = core.now_utc() - timedelta(seconds=1)
        self.db.commit()
        self.assertIsNone(portal.verify_merchant_otp(self.db, token, "123456"))
        self.db.refresh(row)
        self.assertEqual(row.status, "expired")

    def test_session_token_rejects_tampering(self):
        self.assertTrue(hasattr(portal, "merchant_session_token"))
        self.assertTrue(hasattr(portal, "valid_merchant_session"))
        expires = int((core.now_utc() + timedelta(days=14)).timestamp())
        token = portal.merchant_session_token(self.merchant.id, expires)
        self.assertEqual(portal.valid_merchant_session(token), self.merchant.id)
        self.assertIsNone(portal.valid_merchant_session(token + "x"))

    def test_dashboard_renders_only_authenticated_merchant_data(self):
        self.assertTrue(hasattr(portal, "merchant_session_token"))
        expires = int((core.now_utc() + timedelta(days=14)).timestamp())
        token = portal.merchant_session_token(self.merchant.id, expires)
        response = portal.merchant_portal_dashboard(
            self._request("/merchant/dashboard", token),
            self.db,
        )
        html = response.body.decode("utf-8")
        self.assertIn("Portal Merchant", html)
        self.assertIn("PKG-MA-2026-08-0100", html)
        self.assertIn("بوكس تجربة التاجر", html)
        self.assertNotIn("الملاحظات الداخلية", html)

        other = finance.Merchant(
            code="PKG-M-OTHER",
            display_name="Other Merchant Secret",
            contact_phone="0511111111",
            status="active",
        )
        self.db.add(other)
        self.db.commit()
        self.assertNotIn("Other Merchant Secret", html)

    def test_suspended_merchant_is_denied_with_existing_session(self):
        self.assertTrue(hasattr(portal, "merchant_session_token"))
        expires = int((core.now_utc() + timedelta(days=14)).timestamp())
        token = portal.merchant_session_token(self.merchant.id, expires)
        self.merchant.status = "suspended"
        self.db.commit()
        response = portal.merchant_portal_dashboard(
            self._request("/merchant/dashboard", token),
            self.db,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/merchant")

    def test_logout_clears_merchant_cookie(self):
        response = portal.merchant_portal_logout(self._request("/merchant/logout"))
        self.assertEqual(response.status_code, 303)
        cookie = response.headers.get("set-cookie", "")
        self.assertIn("pakgat_merchant=", cookie)
        self.assertIn("Max-Age=0", cookie)
        self.assertIn("Path=/merchant", cookie)


if __name__ == "__main__":
    unittest.main()
