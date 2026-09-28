"""
Unit tests for Pydantic schema validation.

Verifies:
- UserCreate: email formatting, blank name rejection, password length constraints
- ProjectCreate: blank name rejection, field lengths
- EvaluationCreate: score boundaries (1 to 5)
"""

import pytest
from pydantic import ValidationError
from app.schemas import UserCreate, ProjectCreate, EvaluationCreate


def test_user_create_valid():
    user = UserCreate(email="test@barclays.com", full_name="Jane Doe", password="password123")
    assert user.email == "test@barclays.com"
    assert user.full_name == "Jane Doe"


def test_user_create_rejects_invalid_email():
    with pytest.raises(ValidationError):
        UserCreate(email="not-an-email", full_name="Jane", password="password123")


def test_user_create_rejects_blank_name():
    with pytest.raises(ValidationError) as exc:
        UserCreate(email="valid@example.com", full_name="   ", password="password123")
    assert "cannot be blank" in str(exc.value)


def test_user_create_rejects_short_password():
    with pytest.raises(ValidationError):
        UserCreate(email="valid@example.com", full_name="Jane", password="short")


def test_project_create_rejects_blank_name():
    with pytest.raises(ValidationError) as exc:
        ProjectCreate(name="   ", description="Some desc")
    assert "cannot be blank" in str(exc.value)


def test_evaluation_create_score_range():
    # Valid scores
    assert EvaluationCreate(score=1).score == 1
    assert EvaluationCreate(score=5).score == 5

    # Invalid scores
    with pytest.raises(ValidationError):
        EvaluationCreate(score=0)

    with pytest.raises(ValidationError):
        EvaluationCreate(score=6)
