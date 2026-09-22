import json
import re

from langchain_core.exceptions import OutputParserException

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _strip_code_fences(text: str) -> str:
    return _CODE_FENCE_RE.sub("", text).strip()


def _extract_text(raw) -> str:
    return raw.content if hasattr(raw, "content") else str(raw)


def generate_with_quality_check(
    chain,
    inputs: dict,
    parser,
    max_retries: int = 2,
    fallback_chain=None,
):
    last_error = None
    attempt_inputs = dict(inputs)
    attempt_inputs.setdefault("repair_note", "")

    for attempt in range(max_retries):
        try:
            raw = chain.invoke(attempt_inputs)
            text = _strip_code_fences(_extract_text(raw))
            parsed = parser.parse(text)
            return parsed, raw
        except (OutputParserException, ValueError, json.JSONDecodeError) as e:
            last_error = e
            attempt_inputs["repair_note"] = (
                f"Your previous output was invalid: {e}. "
                f"Fix it and respond with ONLY the corrected JSON, no markdown fences."
            )

    if fallback_chain is not None:
        try:
            raw = fallback_chain.invoke(attempt_inputs)
            text = _strip_code_fences(_extract_text(raw))
            parsed = parser.parse(text)
            return parsed, raw
        except (OutputParserException, ValueError, json.JSONDecodeError) as e:
            last_error = e

    raise RuntimeError(f"Generation failed after {max_retries} retries: {last_error}")


def consistency_score(output_a: dict, output_b: dict) -> float:
    keys = set(output_a.keys()) | set(output_b.keys())
    if not keys:
        return 1.0
    matches = sum(1 for k in keys if output_a.get(k) == output_b.get(k))
    return matches / len(keys)


def format_compliance_score(raw_text: str, schema_cls) -> bool:
    from app.llm.parsers import get_parser
    try:
        get_parser(schema_cls).parse(_strip_code_fences(raw_text))
        return True
    except Exception:
        return False
