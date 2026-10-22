"""
§2.3.6 ship run: compare vector-only vs hybrid retrieval on the golden set.

Writes eval_data/eval_report_<mode>.json per mode (latency p50/p95 across the FULL SOP
workflow including revisions, tree fallback rate, auditor similarity, RAGAS scores).
Keeps RETRIEVAL_MODE defaults untouched — the harness passes the mode explicitly.

Run from ai-engine/ (needs live keys + DB; corpus seeded first):
    PYTHONPATH=. python scripts/prepare_eval_corpus.py
    PYTHONPATH=. python scripts/run_ship_eval.py --limit 50 --modes vector hybrid
"""
import argparse
import json
from pathlib import Path

from app.evaluation.batch_harness import run_batch_eval


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="rows per mode (default: all 50)")
    parser.add_argument("--modes", nargs="+", default=["vector", "hybrid"])
    parser.add_argument("--no-ragas", action="store_true", help="skip RAGAS (429-prone on free tier)")
    args = parser.parse_args()

    out_dir = Path(__file__).parents[1] / "eval_data"
    summaries = {}
    for mode in args.modes:
        print(f"=== ship run: mode={mode} limit={args.limit}", flush=True)
        report = run_batch_eval(
            retrieval_mode=mode,
            use_ragas=not args.no_ragas,
            limit=args.limit,
            report_path=out_dir / f"eval_report_{mode}.json",
        )
        summaries[mode] = report
        print(json.dumps(report, indent=2), flush=True)

    if len(summaries) == 2:
        a, b = summaries.values()
        print("=== comparison ===")
        print(f"auditor mean similarity : {a['auditor_mean_similarity']} vs {b['auditor_mean_similarity']}")
        print(f"auditor pass>=70%       : {a['auditor_pass_70pct']} vs {b['auditor_pass_70pct']}")
        print(f"latency p50 ms          : {a['latency_ms']['p50']} vs {b['latency_ms']['p50']}")
        print(f"latency p95 ms          : {a['latency_ms']['p95']} vs {b['latency_ms']['p95']}")
        print(f"tree fallback rate      : {a['tree_fallback_rate']} vs {b['tree_fallback_rate']}")


if __name__ == "__main__":
    main()
