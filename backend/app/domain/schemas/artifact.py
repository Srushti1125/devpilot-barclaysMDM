from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class GenerateRequest(BaseModel):
    artifact_type: str = Field(min_length=1, max_length=80)
    requirement_text: str = Field(min_length=1, max_length=100000)

    @field_validator("requirement_text")
    @classmethod
    def requirement_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Requirement text cannot be blank")
        return value.strip()


class ArtifactUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    content: dict[str, Any] | None = None


class ArtifactOut(BaseModel):
    id: str
    project_id: str
    created_by: str
    artifact_type: str
    title: str
    content: dict[str, Any]
    version: int
    created_at: datetime
    updated_at: datetime
