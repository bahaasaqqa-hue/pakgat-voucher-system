import io
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import sadq_sandbox_smoke as smoke


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, headers=None, body=None, timeout=20):
        self.calls.append((method, url, dict(headers or {}), body))
        return self.responses.pop(0)


class SadqSandboxSmokeTests(unittest.TestCase):
    def config(self):
        return smoke.SmokeConfig(
            base_url="https://sandbox-api.sadq-sa.com",
            client_id="client-id",
            client_secret="client-secret",
            username="user@example.com",
            password="integration-password",
            account_id="account-id",
            account_secret="account-secret",
            callback_url="https://voucher.pakgat.com/integrations/sadq/webhook",
        )

    def test_auth_and_webhook_get_use_correct_shapes_without_leaking_secrets(self):
        transport = FakeTransport(
            [
                smoke.HttpResponse(
                    200,
                    json.dumps(
                        {
                            "access_token": "very-secret-access-token",
                            "expires_in": 100,
                            "token_type": "Bearer",
                        }
                    ).encode(),
                ),
                smoke.HttpResponse(
                    200,
                    json.dumps(
                        {
                            "data": [
                                {
                                    "id": "webhook-id",
                                    "webhookUrl": "https://voucher.pakgat.com/integrations/sadq/webhook",
                                    "isDefault": True,
                                }
                            ],
                            "errorCode": 0,
                        }
                    ).encode(),
                ),
                smoke.HttpResponse(403, b'{"detail":"Invalid Sadq webhook token"}'),
            ]
        )
        out = io.StringIO()

        result = smoke.run_read_only(self.config(), transport=transport, out=out)

        self.assertTrue(result.api_ok)
        self.assertTrue(result.callback_registered)
        self.assertEqual(result.callback_probe_status, 403)
        self.assertTrue(result.ready_for_e2e)

        auth_call = transport.calls[0]
        self.assertEqual(auth_call[0], "POST")
        self.assertTrue(auth_call[1].endswith("/Authentication/Authority/Token"))
        self.assertTrue(auth_call[2]["Authorization"].startswith("Basic "))
        self.assertIn(b"grant_type=integration", auth_call[3])
        self.assertIn(b"accountId=account-id", auth_call[3])
        self.assertIn(b"accountSecret=account-secret", auth_call[3])

        webhook_call = transport.calls[1]
        self.assertEqual(webhook_call[0], "GET")
        self.assertTrue(webhook_call[1].endswith("/api/v1/webhooks"))
        self.assertEqual(
            webhook_call[2]["Authorization"], "Bearer very-secret-access-token"
        )

        callback_call = transport.calls[2]
        self.assertEqual(callback_call[0], "POST")
        self.assertEqual(callback_call[1], self.config().callback_url)
        self.assertNotIn("Authorization", callback_call[2])

        rendered = out.getvalue()
        for secret in (
            "client-secret",
            "integration-password",
            "account-secret",
            "very-secret-access-token",
        ):
            self.assertNotIn(secret, rendered)
        self.assertIn("SADQ_AUTH_OK", rendered)
        self.assertIn("SADQ_BEARER_API_OK", rendered)
        self.assertIn("SADQ_CALLBACK_REGISTERED", rendered)
        self.assertIn("PAKGAT_CALLBACK_REACHABLE_AND_PROTECTED", rendered)
        self.assertIn("SADQ_INTEGRATION_READY_FOR_E2E", rendered)

    def test_reachable_callback_with_missing_webhook_token_is_reported_not_ready(self):
        transport = FakeTransport(
            [
                smoke.HttpResponse(200, b'{"access_token":"token"}'),
                smoke.HttpResponse(200, b'{"data":[],"errorCode":0}'),
                smoke.HttpResponse(
                    503,
                    b'{"detail":"Sadq webhook authentication is not configured"}',
                ),
            ]
        )
        out = io.StringIO()

        result = smoke.run_read_only(self.config(), transport=transport, out=out)

        self.assertTrue(result.api_ok)
        self.assertFalse(result.callback_registered)
        self.assertEqual(result.callback_probe_status, 503)
        self.assertFalse(result.ready_for_e2e)
        self.assertIn("SADQ_CALLBACK_NOT_REGISTERED", out.getvalue())
        self.assertIn(
            "PAKGAT_CALLBACK_REACHABLE_BUT_TOKEN_NOT_CONFIGURED", out.getvalue()
        )
        self.assertIn("SADQ_READ_ONLY_API_OK", out.getvalue())

    def test_missing_access_token_reports_safe_provider_error_without_leaking_secrets(self):
        response = {
            "access_token": None,
            "error": "invalid_grant",
            "errorMessage": "Invalid credentials for integration-password / account-secret",
            "message": None,
            "stateValidationErrors": None,
        }
        transport = FakeTransport(
            [smoke.HttpResponse(200, json.dumps(response).encode())]
        )
        out = io.StringIO()

        with self.assertRaises(smoke.SmokeError):
            smoke.run_read_only(self.config(), transport=transport, out=out)

        rendered = out.getvalue()
        self.assertIn("SADQ_AUTH_RESPONSE_KEYS=", rendered)
        self.assertIn("SADQ_AUTH_PROVIDER_ERROR=invalid_grant", rendered)
        self.assertIn("SADQ_AUTH_PROVIDER_MESSAGE=Invalid credentials for [REDACTED] / [REDACTED]", rendered)
        self.assertNotIn("integration-password", rendered)
        self.assertNotIn("account-secret", rendered)
        self.assertNotIn("client-secret", rendered)


if __name__ == "__main__":
    unittest.main()
