import re

from app.schemas.user_story import UserStory
from app.schemas.registry import SCHEMA_REGISTRY
from app.tracking.cost import estimate_cost_usd


def test_richer_user_story_defaults_are_backward_compatible():
    story = UserStory(title="Reset password", story="As a user, I want a reset link so I can sign in",
                      priority="High", category="identity")
    assert re.fullmatch(r"US-[A-F0-9]{6}", story.id)
    assert story.actor == ""
    assert story.story_points is None
    assert story.acceptance_criteria_summary == []
    assert story.sprint_candidate is None


def test_conversational_schema_has_a_matching_prompt_template():
    from app.prompts.registry import list_artifact_types, list_versions

    assert "conversational" in SCHEMA_REGISTRY
    assert "conversational" in list_artifact_types()
    assert list_versions("conversational") == ["v1"]


def test_cost_estimate_uses_model_family_and_local_models_are_free():
    assert estimate_cost_usd("groq-test-model", 1000, 1000) > 0
    assert estimate_cost_usd("ollama-llama3", 1000, 1000) == 0
