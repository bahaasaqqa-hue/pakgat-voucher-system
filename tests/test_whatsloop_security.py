from app.whatsloop_security import (
    current_webhook_token,
    legacy_webhook_token,
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
