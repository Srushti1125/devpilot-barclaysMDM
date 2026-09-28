"""
Unit tests for ProjectService business logic.

Verifies:
- Project creation with automatic owner assignment
- Access control: owner vs member vs admin vs unauthorized
- Project update and delete authorization rules
- Member management with role restrictions (editor, viewer)
- Domain exceptions: ResourceNotFoundError, AuthorisationError, ValidationError
"""

import pytest
from app.core.exceptions import AuthorisationError, ResourceNotFoundError, ValidationError


def test_create_project_success(project_service, dev_user, audit_repo):
    project = project_service.create("Payment Gateway", "Core payment integration", dev_user)

    assert project.id is not None
    assert project.name == "Payment Gateway"
    assert project.owner_id == dev_user.id

    # Verify audit record
    logs = audit_repo.list_recent(limit=10)
    assert any(log.action == "project.create" and log.resource_id == project.id for log in logs)


def test_get_project_owner_and_admin_access(project_service, pm_user, admin_user):
    project = project_service.create("Risk Engine", "Risk analysis service", pm_user)

    # Owner can read and write
    read_by_owner = project_service.get_project_or_fail(project.id, pm_user, write=True)
    assert read_by_owner.id == project.id

    # Admin can read and write even if not owner
    read_by_admin = project_service.get_project_or_fail(project.id, admin_user, write=True)
    assert read_by_admin.id == project.id


def test_get_project_unauthorized_user_raises_authorisation_error(project_service, pm_user, dev_user):
    project = project_service.create("Secret Project", "Confidential", pm_user)

    with pytest.raises(AuthorisationError) as exc_info:
        project_service.get_project_or_fail(project.id, dev_user)

    assert "do not have access" in str(exc_info.value).lower()


def test_get_nonexistent_project_raises_resource_not_found(project_service, dev_user):
    with pytest.raises(ResourceNotFoundError) as exc_info:
        project_service.get_project_or_fail("non-existent-uuid", dev_user)

    assert "project" in str(exc_info.value).lower()


def test_update_project_by_owner_succeeds(project_service, pm_user):
    project = project_service.create("Original Title", "Original Desc", pm_user)

    updated = project_service.update(project.id, pm_user, {"name": "Updated Title", "description": "Updated Desc"})
    assert updated.name == "Updated Title"
    assert updated.description == "Updated Desc"


def test_update_project_by_non_owner_raises_authorisation_error(project_service, pm_user, dev_user):
    project = project_service.create("Protected Project", "Desc", pm_user)

    with pytest.raises(AuthorisationError):
        project_service.update(project.id, dev_user, {"name": "Malicious Rename"})


def test_delete_project_by_owner_succeeds(project_service, pm_user, project_repo):
    project = project_service.create("Ephemeral Project", "To be deleted", pm_user)
    project_id = project.id

    project_service.delete(project_id, pm_user)
    assert project_repo.get(project_id) is None


def test_delete_project_by_admin_succeeds(project_service, pm_user, admin_user, project_repo):
    project = project_service.create("User Project", "Deleted by admin", pm_user)
    project_id = project.id

    project_service.delete(project_id, admin_user)
    assert project_repo.get(project_id) is None


def test_delete_project_by_non_owner_raises_authorisation_error(project_service, pm_user, dev_user):
    project = project_service.create("Safe Project", "Desc", pm_user)

    with pytest.raises(AuthorisationError):
        project_service.delete(project.id, dev_user)


def test_add_member_with_valid_and_invalid_role(project_service, pm_user, dev_user):
    project = project_service.create("Collaborative Project", "Desc", pm_user)

    # Valid roles
    member = project_service.set_member(project.id, dev_user.email, "editor", pm_user)
    assert member["role"] == "editor"
    assert member["user_id"] == dev_user.id

    # Editor now has write access
    assert project_service.get_project_or_fail(project.id, dev_user, write=True) is not None

    # Invalid role rejection
    with pytest.raises(ValidationError) as exc_info:
        project_service.set_member(project.id, dev_user.email, "superadmin", pm_user)
    assert "must be editor or viewer" in str(exc_info.value).lower()
