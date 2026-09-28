"""
Integration tests for Project API endpoints (/api/v1/projects/*).

Verifies:
- Complete CRUD lifecycle
- Nonexistent resource 404s
- Input validation (empty name rejection)
- Project member management (editor/viewer roles, email lookups)
"""


def test_project_crud_lifecycle(client, dev_headers):
    # 1. Create
    create_res = client.post(
        "/api/v1/projects",
        json={"name": "Transaction Engine", "description": "High-throughput processing"},
        headers=dev_headers,
    )
    assert create_res.status_code == 201
    project = create_res.json()
    proj_id = project["id"]
    assert project["name"] == "Transaction Engine"

    # 2. List
    list_res = client.get("/api/v1/projects", headers=dev_headers)
    assert list_res.status_code == 200
    ids = [p["id"] for p in list_res.json()]
    assert proj_id in ids

    # 3. Read
    read_res = client.get(f"/api/v1/projects/{proj_id}", headers=dev_headers)
    assert read_res.status_code == 200
    assert read_res.json()["id"] == proj_id

    # 4. Update
    patch_res = client.patch(
        f"/api/v1/projects/{proj_id}",
        json={"name": "Transaction Engine v2", "description": "Updated description"},
        headers=dev_headers,
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["name"] == "Transaction Engine v2"

    # 5. Delete
    del_res = client.delete(f"/api/v1/projects/{proj_id}", headers=dev_headers)
    assert del_res.status_code == 204

    # 6. Verify 404 after delete
    get_after_del = client.get(f"/api/v1/projects/{proj_id}", headers=dev_headers)
    assert get_after_del.status_code == 404


def test_project_validation_and_not_found(client, dev_headers):
    # Blank name -> 422
    blank_name = client.post("/api/v1/projects", json={"name": "   "}, headers=dev_headers)
    assert blank_name.status_code == 422

    # Non-existent ID -> 404
    missing = client.get("/api/v1/projects/non-existent-id-12345", headers=dev_headers)
    assert missing.status_code == 404


def test_project_membership_management(client, pm_headers, dev_user, dev_headers):
    # PM creates project
    proj = client.post("/api/v1/projects", json={"name": "Shared Workspace"}, headers=pm_headers).json()
    proj_id = proj["id"]

    # Before adding, dev has no access
    assert client.get(f"/api/v1/projects/{proj_id}", headers=dev_headers).status_code == 403

    # PM adds dev as editor
    add_res = client.post(
        f"/api/v1/projects/{proj_id}/members?email={dev_user.email}&role=editor",
        headers=pm_headers,
    )
    assert add_res.status_code == 201

    # Dev now has access
    dev_view = client.get(f"/api/v1/projects/{proj_id}", headers=dev_headers)
    assert dev_view.status_code == 200

    # Invalid role -> 422
    invalid_role = client.post(
        f"/api/v1/projects/{proj_id}/members?email={dev_user.email}&role=superadmin",
        headers=pm_headers,
    )
    assert invalid_role.status_code == 422

    # Nonexistent user -> 404
    unknown_user = client.post(
        f"/api/v1/projects/{proj_id}/members?email=ghost@example.com&role=viewer",
        headers=pm_headers,
    )
    assert unknown_user.status_code == 404
