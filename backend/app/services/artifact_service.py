"""
Artifact generation, update, export, and evaluation business logic.
"""

import json
import uuid

from app.core.exceptions import ResourceNotFoundError, ValidationError
from app.domain.models import Artifact, Evaluation, GenerationHistory, User
from app.repositories.artifact_repo import ArtifactRepository
from app.repositories.audit_repo import AuditRepository
from app.services.ai_engine import AIEngineClient
from app.services.project_service import ProjectService


class ArtifactService:
    def __init__(
        self,
        artifact_repo: ArtifactRepository,
        audit_repo: AuditRepository,
        project_service: ProjectService,
        ai_client: AIEngineClient,
    ):
        self.artifact_repo = artifact_repo
        self.audit_repo = audit_repo
        self.project_service = project_service
        self.ai_client = ai_client

    # ── Helpers ─────────────────────────────────────────────────────────

    def _get_artifact_or_fail(self, artifact_id: str) -> Artifact:
        artifact = self.artifact_repo.get(artifact_id)
        if not artifact:
            raise ResourceNotFoundError("Artifact", artifact_id)
        return artifact

    # ── Generation ──────────────────────────────────────────────────────

    async def generate(
        self,
        project_id: str,
        artifact_type: str,
        requirement_text: str,
        user: User,
    ) -> Artifact:
        self.project_service.get_project_or_fail(project_id, user, write=True)

        result = await self.ai_client.generate(project_id, artifact_type, requirement_text)
        content = result.get("output")
        if not isinstance(content, dict):
            raise ValidationError("AI engine returned an invalid artifact payload")

        artifact = Artifact(
            id=self.artifact_repo.new_id(),
            project_id=project_id,
            created_by=user.id,
            artifact_type=result.get("artifact_type", artifact_type),
            title=f"{artifact_type.replace('_', ' ').title()}",
            content=content,
        )
        self.artifact_repo.add(artifact)
        self.artifact_repo.flush()

        history = GenerationHistory(
            id=self.artifact_repo.new_id(),
            project_id=project_id,
            artifact_id=artifact.id,
            user_id=user.id,
            engine_request_id=result.get("request_id", ""),
            artifact_type=artifact.artifact_type,
            prompt_version=result.get("prompt_version", ""),
            usage=result.get("usage") or {},
            latency_ms=result.get("latency_ms", 0),
            requirement_text=requirement_text,
        )
        self.artifact_repo.add_history(history)

        self.audit_repo.record(
            user.id,
            "artifact.generate",
            "artifact",
            artifact.id,
            {
                "request_id": history.engine_request_id,
                "prompt_version": history.prompt_version,
                "usage": history.usage,
                "latency_ms": history.latency_ms,
            },
        )
        self.artifact_repo.commit()
        return self.artifact_repo.refresh(artifact)

    # ── Read / List ─────────────────────────────────────────────────────

    def list_for_project(self, project_id: str, user: User) -> list[Artifact]:
        self.project_service.get_project_or_fail(project_id, user)
        return self.artifact_repo.list_for_project(project_id)

    def get(self, artifact_id: str, user: User) -> Artifact:
        artifact = self._get_artifact_or_fail(artifact_id)
        self.project_service.get_project_or_fail(artifact.project_id, user)
        return artifact

    # ── Update ──────────────────────────────────────────────────────────

    def update(self, artifact_id: str, updates: dict, user: User) -> Artifact:
        artifact = self._get_artifact_or_fail(artifact_id)
        self.project_service.get_project_or_fail(artifact.project_id, user, write=True)

        for key, value in updates.items():
            if value is not None:
                setattr(artifact, key, value)
        artifact.version += 1

        self.audit_repo.record(
            user.id, "artifact.update", "artifact", artifact.id, {"version": artifact.version}
        )
        self.artifact_repo.commit()
        return self.artifact_repo.refresh(artifact)

    # ── History ─────────────────────────────────────────────────────────

    def list_history(self, project_id: str, user: User) -> list[dict]:
        self.project_service.get_project_or_fail(project_id, user)
        entries = self.artifact_repo.list_history(project_id)
        return [
            {
                "id": h.id,
                "artifact_id": h.artifact_id,
                "artifact_type": h.artifact_type,
                "engine_request_id": h.engine_request_id,
                "prompt_version": h.prompt_version,
                "usage": h.usage,
                "latency_ms": h.latency_ms,
                "created_at": h.created_at,
            }
            for h in entries
        ]

    # ── Export ───────────────────────────────────────────────────────────

    def export_json(self, artifact_id: str, user: User) -> str:
        artifact = self.get(artifact_id, user)
        return json.dumps(
            {
                "id": artifact.id,
                "project_id": artifact.project_id,
                "artifact_type": artifact.artifact_type,
                "title": artifact.title,
                "version": artifact.version,
                "content": artifact.content,
            },
            indent=2,
        )

    # ── Evaluations ─────────────────────────────────────────────────────

    def evaluate(
        self, artifact_id: str, score: int, feedback: str, metrics: dict, user: User
    ) -> Evaluation:
        artifact = self._get_artifact_or_fail(artifact_id)
        self.project_service.get_project_or_fail(artifact.project_id, user, write=True)

        item = Evaluation(
            id=self.artifact_repo.new_id(),
            artifact_id=artifact_id,
            user_id=user.id,
            score=score,
            feedback=feedback,
            metrics=metrics,
        )
        self.artifact_repo.add_evaluation(item)
        self.audit_repo.record(
            user.id, "artifact.evaluate", "artifact", artifact_id, {"score": score}
        )
        self.artifact_repo.commit()
        return item

    def list_evaluations(self, artifact_id: str, user: User) -> list[dict]:
        artifact = self._get_artifact_or_fail(artifact_id)
        self.project_service.get_project_or_fail(artifact.project_id, user)
        items = self.artifact_repo.list_evaluations(artifact_id)
        return [
            {
                "id": x.id,
                "user_id": x.user_id,
                "score": x.score,
                "feedback": x.feedback,
                "metrics": x.metrics,
                "created_at": x.created_at,
            }
            for x in items
        ]
