from app.whatsloop_security import (
    current_webhook_token,
    legacy_webhook_token,
    signature_header_metadata,
    webhook_token_is_valid,
)


def test_webhook_token_rotation_accepts_current_and_legacy_during_transition():
    secret = "admin-secret"
    current = current_webhook_token(secret)
    legacy = legacy_webhook_token(secret)
    assert current != legacy
    assert len(current) == 64
    assert len(legacy) == 64
    assert webhook_token_is_valid(current, secret)
    assert webhook_token_is_valid(legacy, secret)
    assert not webhook_token_is_valid("bad-token", secret)


def test_signature_header_metadata_only_exposes_candidate_name_and_shape():
    headers = {
        "content-type": "application/json",
        "x-whatsloop-signature": "sha256=abcdef0123456789",
        "x-request-id": "req_123",
        "authorization": "Bearer secret",
    }
    metadata = signature_header_metadata(headers)
    assert metadata == ["x-whatsloop-signature(len=23,prefix=sha256=)"]
    assert "secret" not in " ".join(metadata)
    assert "abcdef" not in " ".join(metadata)
