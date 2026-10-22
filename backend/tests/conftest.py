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
import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app import main as main_module
from app.main import app
from app.domain.models import User, Project, ProjectMember
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


# SQLite keeps local unit tests fast; CI also runs the API and repository tests
# against an explicitly named disposable PostgreSQL test database.
test_database_url = os.getenv("TEST_DATABASE_URL", "sqlite://")
if test_database_url.startswith("sqlite"):
    test_engine = create_engine(
        test_database_url,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
else:
    test_engine = create_engine(test_database_url, pool_pre_ping=True)
TestingSessionLocal = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)


@pytest.fixture(autouse=True)
def setup_database():
    """Ensure a clean database schema before each test."""
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(autouse=True)
def isolate_rate_limiter():
    """Keep process-local request counters from leaking across test cases."""
    with main_module._rate_lock:
        main_module._rate_windows.clear()
    yield
    with main_module._rate_lock:
        main_module._rate_windows.clear()


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
    """Mocks AIEngineClient.generate to return standard structured SDLC artifacts,
    including the SOP telemetry fields (§3.2.2/§6.1)."""
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
            "eval_score": 0.91,
            "retry_count": 1,
            "model_used": "groq-test-model",
        }
    monkeypatch.setattr(AIEngineClient, "generate", fake_generate)
    return fake_generate


@pytest.fixture
def mock_ai_ingest(monkeypatch):
    """Mocks the §2.2.4 job contract end to end: ingest() acknowledges with a job id,
    ingest_status() returns the terminal payload the backend finalizes on first poll."""
    async def fake_ingest(self, file_path, project_id, doc_type="requirement", doc_id=None):
        return {"job_id": f"engine-job-{doc_id}", "status": "processing"}

    async def fake_ingest_status(self, engine_job_id):
        return {
            "status": "done",
            "chunks_indexed": 5,
            "content_hash": "c" * 64,
            "tree_nodes": [
                {"node_id": "n-root", "parent_id": None, "ordinal": "0", "level": 1,
                 "title": "1 Authentication", "page_start": 1, "page_end": 2, "text": "", "low_structure": False},
                {"node_id": "n-child", "parent_id": "n-root", "ordinal": "0.0", "level": 2,
                 "title": "1.1 Password Reset", "page_start": 1, "page_end": 1,
                 "text": "Reset via OTP.", "low_structure": False},
            ],
        }
    monkeypatch.setattr(AIEngineClient, "ingest", fake_ingest)
    monkeypatch.setattr(AIEngineClient, "ingest_status", fake_ingest_status)
    return fake_ingest, fake_ingest_status


@pytest.fixture
def mock_ai_ingest_failed(monkeypatch):
    """Job kicks off cleanly but the engine job fails — status path."""
    async def fake_ingest(self, file_path, project_id, doc_type="requirement", doc_id=None):
        return {"job_id": "engine-job-bad", "status": "processing"}

    async def fake_status(self, engine_job_id):
        return {"status": "failed", "error": "unsupported file type", "error_type": "invalid_input"}

    monkeypatch.setattr(AIEngineClient, "ingest", fake_ingest)
    monkeypatch.setattr(AIEngineClient, "ingest_status", fake_status)
    return fake_status
