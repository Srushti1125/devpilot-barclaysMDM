from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=160)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("full_name")
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Full name cannot be blank")
        return value.strip()


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: EmailStr
    full_name: str
    role: str
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=10000)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Project name cannot be blank")
        return value.strip()


class ProjectOut(BaseModel):
    id: str
    name: str
    description: str
    owner_id: str
    created_at: datetime


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=10000)


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


class EvaluationCreate(BaseModel):
    score: int = Field(ge=1, le=5)
    feedback: str = Field(default="", max_length=10000)
    metrics: dict[str, Any] = Field(default_factory=dict)
