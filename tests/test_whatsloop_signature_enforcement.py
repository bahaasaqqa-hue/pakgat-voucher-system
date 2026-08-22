import hashlib
import hmac

from app.whatsloop_security import request_signature_is_valid


def test_request_signature_enforcement():
    key = "test-key"
    raw = b'{"type":"message.received"}'
    signature = hmac.new(key.encode(), raw, hashlib.sha256).hexdigest()
    assert request_signature_is_valid(raw, {"x-webhook-signature": signature}, key)
    assert not request_signature_is_valid(raw, {}, key)
