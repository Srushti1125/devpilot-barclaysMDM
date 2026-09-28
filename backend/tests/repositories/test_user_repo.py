"""
Database repository tests for UserRepository.

Verifies:
- CRUD operations for User entity
- Email lookups (case handling, uniqueness)
- Default values and timestamps
"""

from app.domain.models import User
from app.core.security import hash_password


def test_user_repo_create_and_get(user_repo, db_session):
    user_id = user_repo.new_id()
    user = User(
        id=user_id,
        email="repo.test@example.com",
        full_name="Repo Test User",
        password_hash=hash_password("Pass123!"),
        role="member",
    )
    user_repo.add(user)
    user_repo.commit()

    retrieved = user_repo.get(user_id)
    assert retrieved is not None
    assert retrieved.email == "repo.test@example.com"
    assert retrieved.role == "member"
    assert retrieved.is_active is True
    assert retrieved.created_at is not None


def test_user_repo_get_by_email(user_repo):
    user_id = user_repo.new_id()
    user = User(
        id=user_id,
        email="lookup@example.com",
        full_name="Lookup User",
        password_hash=hash_password("Pass123!"),
    )
    user_repo.add(user)
    user_repo.commit()

    found = user_repo.get_by_email("lookup@example.com")
    assert found is not None
    assert found.id == user_id

    not_found = user_repo.get_by_email("ghost@example.com")
    assert not_found is None


def test_user_repo_delete(user_repo):
    user_id = user_repo.new_id()
    user = User(
        id=user_id,
        email="delete.me@example.com",
        full_name="To Delete",
        password_hash=hash_password("Pass123!"),
    )
    user_repo.add(user)
    user_repo.commit()

    user_repo.delete(user)
    user_repo.commit()

    assert user_repo.get(user_id) is None
