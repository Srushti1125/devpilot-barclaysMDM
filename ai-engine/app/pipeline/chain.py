from langchain_core.runnables import RunnableLambda

from app.config import settings
from app.llm.parsers import get_parser
from app.llm.provider import get_llm
from app.pipeline.quality_check import generate_with_quality_check
from app.prompts.registry import load_prompt
from app.retrieval.retriever import get_retriever


def _format_docs(docs) -> str:
    if not docs:
        return "(no matching context retrieved for this project)"
    return "\n\n".join(d.page_content for d in docs)


def build_generation_chain(
    artifact_type: str,
    project_id: str,
    schema_cls,
    model_alias: str | None = None,
    doc_type: str | None = "requirement",
):

    retriever = get_retriever(project_id, doc_type=doc_type)
    prompt, version_id = load_prompt(artifact_type)
    llm = get_llm(model_alias)
    parser = get_parser(schema_cls)

    def _inputs(x: dict) -> dict:
        requirement_text = x["requirement"]
        docs = retriever.invoke(requirement_text)
        return {
            "requirement": requirement_text,
            "context": _format_docs(docs),
            "repair_note": x.get("repair_note", ""),
            "format_instructions": parser.get_format_instructions(),
        }

    rag_chain = RunnableLambda(_inputs) | prompt | llm
    return rag_chain, parser, version_id


def run_generation(
    artifact_type: str,
    project_id: str,
    requirement_text: str,
    schema_cls,
    max_retries: int = 2,
) -> dict:

    chain, parser, version_id = build_generation_chain(artifact_type, project_id, schema_cls)

    fallback_chain = None
    if settings.FALLBACK_LLM and settings.FALLBACK_LLM != settings.DEFAULT_LLM:
        fallback_chain, _, _ = build_generation_chain(
            artifact_type, project_id, schema_cls, model_alias=settings.FALLBACK_LLM
        )

    result, raw = generate_with_quality_check(
        chain,
        {"requirement": requirement_text},
        parser,
        max_retries=max_retries,
        fallback_chain=fallback_chain,
    )

    usage = getattr(raw, "usage_metadata", None) or {}

    return {
        "artifact_type": artifact_type,
        "project_id": project_id,
        "prompt_version": version_id,
        "output": result.model_dump(),
        "usage": {
            "prompt_tokens": usage.get("input_tokens", 0),
            "completion_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
            "total_cost_usd": 0.0,  # free tier
        },
    }
