from pydantic import BaseModel


class SprintItem(BaseModel):
    story_title: str
    story_points: int
    effort_estimate_hours: float
    dependencies: list[str] = []
    sprint: int


class SprintPlan(BaseModel):
    items: list[SprintItem]
    critical_path: list[str] = []
    assumed_velocity_points_per_sprint: int = 0
