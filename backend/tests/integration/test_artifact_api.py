"""
Integration tests for Artifact generation, management, evaluation, and export API.

Verifies:
- Generation endpoint triggers AI engine, persists artifact, records history (UC-02)
- Artifact updates increment version
- Evaluations can be added and listed (UC-09)
- Multi-format exports (JSON, Markdown, CSV, YAML) (UC-12)
- History recording and retrieval
"""

import json
import yaml


def test_generate_artifact_end_to_end(client, dev_headers, mock_ai_generate):
    # 1. Create project
    project = client.post("/api/v1/projects", json={"name": "Gen Project"}, headers=dev_headers).json()
    project_id = project["id"]

    # 2. Trigger generation
    gen_res = client.post(
        f"/api/v1/projects/{project_id}/generate",
        json={"artifact_type": "user_story", "requirement_text": "Users can reset passwords via email."},
        headers=dev_headers,
    )
    assert gen_res.status_code == 201
    artifact = gen_res.json()
    assert artifact["artifact_type"] == "user_story"
    assert artifact["version"] == 1
    assert "items" in artifact["content"]
    artifact_id = artifact["id"]

    # 3. Check history
    hist_res = client.get(f"/api/v1/projects/{project_id}/history", headers=dev_headers)
    assert hist_res.status_code == 200
    assert len(hist_res.json()) >= 1
    assert hist_res.json()[0]["engine_request_id"] == "test-req-123"

    # 4. Patch artifact
    patch_res = client.patch(
        f"/api/v1/artifacts/{artifact_id}",
        json={"title": "Updated User Story Title"},
        headers=dev_headers,
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["version"] == 2
    assert patch_res.json()["title"] == "Updated User Story Title"


def test_artifact_evaluation_flow(client, dev_headers, mock_ai_generate):
    project = client.post("/api/v1/projects", json={"name": "Eval Project"}, headers=dev_headers).json()
    artifact = client.post(
        f"/api/v1/projects/{project['id']}/generate",
        json={"artifact_type": "test_case", "requirement_text": "Transfer money"},
        headers=dev_headers,
    ).json()

    # Add evaluation
    eval_res = client.post(
        f"/api/v1/artifacts/{artifact['id']}/evaluations",
        json={"score": 5, "feedback": "Comprehensive edge case coverage", "metrics": {"accuracy": 0.92}},
        headers=dev_headers,
    )
    assert eval_res.status_code == 201
    assert eval_res.json()["score"] == 5

    # List evaluations
    list_res = client.get(f"/api/v1/artifacts/{artifact['id']}/evaluations", headers=dev_headers)
    assert list_res.status_code == 200
    assert len(list_res.json()) == 1


def test_artifact_export_multi_formats(client, dev_headers, mock_ai_generate):
    project = client.post("/api/v1/projects", json={"name": "Export Project"}, headers=dev_headers).json()
    artifact = client.post(
        f"/api/v1/projects/{project['id']}/generate",
        json={"artifact_type": "api_spec", "requirement_text": "OpenAPI specs"},
        headers=dev_headers,
    ).json()
    art_id = artifact["id"]

    # 1. JSON Export
    json_res = client.get(f"/api/v1/artifacts/{art_id}/export?format=json", headers=dev_headers)
    assert json_res.status_code == 200
    assert "application/json" in json_res.headers["content-type"]
    parsed_json = json.loads(json_res.text)
    assert parsed_json["id"] == art_id

    # 2. Markdown Export
    md_res = client.get(f"/api/v1/artifacts/{art_id}/export?format=markdown", headers=dev_headers)
    assert md_res.status_code == 200
    assert "text/markdown" in md_res.headers["content-type"]
    assert "# " in md_res.text

    # 3. CSV Export
    csv_res = client.get(f"/api/v1/artifacts/{art_id}/export?format=csv", headers=dev_headers)
    assert csv_res.status_code == 200
    assert "text/csv" in csv_res.headers["content-type"]
    assert art_id in csv_res.text

    # 4. YAML Export
    yaml_res = client.get(f"/api/v1/artifacts/{art_id}/export?format=yaml", headers=dev_headers)
    assert yaml_res.status_code == 200
    assert "application/x-yaml" in yaml_res.headers["content-type"]
    parsed_yaml = yaml.safe_load(yaml_res.text)
    assert parsed_yaml["id"] == art_id
