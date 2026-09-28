from typing import Any

from pydantic import BaseModel, Field


class EvaluationCreate(BaseModel):
    score: int = Field(ge=1, le=5)
    feedback: str = Field(default="", max_length=10000)
    metrics: dict[str, Any] = Field(default_factory=dict)
