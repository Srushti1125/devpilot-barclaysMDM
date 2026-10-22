"""
Latency measurement script (IMPLEMENTATION.draft.md §9 Sprint 7: P95 < 30s for standard
generation). Probes a running ai-engine end-to-end: ingestion job + N generation runs
through the full SOP loop (draft + judge + revisions included).

Usage (engine must be running with real keys + pgvector DB):
    python scripts/latency_probe.py --runs 5 --artifact-type user_story \
        [--base-url http://localhost:8001] [--project-id probe]
"""
import argparse
import json
import statistics
import sys
import time
import urllib.request
from pathlib import Path

SAMPLE_REQUIREMENT = (
    "Allow BFSI customers to reset their password via an OTP sent to their registered "
    "email. The OTP must expire in 5 minutes and allow at most 3 verification attempts."
)


def _post(url: str, payload: dict, timeout: float) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round(pct / 100 * (len(ordered) - 1)))))
    return ordered[idx]


def probe_ingest(base: str, project_id: str) -> float:
    """Time ingestion end to end (kickoff + poll to terminal). Returns wall seconds."""
    path = str(Path(__file__).parents[1] / "sample_docs" / "sample_requirements.txt")
    start = time.monotonic()
    accepted = _post(f"{base}/ingest", {"file_path": path, "project_id": project_id,
                                        "doc_type": "requirement"}, timeout=30)
    while True:
        with urllib.request.urlopen(f"{base}/ingest/{accepted['job_id']}", timeout=30) as r:
            state = json.loads(r.read())
        if state["status"] in ("done", "failed"):
            break
        time.sleep(2)
    return time.monotonic() - start


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default="http://localhost:8001")
    ap.add_argument("--project-id", default="perf-probe")
    ap.add_argument("--artifact-type", default="user_story")
    ap.add_argument("--runs", type=int, default=5)
    args = ap.parse_args()

    ingest_s = probe_ingest(args.base_url, args.project_id)
    print(f"ingest (incl. parse+index): {ingest_s:.1f}s")

    latencies, scores = [], []
    for i in range(args.runs):
        started = time.monotonic()
        try:
            result = _post(f"{args.base_url}/generate", {
                "project_id": args.project_id, "artifact_type": args.artifact_type,
                "requirement_text": SAMPLE_REQUIREMENT,
            }, timeout=120)
        except Exception as e:  # noqa: BLE001 - probe script: report and continue
            print(f"run {i + 1}: FAILED {e}")
            continue
        wall = time.monotonic() - started
        latencies.append(wall)
        scores.append(result.get("eval_score"))
        print(f"run {i + 1}: wall={wall:.1f}s reported={result['latency_ms']}ms "
              f"score={result.get('eval_score')} retries={result.get('retry_count')} "
              f"model={result.get('model_used')}")

    if not latencies:
        print("no successful runs")
        return 1
    p50 = percentile(latencies, 50)
    p95 = percentile(latencies, 95)
    print(f"\np50={p50:.1f}s p95={p95:.1f}s mean_score={statistics.mean(s for s in scores if s):.2f}")
    print("NFR (30s end-to-end, incl. revisions):", "PASS" if p95 < 30 else "FAIL")
    return 0


if __name__ == "__main__":
    sys.exit(main())
