import logging

from langchain_core.runnables import RunnableLambda

from app.config import settings
from app.llm.parsers import get_parser
from app.llm.provider import get_llm
from app.pipeline.quality_check import generate_with_quality_check
from app.prompts.registry import load_prompt
from app.retrieval import tree_store
from app.retrieval.hybrid import RetrievalResult, hybrid_retrieve
from app.retrieval.reranker import with_reranking
from app.retrieval.retriever import get_retriever

logger = logging.getLogger("devpilot.chain")

NO_CONTEXT = "(no matching context retrieved for this project)"


def _format_docs(docs) -> str:
    if not docs:
        return NO_CONTEXT
    return "\n\n".join(d.page_content for d in docs)


def _tree_select(project_id: str, requirement_text: str, doc_type: str) -> list[str]:
    """Tree leg: load the outline, ask the selector LLM, return validated node ids."""
    from app.llm.provider import get_llm
    from app.retrieval import tree_store
    from app.retrieval.tree_search import select_with_cache

    outline = tree_store.load_outline(project_id, doc_type)
    llm = get_llm(settings.DEFAULT_LLM, temperature=0.0)

    def ask(prompt: str) -> str:
        out = llm.invoke(prompt)
        return out.content if hasattr(out, "content") else str(out)

    return select_with_cache(
        project_id, outline, requirement_text, ask,
        token_budget=settings.TREE_SELECT_TOKEN_BUDGET,
        concurrency=settings.TREE_CONCURRENCY,
        acquire_timeout=settings.TREE_TIMEOUT_S,
    )


def retrieve_context(
    project_id: str,
    requirement_text: str,
    doc_type: str | None = "requirement",
) -> RetrievalResult:
    """
    Single retrieval call per generation request. Callers run this ONCE and pass the context into
    every chain/revision, so retries and fallbacks never re-query the stores.
    RETRIEVAL_MODE=vector (default) keeps the original MMR behaviour; "hybrid" adds the tree leg.
    """
    dt = doc_type or "requirement"

    def vector_search():
        # Cohere rerank wraps the retriever only when COHERE_API_KEY is set (§2.2.3);
        # without it, with_reranking returns the base retriever unchanged.
        return with_reranking(get_retriever(project_id, doc_type=doc_type)).invoke(requirement_text)

    if settings.RETRIEVAL_MODE != "hybrid":
        docs = vector_search()
        return RetrievalResult(context=_format_docs(docs),
                               trace={"mode": "vector", "vector_hits": len(docs)})

    return hybrid_retrieve(
        vector_search=vector_search,
        tree_select=lambda: _tree_select(project_id, requirement_text, dt),
        load_nodes=lambda ids: tree_store.load_node_texts(project_id, ids),
        vector_timeout_s=settings.VECTOR_TIMEOUT_S,
        tree_timeout_s=settings.TREE_TIMEOUT_S,
        context_token_budget=settings.RETRIEVAL_CONTEXT_TOKENS,
    )


def build_generation_chain(
    artifact_type: str,
    schema_cls,
    model_alias: str | None = None,
):
    """
    Prompt | LLM chain. Context is an input, not fetched here, so building or
    invoking the chain performs no retrieval.

    Expected input keys: requirement, context, repair_note (optional).
    """
    prompt, version_id = load_prompt(artifact_type)
    llm = get_llm(model_alias)
    parser = get_parser(schema_cls)

    def _inputs(x: dict) -> dict:
        if "context" not in x:
            raise KeyError("build_generation_chain requires precomputed 'context' (see retrieve_context)")
        return {
            "requirement": x["requirement"],
            "context": x["context"],
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

    # Retrieval happens exactly once; primary and fallback chains share the same context.
    retrieval = retrieve_context(project_id, requirement_text)
    context = retrieval.context

    chain, parser, version_id = build_generation_chain(artifact_type, schema_cls)

    fallback_chain = None
    if settings.FALLBACK_LLM and settings.FALLBACK_LLM != settings.DEFAULT_LLM:
        try:
            fallback_chain, _, _ = build_generation_chain(
                artifact_type, schema_cls, model_alias=settings.FALLBACK_LLM
            )
        except Exception as e:  # missing key etc. must not block the primary path
            logger.warning("Fallback LLM '%s' unavailable: %s", settings.FALLBACK_LLM, e)

    result, raw = generate_with_quality_check(
        chain,
        {"requirement": requirement_text, "context": context},
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
        "retrieval": retrieval.trace,
        "usage": {
            "prompt_tokens": usage.get("input_tokens", 0),
            "completion_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
            "total_cost_usd": 0.0,  # free tier
        },
    }
