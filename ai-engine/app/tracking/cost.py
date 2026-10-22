"""Configurable approximate token cost estimate in USD."""

import os

# USD per million input/output tokens; override by deployment when prices change.
_USD_PER_MILLION = {
    "gemini": (0.25, 0.50), "groq": (0.05, 0.08), "mistral": (0.20, 0.60),
    "openai": (3.00, 6.00), "ollama": (0.0, 0.0),
}


def estimate_cost_usd(model_alias: str, prompt_tokens: int, completion_tokens: int) -> float:
    prefix = (model_alias or "").split("-", 1)[0].lower()
    in_rate, out_rate = _USD_PER_MILLION.get(prefix, (0.0, 0.0))
    # Optional global multiplier supports local price table adjustment.
    multiplier = float(os.environ.get("LLM_COST_MULTIPLIER", "1"))
    return round(multiplier * (max(0, prompt_tokens) * in_rate +
                               max(0, completion_tokens) * out_rate) / 1_000_000, 8)
