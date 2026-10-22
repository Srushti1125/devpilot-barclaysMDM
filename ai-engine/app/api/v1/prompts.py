"""
Prompt template management endpoints.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.pipeline.chain import build_generation_chain, retrieve_context
from app.pipeline.sop_graph import _extract_text
from app.prompts.registry import PROMPT_DIR, list_artifact_types, list_versions, load_prompt
from app.schemas.registry import SCHEMA_REGISTRY
from app.schemas.registry import get_schema

router = APIRouter(tags=["Prompts"])


class PromptWriteRequest(BaseModel):
    system: str = Field(min_length=1, max_length=20000)
    human: str = Field(min_length=1, max_length=20000)
    version_id: str | None = Field(default=None, min_length=1, max_length=100)


class PromptTestRequest(BaseModel):
    version: str = "latest"
    requirement_text: str = Field(min_length=1, max_length=20000)


@router.get("/prompts")
def list_prompts():
    return {"artifact_types": {name: list_versions(name) for name in list_artifact_types()}}


@router.get("/prompts/{artifact_type}")
def read_prompt(artifact_type: str, version: str = "latest"):
    if artifact_type not in list_artifact_types():
        raise HTTPException(status_code=404, detail="Prompt type not found")
    versions = list_versions(artifact_type)
    selected = f"v{max((int(v[1:]) for v in versions), default=0)}" if version == "latest" else version
    if selected not in versions:
        raise HTTPException(status_code=404, detail="Prompt version not found")
    import yaml
    path = PROMPT_DIR / artifact_type / f"{selected}.yaml"
    spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {"artifact_type": artifact_type, "version_id": spec.get("version_id"),
            "version_file": selected, "spec": spec}


@router.post("/prompts/{artifact_type}", status_code=201)
def create_prompt_version(artifact_type: str, payload: PromptWriteRequest):
    if artifact_type not in SCHEMA_REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown artifact type")
    versions = list_versions(artifact_type)
    next_version = max((int(value[1:]) for value in versions), default=0) + 1
    version_file = f"v{next_version}"
    version_id = payload.version_id or f"{artifact_type}_{version_file}"
    destination = PROMPT_DIR / artifact_type / f"{version_file}.yaml"
    import yaml
    destination.write_text(yaml.safe_dump({"version_id": version_id,
        "system": payload.system, "human": payload.human}, sort_keys=False), encoding="utf-8")
    return {"artifact_type": artifact_type, "version_id": version_id,
            "version_file": version_file}


@router.post("/prompts/{artifact_type}/test")
def test_prompt(artifact_type: str, payload: PromptTestRequest):
    if artifact_type not in SCHEMA_REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown artifact type")
    try:
        _, version_id = load_prompt(artifact_type, payload.version)
        schema_cls = get_schema(artifact_type)
        retrieval = retrieve_context("prompt_test", payload.requirement_text)
        chain, _, _ = build_generation_chain(artifact_type, schema_cls,
                                              prompt_version=payload.version)
        raw = chain.invoke({"requirement": payload.requirement_text,
                            "context": retrieval.context, "repair_note": ""})
        return {"version_id": version_id, "raw_output": _extract_text(raw),
                "retrieval_mode": retrieval.trace.get("mode")}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger = __import__("logging").getLogger("devpilot.ai_engine")
        logger.exception("Prompt test failed")
        raise HTTPException(status_code=502, detail="Prompt test generation failed") from exc
