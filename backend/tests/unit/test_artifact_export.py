import csv
import io
from types import SimpleNamespace

from app.services.artifact_export import render_artifact_export


def test_user_story_csv_exports_jira_columns_and_optional_fields():
    artifact = SimpleNamespace(
        id="artifact-1",
        project_id="project-1",
        artifact_type="user_story",
        title="Stories",
        version=1,
        content={
            "stories": [{
                "title": "Reset password",
                "story": "As a user, I want a reset flow",
                "priority": "High",
                "category": "Identity",
                "story_points": 3,
                "sprint_candidate": 2,
            }]
        },
    )

    response = render_artifact_export(artifact, "CSV")
    rows = list(csv.reader(io.StringIO(response.body.decode())))

    assert rows == [
        [
            "Issue ID", "Summary", "Description", "Priority", "Category",
            "Story Points", "Sprint", "Issue Type",
        ],
        [
            "US-1", "Reset password", "As a user, I want a reset flow",
            "High", "Identity", "3", "2", "Story",
        ],
    ]


def test_gherkin_export_supports_list_steps():
    artifact = SimpleNamespace(
        id="artifact-2",
        artifact_type="acceptance_criteria",
        title="Password Reset",
        content={
            "criteria": [{
                "title": "Valid OTP",
                "given": ["an account exists", "OTP was sent"],
                "when": "the OTP is valid",
                "then": ["password is updated"],
            }]
        },
    )

    response = render_artifact_export(artifact, "gherkin")
    text = response.body.decode()

    assert response.media_type == "text/plain"
    assert "Feature: Password Reset" in text
    assert "Given an account exists" in text
    assert "Given OTP was sent" in text
    assert "Then password is updated" in text


def test_gherkin_format_is_not_rendered_for_other_artifacts():
    artifact = SimpleNamespace(
        id="artifact-3",
        project_id="project-1",
        artifact_type="architecture",
        title="Architecture",
        version=1,
        content={},
    )

    assert render_artifact_export(artifact, "gherkin") is None
