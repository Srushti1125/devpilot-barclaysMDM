"""
Global pytest fixtures for DevPilot backend tests.

Provides:
- In-memory SQLite database isolation with StaticPool
- FastAPI TestClient with dependency overrides
- Role-based user factory (Admin, PM, BA, Developer, Tester)
- Pre-authenticated headers for each role
- Service and Repository instances wired to the test session
- AI Engine mock helpers
"""

import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import User, Project, ProjectMember
from app.security import hash_password, create_access_token
from app.services.ai_engine import AIEngineClient
from app.repositories.user_repo import UserRepository
from app.repositories.project_repo import ProjectRepository
from app.repositories.requirement_repo import RequirementRepository
from app.repositories.artifact_repo import ArtifactRepository
from app.repositories.audit_repo import AuditRepository
from app.services.auth_service import AuthService
from app.services.project_service import ProjectService
from app.services.artifact_service import ArtifactService


# In-memory SQLite database for test speed and complete isolation
test_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)


@pytest.fixture(autouse=True)
def setup_database():
    """Ensure a clean database schema before each test."""
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def db_session():
    """Direct database session for repository/service unit tests."""
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    """FastAPI TestClient with get_db overridden to use test database."""
    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# ── Repository Fixtures ───────────────────────────────────────────────────────

@pytest.fixture
def user_repo(db_session):
    return UserRepository(db_session)


@pytest.fixture
def project_repo(db_session):
    return ProjectRepository(db_session)


@pytest.fixture
def requirement_repo(db_session):
    return RequirementRepository(db_session)


@pytest.fixture
def artifact_repo(db_session):
    return ArtifactRepository(db_session)


@pytest.fixture
def audit_repo(db_session):
    return AuditRepository(db_session)


# ── Service Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def auth_service(user_repo, audit_repo):
    return AuthService(user_repo, audit_repo)


@pytest.fixture
def project_service(project_repo, user_repo, audit_repo):
    return ProjectService(project_repo, user_repo, audit_repo)


@pytest.fixture
def artifact_service(artifact_repo, audit_repo, project_service):
    return ArtifactService(artifact_repo, audit_repo, project_service, AIEngineClient())


# ── User & Role Fixtures ──────────────────────────────────────────────────────

def create_user_record(db, email: str, role: str, full_name: str, password: str = "TestPass123!") -> User:
    user = User(
        id=str(uuid.uuid4()),
        email=email.lower(),
        full_name=full_name,
        password_hash=hash_password(password),
        role=role.lower(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_token_for_user(user: User) -> dict[str, str]:
    token = create_access_token(user.id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_user(db_session):
    return create_user_record(db_session, "admin@example.com", "admin", "Admin User")


@pytest.fixture
def admin_headers(admin_user):
    return get_token_for_user(admin_user)


@pytest.fixture
def pm_user(db_session):
    return create_user_record(db_session, "pm@example.com", "pm", "Product Manager")


@pytest.fixture
def pm_headers(pm_user):
    return get_token_for_user(pm_user)


@pytest.fixture
def ba_user(db_session):
    return create_user_record(db_session, "ba@example.com", "ba", "Business Analyst")


@pytest.fixture
def ba_headers(ba_user):
    return get_token_for_user(ba_user)


@pytest.fixture
def dev_user(db_session):
    return create_user_record(db_session, "dev@example.com", "developer", "Dev User")


@pytest.fixture
def dev_headers(dev_user):
    return get_token_for_user(dev_user)


@pytest.fixture
def tester_user(db_session):
    return create_user_record(db_session, "tester@example.com", "tester", "QA Tester")


@pytest.fixture
def tester_headers(tester_user):
    return get_token_for_user(tester_user)


# ── AI Engine Mock Helper ─────────────────────────────────────────────────────

@pytest.fixture
def mock_ai_generate(monkeypatch):
    """Mocks AIEngineClient.generate to return standard structured SDLC artifacts."""
    async def fake_generate(self, project_id, artifact_type, requirement_text):
        return {
            "request_id": "test-req-123",
            "project_id": project_id,
            "artifact_type": artifact_type,
            "prompt_version": f"{artifact_type}_v1",
            "output": {
                "title": f"Generated {artifact_type}",
                "items": [
                    {"id": "ITEM-1", "description": f"Specification for {requirement_text[:20]}"}
                ],
            },
            "usage": {"prompt_tokens": 50, "completion_tokens": 100, "total_tokens": 150},
            "latency_ms": 42,
        }
    monkeypatch.setattr(AIEngineClient, "generate", fake_generate)
    return fake_generate


@pytest.fixture
def mock_ai_ingest(monkeypatch):
    """Mocks AIEngineClient.ingest for requirement ingestion."""
    async def fake_ingest(self, file_path, project_id, doc_type="requirement"):
        return {
            "status": "indexed",
            "chunks_indexed": 5,
            "entities": ["PaymentService", "Account"],
            "constraints": ["Max transaction $10,000"],
        }
    monkeypatch.setattr(AIEngineClient, "ingest", fake_ingest)
    return fake_ingest
