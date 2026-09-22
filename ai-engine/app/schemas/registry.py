from app.schemas.acceptance_criteria import AcceptanceCriteriaList
from app.schemas.api_spec import ApiSpecList
from app.schemas.architecture import Architecture
from app.schemas.sprint_plan import SprintPlan
from app.schemas.test_case import TestCaseList
from app.schemas.user_story import UserStoryList

SCHEMA_REGISTRY = {
    "user_story": UserStoryList,
    "acceptance_criteria": AcceptanceCriteriaList,
    "test_case": TestCaseList,
    "api_spec": ApiSpecList,
    "architecture": Architecture,
    "sprint_plan": SprintPlan,
}


def get_schema(artifact_type: str):
    try:
        return SCHEMA_REGISTRY[artifact_type]
    except KeyError:
        raise ValueError(
            f"Unknown artifact_type '{artifact_type}'. "
            f"Valid types: {sorted(SCHEMA_REGISTRY.keys())}"
        )
