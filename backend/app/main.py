import json
import logging
import os
import uuid
from pathlib import Path
from fastapi import Depends, FastAPI, File, HTTPException, Query, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Base, engine, get_db
from app.models import Artifact, AuditLog, Evaluation, GenerationHistory, Project, ProjectMember, Requirement, User
from app.schemas import (ArtifactOut, ArtifactUpdate, EvaluationCreate, GenerateRequest, LoginRequest,
                         ProjectCreate, ProjectOut, ProjectUpdate, Token, UserCreate, UserOut)
from app.security import create_access_token, hash_password, token_subject, verify_password
from app.services.ai_engine import AIEngineClient

logging.basicConfig(level=settings.log_level.upper())
logger = logging.getLogger("devpilot.backend")
bearer_scheme = HTTPBearer(auto_error=False)
app = FastAPI(title="DevPilot Backend API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

if settings.auto_create_tables:
    Base.metadata.create_all(bind=engine)


def audit(db: Session, user_id: str | None, action: str, resource_type: str, resource_id: str | None, details=None):
    db.add(AuditLog(id=str(uuid.uuid4()), user_id=user_id, action=action, resource_type=resource_type,
                    resource_id=resource_id, details=details or {}))


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
                 db: Session = Depends(get_db)) -> User:
    token = credentials.credentials if credentials else ""
    subject = token_subject(token)
    user = db.get(User, subject) if subject else None
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid or expired authentication token",
                            headers={"WWW-Authenticate": "Bearer"})
    return user


def get_project(db: Session, project_id: str, user: User, write: bool = False) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.owner_id == user.id or user.role == "admin":
        return project
    member = db.scalar(select(ProjectMember).where(ProjectMember.project_id == project_id,
                                                   ProjectMember.user_id == user.id))
    if not member or (write and member.role not in ("owner", "editor")):
        raise HTTPException(status_code=403, detail="You do not have access to this project")
    return project


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/v1/auth/register", response_model=UserOut, status_code=201)
def register(payload: UserCreate, db: Session = Depends(get_db)):
    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="Email already registered")
    user = User(id=str(uuid.uuid4()), email=email, full_name=payload.full_name.strip(),
                password_hash=hash_password(payload.password), role="member")
    db.add(user)
    db.flush()
    audit(db, user.id, "user.register", "user", user.id)
    db.commit()
    db.refresh(user)
    return user


@app.post("/api/v1/auth/login", response_model=Token)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password",
                            headers={"WWW-Authenticate": "Bearer"})
    audit(db, user.id, "auth.login", "user", user.id)
    db.commit()
    return Token(access_token=create_access_token(user.id))


@app.get("/api/v1/auth/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


@app.get("/api/v1/artifact-types")
async def artifact_types(user: User = Depends(current_user)):
    return await AIEngineClient().artifact_types()


@app.post("/api/v1/projects", response_model=ProjectOut, status_code=201)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    project = Project(id=str(uuid.uuid4()), name=payload.name.strip(), description=payload.description,
                      owner_id=user.id)
    db.add(project)
    db.flush()
    db.add(ProjectMember(id=str(uuid.uuid4()), project_id=project.id, user_id=user.id, role="owner"))
    audit(db, user.id, "project.create", "project", project.id)
    db.commit()
    db.refresh(project)
    return project


@app.get("/api/v1/projects", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return list(db.scalars(select(Project).outerjoin(ProjectMember, ProjectMember.project_id == Project.id)
                           .where(or_(Project.owner_id == user.id, ProjectMember.user_id == user.id))
                           .order_by(Project.created_at.desc())).unique())


@app.get("/api/v1/projects/{project_id}", response_model=ProjectOut)
def read_project(project_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return get_project(db, project_id, user)


@app.patch("/api/v1/projects/{project_id}", response_model=ProjectOut)
def update_project(project_id: str, payload: ProjectUpdate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    project = get_project(db, project_id, user, write=True)
    if user.role != "admin" and project.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only the project owner can update project settings")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, key, value)
    audit(db, user.id, "project.update", "project", project.id)
    db.commit()
    db.refresh(project)
    return project


@app.delete("/api/v1/projects/{project_id}", status_code=204)
def delete_project(project_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    project = get_project(db, project_id, user, write=True)
    if user.role != "admin" and project.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only the project owner can delete this project")
    audit(db, user.id, "project.delete", "project", project.id)
    db.delete(project)
    db.commit()
    return Response(status_code=204)


@app.post("/api/v1/projects/{project_id}/members", status_code=201)
def add_member(project_id: str, email: str = Query(...), role: str = Query("viewer"),
               db: Session = Depends(get_db), user: User = Depends(current_user)):
    project = get_project(db, project_id, user, write=True)
    if project.owner_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Only the project owner can manage members")
    if role not in {"editor", "viewer"}:
        raise HTTPException(status_code=422, detail="Role must be editor or viewer")
    member_user = db.scalar(select(User).where(User.email == email.lower()))
    if not member_user:
        raise HTTPException(status_code=404, detail="User not found")
    existing = db.scalar(select(ProjectMember).where(ProjectMember.project_id == project_id,
                                                     ProjectMember.user_id == member_user.id))
    if existing:
        existing.role = role
        membership = existing
    else:
        membership = ProjectMember(id=str(uuid.uuid4()), project_id=project_id, user_id=member_user.id, role=role)
        db.add(membership)
    audit(db, user.id, "project.member.set", "project", project_id, {"member_id": member_user.id, "role": role})
    db.commit()
    return {"project_id": project_id, "user_id": member_user.id, "role": membership.role}


@app.post("/api/v1/projects/{project_id}/requirements", status_code=201)
async def ingest_requirement(project_id: str, file: UploadFile = File(...), doc_type: str = "requirement",
                             db: Session = Depends(get_db), user: User = Depends(current_user)):
    get_project(db, project_id, user, write=True)
    filename = Path(file.filename or "requirement.txt").name
    suffix = Path(filename).suffix.lower()
    if suffix not in {".pdf", ".docx", ".doc", ".txt", ".md", ".csv", ".pptx", ".xlsx", ".html"}:
        raise HTTPException(status_code=415, detail="Unsupported requirement file type")
    data = await file.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Requirement file exceeds 10 MB")
    os.makedirs(settings.upload_dir, exist_ok=True)
    path = Path(settings.upload_dir) / f"{uuid.uuid4()}{suffix}"
    path.write_bytes(data)
    content = data.decode("utf-8", errors="replace") if suffix in {".txt", ".md", ".csv", ".html"} else ""
    try:
        result = await AIEngineClient().ingest(str(path.resolve()), project_id, doc_type)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    record = Requirement(id=str(uuid.uuid4()), project_id=project_id, uploaded_by=user.id, filename=filename,
                         file_path=str(path), content=content, doc_type=doc_type,
                         chunks_indexed=result.get("chunks_indexed", 0))
    db.add(record)
    audit(db, user.id, "requirement.ingest", "requirement", record.id,
          {"filename": filename, "chunks_indexed": record.chunks_indexed})
    db.commit()
    return {"id": record.id, "filename": filename, "project_id": project_id, **result}


@app.get("/api/v1/projects/{project_id}/requirements")
def list_requirements(project_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    get_project(db, project_id, user)
    rows = db.scalars(select(Requirement).where(Requirement.project_id == project_id).order_by(Requirement.created_at.desc()))
    return [{"id": r.id, "filename": r.filename, "doc_type": r.doc_type, "chunks_indexed": r.chunks_indexed,
             "created_at": r.created_at} for r in rows]


@app.get("/api/v1/requirements/{requirement_id}")
def read_requirement(requirement_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    requirement = db.get(Requirement, requirement_id)
    if not requirement:
        raise HTTPException(status_code=404, detail="Requirement not found")
    get_project(db, requirement.project_id, user)
    return {"id": requirement.id, "project_id": requirement.project_id, "filename": requirement.filename,
            "doc_type": requirement.doc_type, "content": requirement.content,
            "chunks_indexed": requirement.chunks_indexed, "created_at": requirement.created_at}


@app.post("/api/v1/projects/{project_id}/generate", response_model=ArtifactOut, status_code=201)
async def generate(project_id: str, payload: GenerateRequest, db: Session = Depends(get_db), user: User = Depends(current_user)):
    get_project(db, project_id, user, write=True)
    result = await AIEngineClient().generate(project_id, payload.artifact_type, payload.requirement_text)
    content = result.get("output")
    if not isinstance(content, dict):
        raise HTTPException(status_code=502, detail="AI engine returned an invalid artifact payload")
    artifact = Artifact(id=str(uuid.uuid4()), project_id=project_id, created_by=user.id,
                        artifact_type=result.get("artifact_type", payload.artifact_type),
                        title=f"{payload.artifact_type.replace('_', ' ').title()}", content=content)
    db.add(artifact)
    db.flush()
    history = GenerationHistory(id=str(uuid.uuid4()), project_id=project_id, artifact_id=artifact.id,
                                user_id=user.id, engine_request_id=result.get("request_id", ""),
                                artifact_type=artifact.artifact_type, prompt_version=result.get("prompt_version", ""),
                                usage=result.get("usage") or {}, latency_ms=result.get("latency_ms", 0),
                                requirement_text=payload.requirement_text)
    db.add(history)
    audit(db, user.id, "artifact.generate", "artifact", artifact.id,
          {"request_id": history.engine_request_id, "prompt_version": history.prompt_version,
           "usage": history.usage, "latency_ms": history.latency_ms})
    db.commit()
    db.refresh(artifact)
    return artifact


@app.get("/api/v1/projects/{project_id}/artifacts", response_model=list[ArtifactOut])
def list_artifacts(project_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    get_project(db, project_id, user)
    return list(db.scalars(select(Artifact).where(Artifact.project_id == project_id).order_by(Artifact.created_at.desc())))


@app.get("/api/v1/artifacts/{artifact_id}", response_model=ArtifactOut)
def read_artifact(artifact_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    artifact = db.get(Artifact, artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    get_project(db, artifact.project_id, user)
    return artifact


@app.patch("/api/v1/artifacts/{artifact_id}", response_model=ArtifactOut)
def update_artifact(artifact_id: str, payload: ArtifactUpdate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    artifact = db.get(Artifact, artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    get_project(db, artifact.project_id, user, write=True)
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(artifact, key, value)
    artifact.version += 1
    audit(db, user.id, "artifact.update", "artifact", artifact.id, {"version": artifact.version})
    db.commit()
    db.refresh(artifact)
    return artifact


@app.get("/api/v1/projects/{project_id}/history")
def generation_history(project_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    get_project(db, project_id, user)
    entries = db.scalars(select(GenerationHistory).where(GenerationHistory.project_id == project_id)
                         .order_by(GenerationHistory.created_at.desc()))
    return [{"id": h.id, "artifact_id": h.artifact_id, "artifact_type": h.artifact_type,
             "engine_request_id": h.engine_request_id, "prompt_version": h.prompt_version,
             "usage": h.usage, "latency_ms": h.latency_ms, "created_at": h.created_at} for h in entries]


@app.post("/api/v1/artifacts/{artifact_id}/evaluations", status_code=201)
def evaluate_artifact(artifact_id: str, payload: EvaluationCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    artifact = db.get(Artifact, artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    get_project(db, artifact.project_id, user, write=True)
    item = Evaluation(id=str(uuid.uuid4()), artifact_id=artifact_id, user_id=user.id,
                      score=payload.score, feedback=payload.feedback, metrics=payload.metrics)
    db.add(item)
    audit(db, user.id, "artifact.evaluate", "artifact", artifact_id, {"score": payload.score})
    db.commit()
    return {"id": item.id, "artifact_id": item.artifact_id, "score": item.score,
            "feedback": item.feedback, "metrics": item.metrics, "created_at": item.created_at}


@app.get("/api/v1/artifacts/{artifact_id}/evaluations")
def artifact_evaluations(artifact_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    artifact = db.get(Artifact, artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    get_project(db, artifact.project_id, user)
    items = db.scalars(select(Evaluation).where(Evaluation.artifact_id == artifact_id).order_by(Evaluation.created_at.desc()))
    return [{"id": x.id, "user_id": x.user_id, "score": x.score, "feedback": x.feedback,
             "metrics": x.metrics, "created_at": x.created_at} for x in items]


@app.get("/api/v1/artifacts/{artifact_id}/export")
def export_artifact(artifact_id: str, format: str = Query("json", pattern="^json$"),
                    db: Session = Depends(get_db), user: User = Depends(current_user)):
    artifact = db.get(Artifact, artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    get_project(db, artifact.project_id, user)
    body = json.dumps({"id": artifact.id, "project_id": artifact.project_id, "artifact_type": artifact.artifact_type,
                       "title": artifact.title, "version": artifact.version, "content": artifact.content}, indent=2)
    return Response(content=body, media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{artifact.artifact_type}-{artifact.id}.json"'})


@app.get("/api/v1/audit-logs")
def audit_logs(limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db), user: User = Depends(current_user)):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Administrator role required")
    rows = db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit))
    return [{"id": row.id, "user_id": row.user_id, "action": row.action, "resource_type": row.resource_type,
             "resource_id": row.resource_id, "details": row.details, "created_at": row.created_at} for row in rows]
