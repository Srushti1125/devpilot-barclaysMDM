"""
Artifact-level auditor — Layer 3 (IMPLEMENTATION.draft.md §4.2).

Diffs AI output against a human golden baseline at field level.
Pattern source: https://github.com/amitgambhir/rag-auditor (MIT)
Used by the Case Study module (UC-10) to demonstrate 70%+ accuracy.
"""
from __future__ import annotations

import json
from difflib import SequenceMatcher


def audit_artifact(ai_output: dict, golden_output: dict, artifact_type: str) -> dict:
    ai_text = json.dumps(ai_output, sort_keys=True)
    gold_text = json.dumps(golden_output, sort_keys=True)
    similarity = SequenceMatcher(None, ai_text, gold_text).ratio()

    field_scores = {}
    for key in set(ai_output) | set(golden_output):
        a = json.dumps(ai_output.get(key, ""), sort_keys=True)
        g = json.dumps(golden_output.get(key, ""), sort_keys=True)
        field_scores[key] = round(SequenceMatcher(None, a, g).ratio(), 3)

    return {
        "artifact_type": artifact_type,
        "overall_similarity": round(similarity, 3),
        "field_scores": field_scores,
        "passes_70pct_threshold": similarity >= 0.70,
    }
