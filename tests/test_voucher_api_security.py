import asyncio
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from starlette.requests import Request
from starlette.responses import JSONResponse

from app import merchant_finance_hooks as hooks


class VoucherAPISecurityTests(unittest.TestCase):
    def _request(self, secret=""):
        headers = []
        if secret:
            headers.append((b"x-pakgat-voucher-secret", secret.encode("utf-8")))
        return Request({
            "type": "http",
            "method": "POST",
            "path": "/api/vouchers",
            "headers": headers,
            "query_string": b"",
            "scheme": "https",
            "server": ("example.test", 443),
            "client": ("127.0.0.1", 12345),
        })

    def test_missing_secret_is_rejected(self):
        async def next_handler(request):
            return JSONResponse({"ok": True})
        with patch.object(hooks, "VOUCHER_API_SECRET", "strong-secret"):
            response = asyncio.run(hooks._protect_voucher_creation_api(self._request(), next_handler))
        self.assertEqual(response.status_code, 401)

    def test_wrong_secret_is_rejected(self):
        async def next_handler(request):
            return JSONResponse({"ok": True})
        with patch.object(hooks, "VOUCHER_API_SECRET", "strong-secret"):
            response = asyncio.run(hooks._protect_voucher_creation_api(self._request("wrong"), next_handler))
        self.assertEqual(response.status_code, 401)

    def test_correct_secret_passes_without_changing_the_route(self):
        async def next_handler(request):
            return JSONResponse({"ok": True, "path": request.url.path})
        with patch.object(hooks, "VOUCHER_API_SECRET", "strong-secret"):
            response = asyncio.run(hooks._protect_voucher_creation_api(self._request("strong-secret"), next_handler))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'"path":"/api/vouchers"', response.body)

    def test_salla_webhook_is_not_intercepted_by_voucher_api_guard(self):
        async def next_handler(request):
            return JSONResponse({"ok": True})
        request = Request({
            "type": "http",
            "method": "POST",
            "path": "/webhooks/salla",
            "headers": [],
            "query_string": b"",
            "scheme": "https",
            "server": ("example.test", 443),
            "client": ("127.0.0.1", 12345),
        })
        with patch.object(hooks, "VOUCHER_API_SECRET", "strong-secret"):
            response = asyncio.run(hooks._protect_voucher_creation_api(request, next_handler))
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
