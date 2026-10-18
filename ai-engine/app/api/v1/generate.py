"""
SOP generation, streaming, comparison, and batch evaluation endpoints.
"""

import asyncio
import json
import logging
import time
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.config import settings
from app.pipeline import sop_graph
from app.schemas.registry import SCHEMA_REGISTRY, get_schema
from app.tracking.usage import record_request

logger = logging.getLogger("devpilot.ai_engine")

router = APIRouter(tags=["Generate"])


class GenerateRequest(BaseModel):
    project_id: str
    artifact_type: str = Field(description=f"One of: {sorted(SCHEMA_REGISTRY.keys())}")
    requirement_text: str


class GenerateResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    request_id: str
    artifact_type: str
    project_id: str
    prompt_version: str
    output: dict
    usage: dict
    latency_ms: int
    retrieval: dict | None = None
    eval_score: float | None = None
    retry_count: int = 0
    model_used: str | None = None


def _checked_schema(artifact_type: str):
    try:
        return get_schema(artifact_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _sse(payload) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"


@router.post("/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest):
    schema_cls = _checked_schema(req.artifact_type)

    quota_state = record_request()
    if quota_state["quota_exceeded"]:
        logger.warning("Proceeding despite exceeded quota guardrail (soft limit, not enforced).")

    request_id = str(uuid.uuid4())
    start = time.monotonic()
    try:
        result = sop_graph.run_sop_generation(req.artifact_type, req.project_id, req.requirement_text, schema_cls)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=f"LLM generation failed validation: {e}")
    except Exception as e:
        logger.exception("Generation failed for project_id=%s artifact_type=%s", req.project_id, req.artifact_type)
        raise HTTPException(status_code=500, detail=f"Generation failed: {e}")

    latency_ms = int((time.monotonic() - start) * 1000)

    return GenerateResponse(
        request_id=request_id,
        artifact_type=result["artifact_type"],
        project_id=result["project_id"],
        prompt_version=result["prompt_version"],
        output=result["output"],
        usage=result["usage"],
        latency_ms=latency_ms,
        retrieval=result.get("retrieval"),
        eval_score=result.get("eval_score"),
        retry_count=result.get("retry_count", 0),
        model_used=result.get("model_used"),
    )


@router.post("/generate/stream")
async def generate_stream(req: GenerateRequest):
    """SSE stream of SOP node transitions (§3.2.4)."""
    schema_cls = _checked_schema(req.artifact_type)
    record_request()

    async def event_stream():
        accumulated = {
            "artifact_type": req.artifact_type, "project_id": req.project_id,
            "requirement_text": req.requirement_text, "model_alias": settings.DEFAULT_LLM,
            "context": "", "retrieval_trace": {}, "draft_raw": "", "eval_score": 0.0,
            "critique": "", "retry_count": 0, "final_artifact": {}, "prompt_version": "",
            "usage": {}, "model_used": "",
        }
        request_id = str(uuid.uuid4())
        start = time.monotonic()
        try:
            async for update in sop_graph.SOP_GRAPH.astream(accumulated, stream_mode="updates"):
                for node, delta in update.items():
                    if isinstance(delta, dict):
                        accumulated.update(delta)
                    yield _sse({"node": node,
                                "retry": accumulated["retry_count"],
                                "eval_score": accumulated.get("eval_score"),
                                "critique": (delta or {}).get("critique", "") if isinstance(delta, dict) else ""})
        except Exception as e:
            logger.exception("Streaming generation failed")
            yield _sse({"error": str(e)})
            yield "data: [DONE]\n\n"
            return

        yield _sse({"node": "done", "result": GenerateResponse(
            request_id=request_id,
            artifact_type=req.artifact_type,
            project_id=req.project_id,
            prompt_version=accumulated.get("prompt_version", ""),
            output=accumulated.get("final_artifact", {}),
            usage=accumulated.get("usage", {}),
            latency_ms=int((time.monotonic() - start) * 1000),
            retrieval=accumulated.get("retrieval_trace"),
            eval_score=accumulated.get("eval_score"),
            retry_count=accumulated.get("retry_count", 0),
            model_used=accumulated.get("model_used"),
        ).model_dump()})
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/generate/compare")
async def generate_compare(req: GenerateRequest):
    """Sprint the same requirement through DEFAULT_LLM and FALLBACK_LLM concurrently."""
    schema_cls = _checked_schema(req.artifact_type)
    record_request()

    async def _run(alias: str):
        try:
            return await asyncio.to_thread(
                sop_graph.run_sop_generation, req.artifact_type, req.project_id, req.requirement_text,
                schema_cls, alias,
            )
        except Exception as e:
            return {"error": str(e), "model_alias": alias}

    primary, fallback = await asyncio.gather(
        _run(settings.DEFAULT_LLM), _run(settings.FALLBACK_LLM),
    )
    return {"primary": primary, "fallback": fallback}


@router.post("/evaluate/batch")
async def evaluate_batch(project_id: str | None = None, retrieval_mode: str = "vector"):
    """Offline RAGAS harness (§4.2 Layer 2)."""
    from app.evaluation.batch_harness import run_batch_eval

    if retrieval_mode not in ("vector", "hybrid"):
        raise HTTPException(status_code=400, detail="retrieval_mode must be vector|hybrid")
    try:
        return await asyncio.to_thread(run_batch_eval, project_id, retrieval_mode)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=f"Evaluation prerequisites missing: {e}")
