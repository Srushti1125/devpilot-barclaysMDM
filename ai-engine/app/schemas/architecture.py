from pydantic import BaseModel


class ArchitectureComponent(BaseModel):
    name: str
    responsibility: str
    technology: str


class Architecture(BaseModel):
    pattern: str = ""
    rationale: str = ""
    technology_recommendations: list[str] = []
    components: list[ArchitectureComponent] = []
    data_flow: str = ""
    security_considerations: list[str] = []
