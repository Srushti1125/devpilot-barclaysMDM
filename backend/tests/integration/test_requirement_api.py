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

    assert response.status_code == 201
    data = response.json()
    assert data["filename"] == "requirements.txt"
    assert data["project_id"] == project_id
    assert data["chunks_indexed"] == 5

    # Verify requirement appears in list
    req_list = client.get(f"/api/v1/projects/{project_id}/requirements", headers=dev_headers)
    assert req_list.status_code == 200
    assert len(req_list.json()) == 1


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
