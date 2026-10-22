"""
Integration tests for Requirement Ingestion API endpoints (UC-01).

Verifies:
- File uploads with supported extensions (.txt, .md, .pdf, .docx)
- Rejection of unsupported file extensions (415)
- Enforcement of file size limits (413 on >10MB)
- Storage and persistence of parsed requirement content
- Requirement detail and list retrieval
"""

import io


def test_ingest_requirement_text_file(client, dev_headers, mock_ai_ingest):
    """§2.2.4: upload acknowledges with 202 + job; polling the job finalizes indexing."""
    # Create project
    project = client.post("/api/v1/projects", json={"name": "Banking Spec"}, headers=dev_headers).json()
    project_id = project["id"]

    file_content = b"The core banking system must process SEPA credit transfers within 10 seconds."
    files = {"file": ("requirements.txt", io.BytesIO(file_content), "text/plain")}

    response = client.post(
        f"/api/v1/projects/{project_id}/requirements",
        files=files,
        data={"doc_type": "requirement"},
        headers=dev_headers,
    )

    assert response.status_code == 202
    data = response.json()
    assert data["filename"] == "requirements.txt"
    assert data["project_id"] == project_id
    assert data["status"] == "processing"
    job = client.get(f"/api/v1/ingest-jobs/{data['ingest_job_id']}", headers=dev_headers).json()
    assert job["status"] == "done"
    assert job["chunks_indexed"] == 5
    assert job["requirement_id"] == data["id"]

    # Verify requirement appears in list with indexed chunks
    req_list = client.get(f"/api/v1/projects/{project_id}/requirements", headers=dev_headers)
    assert req_list.status_code == 200
    assert len(req_list.json()) == 1
    assert req_list.json()[0]["chunks_indexed"] == 5


def test_ingest_unsupported_file_type_rejected(client, dev_headers):
    project = client.post("/api/v1/projects", json={"name": "Malware Guard"}, headers=dev_headers).json()

    files = {"file": ("malicious.exe", io.BytesIO(b"MZ\x90\x00"), "application/octet-stream")}
    response = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        files=files,
        headers=dev_headers,
    )
    assert response.status_code == 415
    assert "unsupported" in response.json()["detail"].lower()


def test_ingest_oversized_file_rejected(client, dev_headers):
    project = client.post("/api/v1/projects", json={"name": "Large Doc Test"}, headers=dev_headers).json()

    # 10MB + 10 bytes
    large_payload = b"A" * (10 * 1024 * 1024 + 10)
    files = {"file": ("massive_spec.txt", io.BytesIO(large_payload), "text/plain")}

    response = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        files=files,
        headers=dev_headers,
    )
    assert response.status_code == 413


def test_read_requirement_detail(client, dev_headers, mock_ai_ingest):
    project = client.post("/api/v1/projects", json={"name": "Requirement View"}, headers=dev_headers).json()
    project_id = project["id"]

    content = b"# Specification\nAll APIs must return ISO 8601 timestamps."
    files = {"file": ("api_rules.md", io.BytesIO(content), "text/markdown")}

    ingested = client.post(
        f"/api/v1/projects/{project_id}/requirements",
        files=files,
        headers=dev_headers,
    ).json()
    req_id = ingested["id"]

    detail = client.get(f"/api/v1/requirements/{req_id}", headers=dev_headers)
    assert detail.status_code == 200
    assert detail.json()["filename"] == "api_rules.md"
    assert "ISO 8601" in detail.json()["content"]


def test_ingest_persists_tree_nodes_on_job_completion(client, dev_headers, mock_ai_ingest, db_session):
    """Tree nodes from the finished engine job are stored under the requirement, parents preserved."""
    from app.domain.models import DocTreeNode

    project = client.post("/api/v1/projects", json={"name": "Tree Spec"}, headers=dev_headers).json()
    project_id = project["id"]
    files = {"file": ("reqs.md", io.BytesIO(b"# 1 Authentication\n## 1.1 Password Reset\nOTP."), "text/markdown")}
    response = client.post(f"/api/v1/projects/{project_id}/requirements", files=files,
                           data={"doc_type": "requirement"}, headers=dev_headers)
    assert response.status_code == 202
    requirement_id = response.json()["id"]

    # Nodes land only after the job completes; polling is the trigger (§2.2.4/§6.2).
    before = db_session.query(DocTreeNode).filter(DocTreeNode.doc_id == requirement_id).count()
    assert before == 0
    job = client.get(f"/api/v1/ingest-jobs/{response.json()['ingest_job_id']}", headers=dev_headers)
    assert job.status_code == 200
    assert job.json()["status"] == "done"

    rows = {r.id: r for r in db_session.query(DocTreeNode).filter(DocTreeNode.doc_id == requirement_id).all()}
    assert set(rows) == {"n-root", "n-child"}
    assert rows["n-child"].parent_id == "n-root"
    assert rows["n-child"].project_id == project_id
    assert rows["n-child"].text == "Reset via OTP."
    assert rows["n-root"].content_hash == "c" * 64

    # Re-polling a done job does not duplicate rows (idempotent finalization).
    client.get(f"/api/v1/ingest-jobs/{job.json()['id']}", headers=dev_headers)
    assert db_session.query(DocTreeNode).filter(DocTreeNode.doc_id == requirement_id).count() == 2


def test_ingest_job_failure_is_recorded(client, dev_headers, mock_ai_ingest_failed):
    project = client.post("/api/v1/projects", json={"name": "Fail Spec"}, headers=dev_headers).json()
    files = {"file": ("broken.pdf", io.BytesIO(b"%PDF-1.4 broken"), "application/pdf")}
    response = client.post(f"/api/v1/projects/{project['id']}/requirements", files=files, headers=dev_headers)
    assert response.status_code == 202

    job = client.get(f"/api/v1/ingest-jobs/{response.json()['ingest_job_id']}", headers=dev_headers).json()
    assert job["status"] == "failed"
    assert "unsupported" in job["error_message"]
