"""Pure-function module for Claude API cost estimation.

Prices are expressed as USD per million tokens. Values are approximate and
reflect public Anthropic pricing as of early 2026. The module has no side
effects aside from emitting a ``warnings.warn`` when callers request an unknown
model (in which case we silently fall back to Sonnet pricing so billing never
crashes a running collector).
"""

from __future__ import annotations

import warnings
from typing import Dict, Mapping

# Prices are USD per 1,000,000 tokens.
MODEL_PRICING: Dict[str, Dict[str, float]] = {
    "claude-opus-4-6": {
        "input": 15.0,
        "output": 75.0,
        "cache_read": 1.50,
        "cache_creation": 18.75,
    },
    "claude-opus-4-7": {
        "input": 15.0,
        "output": 75.0,
        "cache_read": 1.50,
        "cache_creation": 18.75,
    },
    "claude-sonnet-4-6": {
        "input": 3.0,
        "output": 15.0,
        "cache_read": 0.30,
        "cache_creation": 3.75,
    },
    "claude-haiku-4-5-20251001": {
        "input": 1.0,
        "output": 5.0,
        "cache_read": 0.10,
        "cache_creation": 1.25,
    },
}

# Fallback model used whenever a caller passes an unknown model identifier.
_FALLBACK_MODEL = "claude-sonnet-4-6"

# Conversion factor: prices are per one million tokens.
_PER_MILLION = 1_000_000.0

# Cache of models already warned about, so repeated refreshes don't spam stderr.
_WARNED_MODELS: set[str] = set()


def _resolve_pricing(model: str) -> Dict[str, float]:
    """Return the pricing table for ``model``, warning once per unknown model."""
    pricing = MODEL_PRICING.get(model)
    if pricing is not None:
        return pricing
    if model not in _WARNED_MODELS:
        _WARNED_MODELS.add(model)
        warnings.warn(
            f"Unknown model {model!r}; falling back to {_FALLBACK_MODEL} pricing.",
            stacklevel=3,
        )
    return MODEL_PRICING[_FALLBACK_MODEL]


def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read: int = 0,
    cache_creation: int = 0,
) -> Dict[str, float]:
    """Compute the USD cost for a single request-shaped token bundle.

    Args:
        model: Canonical model identifier (see ``MODEL_PRICING``).
        input_tokens: Non-cached input tokens billed at the full input rate.
        output_tokens: Output/generation tokens.
        cache_read: Tokens served from the prompt cache (cheap read).
        cache_creation: Tokens written into the prompt cache (creation rate).

    Returns:
        A dict with per-category dollar amounts plus ``total`` and
        ``cache_savings`` (the hypothetical cost the ``cache_read`` tokens
        would have incurred at the full input rate).
    """
    pricing = _resolve_pricing(model)

    # Clamp negatives to zero — malformed usage payloads should never produce
    # a negative bill.
    input_tokens = max(int(input_tokens), 0)
    output_tokens = max(int(output_tokens), 0)
    cache_read = max(int(cache_read), 0)
    cache_creation = max(int(cache_creation), 0)

    input_cost = input_tokens * pricing["input"] / _PER_MILLION
    output_cost = output_tokens * pricing["output"] / _PER_MILLION
    cache_read_cost = cache_read * pricing["cache_read"] / _PER_MILLION
    cache_creation_cost = cache_creation * pricing["cache_creation"] / _PER_MILLION

    # Savings: what the cached-read tokens would have cost at the full input
    # rate, minus what we actually paid for them.
    cache_read_full_cost = cache_read * pricing["input"] / _PER_MILLION
    cache_savings = cache_read_full_cost - cache_read_cost

    total = input_cost + output_cost + cache_read_cost + cache_creation_cost

    return {
        "total": total,
        "input": input_cost,
        "output": output_cost,
        "cache_read": cache_read_cost,
        "cache_creation": cache_creation_cost,
        "cache_savings": cache_savings,
    }


def calculate_stats_cost(
    by_model: Mapping[str, Mapping[str, int]],
) -> Dict[str, object]:
    """Aggregate cost across a per-model token breakdown.

    Args:
        by_model: Mapping of ``{model: {"input": N, "output": N,
            "cache_read": N, "cache_creation": N}}``. Missing keys default
            to zero so callers can pass sparse dicts.

    Returns:
        A dict with ``total``, summed per-category costs, ``cache_savings``
        across all models, and a ``by_model`` sub-dict holding the per-model
        breakdown produced by ``calculate_cost``.
    """
    totals = {
        "total": 0.0,
        "input": 0.0,
        "output": 0.0,
        "cache_read": 0.0,
        "cache_creation": 0.0,
        "cache_savings": 0.0,
    }
    per_model: Dict[str, Dict[str, float]] = {}

    for model, counts in by_model.items():
        breakdown = calculate_cost(
            model,
            input_tokens=int(counts.get("input", 0) or 0),
            output_tokens=int(counts.get("output", 0) or 0),
            cache_read=int(counts.get("cache_read", 0) or 0),
            cache_creation=int(counts.get("cache_creation", 0) or 0),
        )
        per_model[model] = breakdown
        for key in totals:
            totals[key] += breakdown[key]

    result: Dict[str, object] = dict(totals)
    result["by_model"] = per_model
    return result


__all__ = [
    "MODEL_PRICING",
    "calculate_cost",
    "calculate_stats_cost",
]
