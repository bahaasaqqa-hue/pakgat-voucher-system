import base64
import json
import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app import sadq_client


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, headers=None, body=None, timeout=20):
        self.calls.append((method, url, dict(headers or {}), body, timeout))
        return self.responses.pop(0)


class SadqSigningClientTests(unittest.TestCase):
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

    def test_initiate_base64_pdf_uses_verified_postman_shape_and_returns_ids(self):
        transport = FakeTransport([
            sadq_client.HttpResponse(200, b'{"access_token":"token","expires_in":3600}'),
            sadq_client.HttpResponse(
                200,
                b'{"data":{"documentId":"doc-123","envelopeId":"env-456","destinations":null},"errorCode":0,"message":"Success"}',
            ),
        ])
        client = sadq_client.SadqClient(self.config(), transport=transport, clock=lambda: 1000.0)
        pdf = b"%PDF-1.7\nPakgat test\n"

        result = client.initiate_base64_pdf(pdf, "PKG-MA-2026-08-0001.pdf")

        self.assertEqual(result.document_id, "doc-123")
        self.assertEqual(result.envelope_id, "env-456")
        method, url, headers, body, _timeout = transport.calls[1]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https://sandbox-api.sadq-sa.com/api/v1/envelopes/initiate-base64")
        self.assertEqual(headers["Authorization"], "Bearer token")
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(set(payload), {"File"})
        self.assertEqual(payload["File"]["FileName"], "PKG-MA-2026-08-0001.pdf")
        self.assertEqual(payload["File"]["File"], base64.b64encode(pdf).decode("ascii"))
        self.assertFalse(payload["File"]["hideEnvelopData"])

    def test_send_nafath_invitation_uses_v2_authentication_type_7(self):
        transport = FakeTransport([
            sadq_client.HttpResponse(200, b'{"access_token":"token","expires_in":3600}'),
            sadq_client.HttpResponse(
                200,
                b'{"data":{"invitationLink":"https://pakgat-sandbox.sadq.sa/sign/invite-789"},"errorCode":0,"message":"Success"}',
            ),
        ])
        client = sadq_client.SadqClient(self.config(), transport=transport, clock=lambda: 1000.0)

        result = client.send_nafath_invitation(
            "doc-123",
            destination_name="بهاء التجربة",
            destination_email="merchant@example.com",
            destination_phone="+966500000000",
            redirect_url="https://merchant.pakgat.com/merchant/onboarding",
            available_to="2026-09-07",
        )

        self.assertEqual(result.invitation_url, "https://pakgat-sandbox.sadq.sa/sign/invite-789")
        method, url, headers, body, _timeout = transport.calls[1]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https://sandbox-api.sadq-sa.com/api/v2/invitations/send")
        self.assertEqual(headers["Authorization"], "Bearer token")
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(payload["documentId"], "doc-123")
        self.assertEqual(len(payload["destinations"]), 1)
        destination = payload["destinations"][0]
        self.assertEqual(destination["destinationName"], "بهاء التجربة")
        self.assertEqual(destination["destinationEmail"], "merchant@example.com")
        self.assertEqual(destination["destinationPhoneNumber"], "+966500000000")
        self.assertEqual(destination["signeOrder"], 0)
        self.assertTrue(destination["ConsentOnly"])
        self.assertEqual(destination["signatories"], [])
        self.assertEqual(destination["authenticationType"], 7)
        self.assertEqual(destination["invitationLanguage"], 1)
        self.assertEqual(destination["redirectUrl"], "https://merchant.pakgat.com/merchant/onboarding")
        self.assertEqual(destination["availableTo"], "2026-09-07")


if __name__ == "__main__":
    unittest.main()
