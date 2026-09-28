"""
Contract tests verifying OpenAPI specification compatibility and schema integrity.

Verifies:
- OpenAPI 3.x schema generation via /openapi.json
- Key endpoints are registered in the specification
- Core schemas (User, Project, Artifact) are defined under components.schemas
"""


def test_openapi_schema_generation(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200

    schema = response.json()
    assert "openapi" in schema
    assert "paths" in schema
    assert "components" in schema

    paths = schema["paths"]
    # Verify core endpoints exist
    assert "/api/v1/auth/register" in paths
    assert "/api/v1/auth/login" in paths
    assert "/api/v1/projects" in paths
    assert "/api/v1/artifacts/{artifact_id}/export" in paths
    assert "/health" in paths
    assert "/health/db" in paths
    assert "/health/ai" in paths


def test_openapi_schemas_components(client):
    response = client.get("/openapi.json")
    schema = response.json()
    schemas = schema.get("components", {}).get("schemas", {})

    expected_schemas = ["UserCreate", "UserOut", "ProjectCreate", "ProjectOut", "ArtifactOut"]
    for s in expected_schemas:
        assert s in schemas, f"Expected schema '{s}' to be documented in OpenAPI components"
