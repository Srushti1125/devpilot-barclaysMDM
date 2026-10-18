from pydantic import BaseModel, Field


class ConversationalResponse(BaseModel):
    answer: str = Field(description="Concise answer grounded in retrieved project context")
    sources: list[str] = Field(default_factory=list)
