"""Composable validators for generated artifacts."""
from __future__ import annotations

import json
from typing import Protocol


class ArtifactValidator(Protocol):
    name: str
    def validate(self, artifact: dict, requirement: str) -> tuple[bool, str]: ...


class SchemaValidator:
    name = "schema"

    def __init__(self, schema_cls):
        self.schema_cls = schema_cls

    def validate(self, artifact: dict, requirement: str) -> tuple[bool, str]:
        from app.pipeline.quality_check import format_compliance_score
        passed = format_compliance_score(json.dumps(artifact), self.schema_cls)
        return passed, "" if passed else "Output does not conform to the required JSON schema."


class LLMJudgeValidator:
    name = "llm_judge"

    def __init__(self, threshold: float):
        self.threshold = threshold
        self.score: float | None = None

    def validate(self, artifact: dict, requirement: str) -> tuple[bool, str]:
        from app.pipeline.sop_graph import judge_score
        self.score, reason = judge_score(requirement, json.dumps(artifact))
        return self.score >= self.threshold, reason


class ValidationChain:
    """Run ordered validators and stop when one fails."""

    def __init__(self, validators: list[ArtifactValidator]):
        self.validators = validators

    def run(self, artifact: dict, requirement: str) -> tuple[bool, list[str]]:
        failures: list[str] = []
        for validator in self.validators:
            passed, reason = validator.validate(artifact, requirement)
            if not passed:
                failures.append(f"[{validator.name}] {reason}")
                return False, failures
        return True, failures
