import json
import logging
import re

from langchain_core.exceptions import OutputParserException

logger = logging.getLogger("devpilot.quality")

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _strip_code_fences(text: str) -> str:
    return _CODE_FENCE_RE.sub("", text).strip()


def _extract_text(raw) -> str:
    return raw.content if hasattr(raw, "content") else str(raw)


_PARSE_ERRORS = (OutputParserException, ValueError, json.JSONDecodeError)


def generate_with_quality_check(
    chain,
    inputs: dict,
    parser,
    max_retries: int = 2,
    fallback_chain=None,
):
    """
    Primary chain (e.g. Groq) with parse-repair retries, then fallback chain (e.g. Gemini).

    - Parse/validation errors: retry the primary with a repair note.
    - Provider errors (rate limit, outage, auth, timeout): skip remaining primary retries
      and go straight to the fallback. Retrying a failing provider wastes latency budget.
    """
    last_error = None
    attempt_inputs = dict(inputs)
    attempt_inputs.setdefault("repair_note", "")

    for _ in range(max_retries):
        try:
            raw = chain.invoke(attempt_inputs)
            text = _strip_code_fences(_extract_text(raw))
            parsed = parser.parse(text)
            return parsed, raw
        except _PARSE_ERRORS as e:
            last_error = e
            attempt_inputs["repair_note"] = (
                f"Your previous output was invalid: {e}. "
                f"Fix it and respond with ONLY the corrected JSON, no markdown fences."
            )
        except Exception as e:  # provider-side failure
            last_error = e
            logger.warning("Primary LLM failed (%s: %s); switching to fallback.",
                           type(e).__name__, e)
            break

    if fallback_chain is not None:
        try:
            raw = fallback_chain.invoke(attempt_inputs)
            text = _strip_code_fences(_extract_text(raw))
            parsed = parser.parse(text)
            return parsed, raw
        except Exception as e:
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
