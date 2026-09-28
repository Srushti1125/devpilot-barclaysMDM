"""
Authentication & user-registration business logic.

Owns password hashing, token creation, and user-existence checks.
Raises domain exceptions – never touches FastAPI directly.
"""

from app.core.exceptions import AuthenticationError, ConflictError
from app.core.security import create_access_token, hash_password, verify_password
from app.domain.models import User
from app.repositories.audit_repo import AuditRepository
from app.repositories.user_repo import UserRepository


class AuthService:
    def __init__(self, user_repo: UserRepository, audit_repo: AuditRepository):
        self.user_repo = user_repo
        self.audit_repo = audit_repo

    def register(self, email: str, full_name: str, password: str) -> User:
        email = email.lower()
        if self.user_repo.get_by_email(email):
            raise ConflictError("Email already registered")

        user = User(
            id=self.user_repo.new_id(),
            email=email,
            full_name=full_name.strip(),
            password_hash=hash_password(password),
            role="member",
        )
        self.user_repo.add(user)
        self.user_repo.flush()
        self.audit_repo.record(user.id, "user.register", "user", user.id)
        self.user_repo.commit()
        self.user_repo.refresh(user)
        return user

    def login(self, email: str, password: str) -> str:
        """Authenticate and return a JWT access token."""
        user = self.user_repo.get_by_email(email.lower())
        if not user or not verify_password(password, user.password_hash):
            raise AuthenticationError("Incorrect email or password")

        self.audit_repo.record(user.id, "auth.login", "user", user.id)
        self.user_repo.commit()
        return create_access_token(user.id)
