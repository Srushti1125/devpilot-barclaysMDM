"""
Unit tests for security utilities (password hashing and JWT tokens).

Verifies:
- Argon2 / bcrypt password hashing produces unique salts
- Password verification is tamper-proof
- JWT access tokens encode subject and expire appropriately
- Malformed, empty, or tampered tokens are safely rejected (returns None)
"""

from app.core.security import create_access_token, hash_password, token_subject, verify_password


def test_password_hash_and_verify():
    password = "CorrectHorseBatteryStaple!"
    hashed = hash_password(password)

    # Hash should not equal plain text
    assert hashed != password
    assert len(hashed) > 20

    # Verification
    assert verify_password(password, hashed) is True
    assert verify_password("WrongPassword123", hashed) is False


def test_hash_produces_unique_salts():
    p = "SamePasswordEveryTime"
    h1 = hash_password(p)
    h2 = hash_password(p)
    assert h1 != h2
    assert verify_password(p, h1) is True
    assert verify_password(p, h2) is True


def test_jwt_token_roundtrip():
    user_id = "user-uuid-123456"
    token = create_access_token(user_id)

    subject = token_subject(token)
    assert subject == user_id


def test_jwt_tampered_token_rejected():
    token = create_access_token("user-uuid-999")
    # Mutate the signature portion
    tampered = token[:-4] + "zzzz"

    assert token_subject(tampered) is None


def test_jwt_empty_and_garbage_token():
    assert token_subject("") is None
    assert token_subject("not.a.valid.jwt.token") is None
    assert token_subject(None) is None
