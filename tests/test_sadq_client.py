import base64
import json
import os
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app import sadq_client


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, headers=None, body=None, timeout=20):
        self.calls.append((method, url, dict(headers or {}), body, timeout))
        return self.responses.pop(0)


class SadqDynamicAuthTests(unittest.TestCase):
    def config(self):
        return sadq_client.SadqConfig(
            base_url="https://sandbox-api.sadq-sa.com",
            client_id="Integrationclient",
            client_secret="basic-secret",
            username="merchant@example.com",
            password="integration-password",
            account_id="account-id",
            account_secret="account-secret",
            webhook_url="https://voucher.pakgat.com/integrations/sadq/webhook",
            webhook_token="pakgat-webhook-secret",
        )

    def test_get_access_token_uses_basic_auth_and_integration_form(self):
        transport = FakeTransport([
            sadq_client.HttpResponse(
                200,
                json.dumps({"access_token": "dynamic-token", "expires_in": 3600}).encode(),
            )
        ])
        client = sadq_client.SadqClient(self.config(), transport=transport, clock=lambda: 1000.0)

        token = client.get_access_token()

        self.assertEqual(token, "dynamic-token")
        method, url, headers, body, _timeout = transport.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https://sandbox-api.sadq-sa.com/Authentication/Authority/Token")
        expected_basic = base64.b64encode(b"Integrationclient:basic-secret").decode("ascii")
        self.assertEqual(headers["Authorization"], f"Basic {expected_basic}")
        form = parse_qs(body.decode("utf-8"))
        self.assertEqual(form["grant_type"], ["integration"])
        self.assertEqual(form["username"], ["merchant@example.com"])
        self.assertEqual(form["password"], ["integration-password"])
        self.assertEqual(form["accountId"], ["account-id"])
        self.assertEqual(form["accountSecret"], ["account-secret"])

    def test_access_token_is_cached_until_refresh_window(self):
        now = [1000.0]
        transport = FakeTransport([
            sadq_client.HttpResponse(200, b'{"access_token":"token-1","expires_in":3600}'),
            sadq_client.HttpResponse(200, b'{"access_token":"token-2","expires_in":3600}'),
        ])
        client = sadq_client.SadqClient(self.config(), transport=transport, clock=lambda: now[0])

        self.assertEqual(client.get_access_token(), "token-1")
        now[0] = 1200.0
        self.assertEqual(client.get_access_token(), "token-1")
        self.assertEqual(len(transport.calls), 1)
        now[0] = 4500.0
        self.assertEqual(client.get_access_token(), "token-2")
        self.assertEqual(len(transport.calls), 2)

    def test_ensure_webhook_registers_callback_with_header_token_once(self):
        transport = FakeTransport([
            sadq_client.HttpResponse(200, b'{"access_token":"token","expires_in":3600}'),
            sadq_client.HttpResponse(200, b'{"data":[],"errorCode":0}'),
            sadq_client.HttpResponse(
                200,
                b'{"data":{"id":"webhook-id","webhookUrl":"https://voucher.pakgat.com/integrations/sadq/webhook","isDefault":true},"errorCode":0}',
            ),
        ])
        client = sadq_client.SadqClient(self.config(), transport=transport, clock=lambda: 1000.0)

        result = client.ensure_webhook()

        self.assertEqual(result["id"], "webhook-id")
        self.assertEqual(len(transport.calls), 3)
        method, url, headers, body, _timeout = transport.calls[2]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https://sandbox-api.sadq-sa.com/api/v1/webhooks")
        self.assertEqual(headers["Authorization"], "Bearer token")
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(payload["webhookUrl"], self.config().webhook_url)
        self.assertTrue(payload["isDefault"])
        self.assertEqual(payload["HeaderToken"], "pakgat-webhook-secret")

    def test_ensure_webhook_is_idempotent_when_callback_already_exists(self):
        transport = FakeTransport([
            sadq_client.HttpResponse(200, b'{"access_token":"token","expires_in":3600}'),
            sadq_client.HttpResponse(
                200,
                b'{"data":[{"id":"existing","webhookUrl":"https://voucher.pakgat.com/integrations/sadq/webhook","isDefault":true}],"errorCode":0}',
            ),
        ])
        client = sadq_client.SadqClient(self.config(), transport=transport, clock=lambda: 1000.0)

        result = client.ensure_webhook()

        self.assertEqual(result["id"], "existing")
        self.assertEqual(len(transport.calls), 2)

    def test_config_from_env_requires_dynamic_credentials_and_webhook_secret(self):
        values = {
            "SADQ_API_BASE_URL": "https://sandbox-api.sadq-sa.com",
            "SADQ_CLIENT_ID": "Integrationclient",
            "SADQ_CLIENT_SECRET": "basic-secret",
            "SADQ_USERNAME": "merchant@example.com",
            "SADQ_PASSWORD": "integration-password",
            "SADQ_ACCOUNT_ID": "account-id",
            "SADQ_ACCOUNT_SECRET": "account-secret",
            "SADQ_WEBHOOK_URL": "https://voucher.pakgat.com/integrations/sadq/webhook",
            "SADQ_WEBHOOK_TOKEN": "pakgat-webhook-secret",
        }
        with patch.dict(os.environ, values, clear=False):
            cfg = sadq_client.SadqConfig.from_env()
        self.assertEqual(cfg.client_id, "Integrationclient")
        self.assertEqual(cfg.webhook_token, "pakgat-webhook-secret")


if __name__ == "__main__":
    unittest.main()
