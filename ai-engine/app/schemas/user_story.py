import uuid

from pydantic import BaseModel, Field


class UserStory(BaseModel):
    id: str = Field(default_factory=lambda: f"US-{uuid.uuid4().hex[:6].upper()}")
    title: str
    story: str = Field(description="As a <role>, I want <goal>, so that <benefit>")
    actor: str = ""
    priority: str = Field(description="High | Medium | Low")
    story_points: int | None = Field(default=None, description="Fibonacci estimate: 1, 2, 3, 5, 8, 13")
    category: str
    acceptance_criteria_summary: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    sprint_candidate: int | None = None


class UserStoryList(BaseModel):
    stories: list[UserStory]
