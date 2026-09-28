"""
Role-Based Access Control (RBAC) authorization tests.

Roles tested:
- Admin
- Product Manager (PM)
- Business Analyst (BA)
- Software Developer (Dev)
- QA / Test Engineer (Tester)

Verifies:
- Project deletion permissions (Admin and Owner allowed, non-owners rejected with 403)
- Audit log viewing (Admin-only restricted endpoint, non-admins rejected with 403)
- Non-member project read isolation (403)
"""

import pytest


def test_project_deletion_rbac_matrix(client, admin_headers, pm_headers, ba_headers, dev_headers, tester_headers):
    # PM creates a project (PM is the owner)
    proj_response = client.post("/api/v1/projects", json={"name": "Owner Project"}, headers=pm_headers)
    assert proj_response.status_code == 201
    project_id = proj_response.json()["id"]

    # Non-owner roles must be denied deletion (403)
    for role_name, headers in [("BA", ba_headers), ("Developer", dev_headers), ("Tester", tester_headers)]:
        res = client.delete(f"/api/v1/projects/{project_id}", headers=headers)
        assert res.status_code == 403, f"Expected 403 for {role_name} deleting project, got {res.status_code}"

    # Owner (PM) can delete their own project (204)
    res_owner = client.delete(f"/api/v1/projects/{project_id}", headers=pm_headers)
    assert res_owner.status_code == 204


def test_admin_can_delete_any_project(client, admin_headers, dev_headers):
    # Developer creates a project
    dev_proj = client.post("/api/v1/projects", json={"name": "Dev Microservice"}, headers=dev_headers).json()
    project_id = dev_proj["id"]

    # Admin deletes Developer's project -> allowed (204)
    admin_del = client.delete(f"/api/v1/projects/{project_id}", headers=admin_headers)
    assert admin_del.status_code == 204

    # Verify project is gone (404)
    assert client.get(f"/api/v1/projects/{project_id}", headers=admin_headers).status_code == 404


@pytest.mark.parametrize(
    "role_fixture, expected_status",
    [
        ("admin_headers", 200),
        ("pm_headers", 403),
        ("ba_headers", 403),
        ("dev_headers", 403),
        ("tester_headers", 403),
    ],
)
def test_audit_logs_rbac_enforcement(client, request, role_fixture, expected_status):
    headers = request.getfixturevalue(role_fixture)
    response = client.get("/api/v1/audit-logs", headers=headers)
    assert response.status_code == expected_status


def test_non_member_access_forbidden(client, pm_headers, dev_headers):
    # PM creates private project
    proj = client.post("/api/v1/projects", json={"name": "PM Private"}, headers=pm_headers).json()

    # Developer (not added to project) tries to view -> 403
    denied = client.get(f"/api/v1/projects/{proj['id']}", headers=dev_headers)
    assert denied.status_code == 403
