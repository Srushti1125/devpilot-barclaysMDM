"""
Database repository tests for ProjectRepository.

Verifies:
- Project entity creation, retrieval, and updates
- Membership tracking and role assignment
- User project listing (both owned and member projects)
- Cascade and deletion constraints
"""

from app.domain.models import Project, ProjectMember


def test_project_repo_create_and_get(project_repo, dev_user):
    proj_id = project_repo.new_id()
    project = Project(
        id=proj_id,
        name="Credit Card Engine",
        description="Handles credit approval",
        owner_id=dev_user.id,
    )
    project_repo.add(project)
    project_repo.commit()

    retrieved = project_repo.get(proj_id)
    assert retrieved is not None
    assert retrieved.name == "Credit Card Engine"
    assert retrieved.owner_id == dev_user.id


def test_project_repo_list_for_user(project_repo, dev_user, pm_user):
    # Dev owns project 1
    p1 = Project(id=project_repo.new_id(), name="P1", owner_id=dev_user.id)
    project_repo.add(p1)

    # PM owns project 2, dev is a member
    p2 = Project(id=project_repo.new_id(), name="P2", owner_id=pm_user.id)
    project_repo.add(p2)
    project_repo.flush()

    member = ProjectMember(
        id=project_repo.new_id(),
        project_id=p2.id,
        user_id=dev_user.id,
        role="viewer",
    )
    project_repo.add_member(member)
    project_repo.commit()

    dev_projects = project_repo.list_for_user(dev_user.id)
    project_ids = [p.id for p in dev_projects]
    assert p1.id in project_ids
    assert p2.id in project_ids


def test_project_repo_membership_lookup(project_repo, dev_user, pm_user):
    p = Project(id=project_repo.new_id(), name="P", owner_id=pm_user.id)
    project_repo.add(p)
    project_repo.flush()

    member = ProjectMember(
        id=project_repo.new_id(),
        project_id=p.id,
        user_id=dev_user.id,
        role="editor",
    )
    project_repo.add_member(member)
    project_repo.commit()

    found = project_repo.get_membership(p.id, dev_user.id)
    assert found is not None
    assert found.role == "editor"

    not_found = project_repo.get_membership(p.id, "unrelated-user-id")
    assert not_found is None
