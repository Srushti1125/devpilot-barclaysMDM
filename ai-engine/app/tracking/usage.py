import logging
import threading
from datetime import date

from app.config import settings

logger = logging.getLogger("devpilot.ai_engine.usage")

_lock = threading.Lock()
_state = {"day": date.today(), "count": 0}


def record_request() -> dict:
    with _lock:
        today = date.today()
        if _state["day"] != today:
            _state["day"] = today
            _state["count"] = 0
        _state["count"] += 1
        count = _state["count"]

    quota_exceeded = count > settings.DAILY_REQUEST_QUOTA
    if quota_exceeded:
        logger.warning(
            "Gemini free-tier daily request quota likely exceeded: "
            "%d requests today (quota=%d). Consider FALLBACK_LLM or Mistral fallback.",
            count, settings.DAILY_REQUEST_QUOTA,
        )
    elif count == int(settings.DAILY_REQUEST_QUOTA * 0.9):
        logger.warning(
            "Approaching Gemini free-tier daily request quota: %d/%d requests today.",
            count, settings.DAILY_REQUEST_QUOTA,
        )

    return {"requests_today": count, "quota": settings.DAILY_REQUEST_QUOTA, "quota_exceeded": quota_exceeded}


def build_usage_record(usage_metadata: dict | None) -> dict:
    usage_metadata = usage_metadata or {}
    return {
        "prompt_tokens": usage_metadata.get("input_tokens", 0),
        "completion_tokens": usage_metadata.get("output_tokens", 0),
        "total_tokens": usage_metadata.get("total_tokens", 0),
        "total_cost_usd": 0.0,  # free tier -> track requests/tokens against quota instead
    }
