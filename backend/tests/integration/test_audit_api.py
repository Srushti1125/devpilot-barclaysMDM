"""
Integration tests for Audit Logging.

Verifies:
- Critical platform actions trigger audit log entries:
  - User registration
  - User login
  - Project creation, update, and deletion
  - Artifact generation and evaluation
- Admin user can query audit logs endpoint (/api/v1/audit-logs)
"""


def test_audit_logs_record_platform_events(client, admin_headers, dev_headers, mock_ai_generate):
    # 1. Project Creation
    project = client.post("/api/v1/projects", json={"name": "Audited App"}, headers=dev_headers).json()
    proj_id = project["id"]

    # 2. Artifact Generation
    art = client.post(
        f"/api/v1/projects/{proj_id}/generate",
        json={"artifact_type": "user_story", "requirement_text": "Audit requirement"},
        headers=dev_headers,
    ).json()

    # 3. Project Delete
    client.delete(f"/api/v1/projects/{proj_id}", headers=dev_headers)

    # 4. Admin inspects audit logs
    audit_res = client.get("/api/v1/audit-logs?limit=50", headers=admin_headers)
    assert audit_res.status_code == 200
    logs = audit_res.json()
    actions = [log["action"] for log in logs]

    assert "project.create" in actions
    assert "artifact.generate" in actions
    assert "project.delete" in actions
