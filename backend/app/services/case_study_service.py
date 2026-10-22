from app.core.exceptions import ValidationError
from app.domain.models import User
from app.repositories.audit_repo import AuditRepository
from app.repositories.history_repo import GenerationHistoryRepository
from app.repositories.requirement_repo import RequirementRepository
from app.services.artifact_service import ArtifactService


class CaseStudyService:
    ARTIFACT_TYPES = (
        "user_story",
        "acceptance_criteria",
        "test_case",
        "api_spec",
        "architecture",
        "sprint_plan",
    )

    def __init__(
        self,
        requirement_repo: RequirementRepository,
        history_repo: GenerationHistoryRepository,
        audit_repo: AuditRepository,
        artifact_service: ArtifactService,
    ):
        self.requirement_repo = requirement_repo
        self.history_repo = history_repo
        self.audit_repo = audit_repo
        self.artifact_service = artifact_service

    async def generate(self, project_id: str, limit: int, user: User) -> dict:
        requirements = self.requirement_repo.list_for_project(
            project_id, limit=limit, oldest_first=True
        )
        if not requirements:
            raise ValidationError("No requirements ingested for this project")

        report_rows = []
        for requirement in requirements:
            requirement_text = (requirement.content or "").strip() or (
                f"Requirement document: {requirement.filename}"
            )
            entries = []
            for artifact_type in self.ARTIFACT_TYPES:
                try:
                    artifact = await self.artifact_service.generate(
                        project_id, artifact_type, requirement_text, user
                    )
                    history = self.history_repo.get_for_artifact(artifact.id)
                    if history:
                        history.requirement_id = requirement.id
                        self.history_repo.commit()
                    entries.append({
                        "artifact_id": artifact.id,
                        "artifact_type": artifact_type,
                        "eval_score": history.eval_score if history else None,
                        "latency_ms": history.latency_ms if history else 0,
                        "retry_count": history.retry_count if history else 0,
                        "model_used": history.model_used if history else None,
                    })
                except Exception as exc:
                    self.history_repo.rollback()
                    entries.append({"artifact_type": artifact_type, "error": str(exc)[:500]})
            report_rows.append({
                "requirement_id": requirement.id,
                "filename": requirement.filename,
                "artifacts": entries,
            })

        successful = [
            item for row in report_rows for item in row["artifacts"] if "artifact_id" in item
        ]
        scores = [item["eval_score"] for item in successful if item["eval_score"] is not None]
        self.audit_repo.record(
            user.id,
            "project.case_study",
            "project",
            project_id,
            {"requirements": len(requirements), "generated": len(successful)},
        )
        self.audit_repo.commit()
        return {
            "project_id": project_id,
            "requirements": report_rows,
            "summary": {
                "total_artifacts_generated": len(successful),
                "avg_eval_score": round(sum(scores) / len(scores), 3) if scores else None,
                "pass_rate_80pct": round(
                    sum(score >= 0.8 for score in scores) / len(scores), 3
                ) if scores else None,
                "artifact_types_covered": list(self.ARTIFACT_TYPES),
            },
        }
