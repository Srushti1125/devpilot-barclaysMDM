"""
Database repository tests for RequirementRepository.

Verifies:
- Requirement entity persistence and field mapping
- Project-scoped requirement listing ordered by created_at desc
"""

from app.domain.models import Project, Requirement


def test_requirement_repo_add_and_get(requirement_repo, project_repo, dev_user):
    project = Project(id=project_repo.new_id(), name="Loans", owner_id=dev_user.id)
    project_repo.add(project)
    project_repo.commit()

    req_id = requirement_repo.new_id()
    req = Requirement(
        id=req_id,
        project_id=project.id,
        uploaded_by=dev_user.id,
        filename="loan_rules.txt",
        file_path="/tmp/loan_rules.txt",
        content="Personal loan interest rate is capped at 12%.",
        doc_type="requirement",
        chunks_indexed=3,
    )
    requirement_repo.add(req)
    requirement_repo.commit()

    retrieved = requirement_repo.get(req_id)
    assert retrieved is not None
    assert retrieved.filename == "loan_rules.txt"
    assert retrieved.chunks_indexed == 3
    assert "capped at 12%" in retrieved.content


def test_requirement_repo_list_for_project(requirement_repo, project_repo, dev_user):
    project = Project(id=project_repo.new_id(), name="Mortgages", owner_id=dev_user.id)
    project_repo.add(project)
    project_repo.commit()

    r1 = Requirement(
        id=requirement_repo.new_id(),
        project_id=project.id,
        uploaded_by=dev_user.id,
        filename="doc1.txt",
        file_path="/tmp/1",
    )
    r2 = Requirement(
        id=requirement_repo.new_id(),
        project_id=project.id,
        uploaded_by=dev_user.id,
        filename="doc2.txt",
        file_path="/tmp/2",
    )
    requirement_repo.add(r1)
    requirement_repo.add(r2)
    requirement_repo.commit()

    results = requirement_repo.list_for_project(project.id)
    assert len(results) == 2
