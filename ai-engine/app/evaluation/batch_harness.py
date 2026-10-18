import json
import time
from pathlib import Path

GOLDEN_PATH = Path(__file__).parents[2] / "eval_data" / "golden.jsonl"
REPORT_PATH = Path(__file__).parents[2] / "eval_data" / "eval_report.json"

REQUIRED_ROW_KEYS = {"artifact_type", "question", "ground_truth", "project_id"}


def load_golden_rows(path: Path | None = None) -> list[dict]:
    """Warning W-5: golden.jsonl must be committed; harness fails loudly if absent."""
    p = path or GOLDEN_PATH
    if not p.exists():
        raise FileNotFoundError(f"Golden dataset missing at {p}. Commit ai-engine/eval_data/golden.jsonl (W-5).")
    rows = []
    for i, line in enumerate(p.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        missing = REQUIRED_ROW_KEYS - row.keys()
        if missing:
            raise ValueError(f"golden.jsonl line {i} missing keys: {sorted(missing)}")
        rows.append(row)
    return rows


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round(pct / 100 * (len(ordered) - 1)))))
    return ordered[idx]


def _flatten_output(output: dict) -> str:
    """Collapse a structured artifact to its human-readable text for baseline diffing.
    rag-auditor compares field-level similarity; golden baselines are prose."""
    parts: list[str] = []

    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, str):
            parts.append(x)

    walk(output)
    return " ".join(parts)


def run_batch_eval(project_id: str | None = None, retrieval_mode: str = "vector",
                   use_ragas: bool = True, limit: int | None = None,
                   report_path: Path | None = None) -> dict:
    """
    Layer 2 offline evaluation (§4.2): regenerate every golden example through the SOP
    graph under a fixed retrieval mode (§2.3.6), score with RAGAS, and report latency
    percentiles + tree fallback rate. Ragas needs live model keys; set use_ragas=False
    for keyless CI smoke runs.
    """
    from app.config import settings
    from app.evaluation.auditor import audit_artifact
    from app.pipeline.sop_graph import run_sop_generation
    from app.schemas.registry import get_schema

    rows = load_golden_rows()
    if limit:
        rows = rows[:limit]

    original_mode = settings.RETRIEVAL_MODE
    settings.RETRIEVAL_MODE = retrieval_mode
    output_rows, latencies, fallbacks, audits = [], [], [], []
    try:
        for row in rows:
            pid = project_id or row.get("project_id", "eval")
            schema_cls = get_schema(row["artifact_type"])
            start = time.monotonic()
            result = run_sop_generation(row["artifact_type"], pid, row["question"], schema_cls)
            latencies.append((time.monotonic() - start) * 1000)
            trace = result.get("retrieval") or {}
            if trace.get("fallback"):
                fallbacks.append(trace["fallback"])
            audits.append(audit_artifact(
                {"text": _flatten_output(result["output"])},
                {"text": row["ground_truth"]},
                row["artifact_type"],
            )["overall_similarity"])
            output_rows.append({
                "question": row["question"],
                "answer": json.dumps(result["output"]),
                "contexts": [result.get("context") or ""],
                "ground_truth": row["ground_truth"],
            })
    finally:
        settings.RETRIEVAL_MODE = original_mode

    report: dict = {
        "retrieval_mode": retrieval_mode,
        "n_examples": len(rows),
        "latency_ms": {"p50": round(_percentile(latencies, 50), 1),
                       "p95": round(_percentile(latencies, 95), 1)},
        "tree_fallback_rate": round(len(fallbacks) / max(1, len(rows)), 3),
        "auditor_mean_similarity": round(sum(audits) / max(1, len(audits)), 3),
        "auditor_pass_70pct": sum(1 for a in audits if a >= 0.70),
    }

    if use_ragas:
        from datasets import Dataset
        from ragas import evaluate
        from ragas.embeddings import LangchainEmbeddingsWrapper
        from ragas.llms import LangchainLLMWrapper
        from ragas.metrics import answer_relevancy, context_recall, faithfulness

        from app.llm.provider import get_llm
        from app.retrieval.vectorstore import get_embeddings

        # RAGAS runs on the same provider layer as generation — model-agnostic by design.
        ds = Dataset.from_list(output_rows)
        scores = evaluate(
            ds,
            metrics=[faithfulness, answer_relevancy, context_recall],
            llm=LangchainLLMWrapper(get_llm(settings.EVAL_JUDGE_LLM, temperature=0.0)),
            embeddings=LangchainEmbeddingsWrapper(get_embeddings()),
        )
        report["ragas"] = scores.to_pandas().mean(numeric_only=True).to_dict()

    out = report_path or REPORT_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    return report
