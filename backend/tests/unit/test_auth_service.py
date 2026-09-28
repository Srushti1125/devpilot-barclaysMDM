"""
Unit tests for AuthService business logic.

Verifies:
- User registration with unique email, hashed password, and default role
- Duplicate email rejection with ConflictError
- Login authentication with valid and invalid credentials
- Password verification via pwdlib
- Audit logging for register and login events
"""

import pytest
from app.core.exceptions import AuthenticationError, ConflictError
from app.core.security import verify_password


def test_register_new_user_success(auth_service, user_repo, audit_repo):
    user = auth_service.register(
        email="john.doe@example.com",
        full_name="John Doe",
        password="SecurePassword123!",
    )

    assert user.id is not None
    assert user.email == "john.doe@example.com"
    assert user.full_name == "John Doe"
    assert user.role == "member"
    assert user.password_hash != "SecurePassword123!"
    assert verify_password("SecurePassword123!", user.password_hash)

    # Verify audit record
    logs = audit_repo.list_recent(limit=10)
    assert any(log.action == "user.register" and log.user_id == user.id for log in logs)


def test_register_duplicate_email_raises_conflict(auth_service):
    auth_service.register("alice@example.com", "Alice Smith", "Password123!")

    with pytest.raises(ConflictError) as exc_info:
        auth_service.register("alice@example.com", "Alice Duplicate", "Password123!")

    assert "already registered" in str(exc_info.value).lower()


def test_register_normalizes_email_to_lowercase(auth_service):
    user = auth_service.register("BOB@EXAMPLE.COM", "Bob Builder", "Password123!")
    assert user.email == "bob@example.com"

    with pytest.raises(ConflictError):
        auth_service.register("bob@example.com", "Bob Again", "Password123!")


def test_login_success_returns_jwt_token(auth_service, audit_repo):
    auth_service.register("charlie@example.com", "Charlie Brown", "SecretPass123!")

    token = auth_service.login("charlie@example.com", "SecretPass123!")
    assert isinstance(token, str)
    assert len(token) > 20

    # Verify audit record
    logs = audit_repo.list_recent(limit=10)
    assert any(log.action == "auth.login" for log in logs)


def test_login_incorrect_password_raises_authentication_error(auth_service):
    auth_service.register("diana@example.com", "Diana Prince", "CorrectPass123!")

    with pytest.raises(AuthenticationError) as exc_info:
        auth_service.login("diana@example.com", "WrongPassword!")

    assert "incorrect email or password" in str(exc_info.value).lower()


def test_login_nonexistent_user_raises_authentication_error(auth_service):
    with pytest.raises(AuthenticationError) as exc_info:
        auth_service.login("ghost@example.com", "AnyPassword123!")

    assert "incorrect email or password" in str(exc_info.value).lower()
