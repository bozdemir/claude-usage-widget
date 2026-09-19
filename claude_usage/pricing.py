"""Pure-function module for Claude API cost estimation.

Prices are expressed as USD per million tokens. Values reflect public
Anthropic pricing as of July 2026 (verify at https://www.anthropic.com/pricing).
The module has no side effects aside from emitting a ``warnings.warn`` when
callers request an unknown model (in which case we silently fall back to
Sonnet pricing so billing never crashes a running collector).

Cache rates follow the standard Anthropic formula:
    cache_read        = input_rate × 0.1   (0.025 on Fable 5.1; tabled per model)
    cache_creation    = input_rate × 1.25  (5-minute TTL writes)
    cache_creation_1h = input_rate × 2     (1-hour TTL writes)
"""

from __future__ import annotations

import re
import warnings
from typing import Dict, Mapping

# Prices are USD per 1,000,000 tokens.
# Source: https://www.anthropic.com/pricing (July 2026)
MODEL_PRICING: Dict[str, Dict[str, float]] = {
    # Opus 4.8: $5 input, $25 output (same standard tier as 4.7). Note: Opus
    # "fast mode" bills at $10/$50, but Claude Code writes the same model id
    # for both, so we price the standard rate (fast mode isn't distinguishable
    # from the usage record alone).
    "claude-opus-4-8": {
        "input": 5.0,
        "output": 25.0,
        "cache_read": 0.50,
        "cache_creation": 6.25,
    },
    # Opus 5 (launched Aug 2026): a drop-in successor to Opus 4.8 at the SAME
    # $5/$25 tier — the one recent flagship whose fallback pricing happened to
    # be right. Tabled explicitly anyway: exact entries silence the unknown-
    # model warning and don't break if the family fallback target ever moves.
    # (Fast mode bills $10/$50 but shares the model id; we price standard.)
    "claude-opus-5": {
        "input": 5.0,
        "output": 25.0,
        "cache_read": 0.50,
        "cache_creation": 6.25,
    },
    # Opus 4.7 (July 2026): $5 input, $25 output — consistent across
    # Anthropic API, Bedrock, Vertex AI, and Foundry.
    "claude-opus-4-7": {
        "input": 5.0,
        "output": 25.0,
        "cache_read": 0.50,
        "cache_creation": 6.25,
    },
    # Opus 4.6 uses the same pricing tier as 4.7.
    "claude-opus-4-6": {
        "input": 5.0,
        "output": 25.0,
        "cache_read": 0.50,
        "cache_creation": 6.25,
    },
    # Sonnet 5 (launched 2026-06-30): $2 input / $10 output. Announced as
    # introductory pricing through 2026-08-31, but Anthropic has since made
    # $2/$10 the standard price — the scheduled rise to $3/$15 did not happen.
    "claude-sonnet-5": {
        "input": 2.0,
        "output": 10.0,
        "cache_read": 0.20,
        "cache_creation": 2.50,
    },
    # Sonnet 4.6: $3 input, $15 output (standard mid-tier pricing).
    "claude-sonnet-4-6": {
        "input": 3.0,
        "output": 15.0,
        "cache_read": 0.30,
        "cache_creation": 3.75,
    },
    # Fable 5: $10 input / $50 output. A distinct premium tier — pricier than
    # Sonnet, so it MUST be tabled explicitly; without this it fell through the
    # family fallback to Sonnet ($3/$15) and under-reported Fable cost ~3.3x.
    "claude-fable-5": {
        "input": 10.0,
        "output": 50.0,
        "cache_read": 1.00,
        "cache_creation": 12.50,
    },
    # Fable 5.1: same $10/$50 tier as Fable 5, but cache reads bill at 0.025x
    # input ($0.25) instead of the usual 0.1x.
    "claude-fable-5-1": {
        "input": 10.0,
        "output": 50.0,
        "cache_read": 0.25,
        "cache_creation": 12.50,
    },
    # Older models still seen in Claude Code logs (Task subagents often pin
    # them). Tabled explicitly because the family fallback maps them to the
    # newest family member, which is priced differently: Sonnet 4.x is $3/$15
    # (not Sonnet 5's $2/$10) and Opus 4.0/4.1 is $15/$75 (not $5/$25).
    "claude-opus-4-5": {
        "input": 5.0,
        "output": 25.0,
        "cache_read": 0.50,
        "cache_creation": 6.25,
    },
    "claude-opus-4-1": {
        "input": 15.0,
        "output": 75.0,
        "cache_read": 1.50,
        "cache_creation": 18.75,
    },
    "claude-opus-4": {
        "input": 15.0,
        "output": 75.0,
        "cache_read": 1.50,
        "cache_creation": 18.75,
    },
    "claude-sonnet-4-5": {
        "input": 3.0,
        "output": 15.0,
        "cache_read": 0.30,
        "cache_creation": 3.75,
    },
    "claude-sonnet-4": {
        "input": 3.0,
        "output": 15.0,
        "cache_read": 0.30,
        "cache_creation": 3.75,
    },
    # Haiku 4.5: $1 input, $5 output (entry-tier pricing).
    "claude-haiku-4-5": {
        "input": 1.0,
        "output": 5.0,
        "cache_read": 0.10,
        "cache_creation": 1.25,
    },
    "claude-haiku-4-5-20251001": {
        "input": 1.0,
        "output": 5.0,
        "cache_read": 0.10,
        "cache_creation": 1.25,
    },
    # Claude Code internal bookkeeping entries (compact summaries, sidechain
    # context, auto-generated placeholders) — not billed to the user, so we
    # map them to zero rates rather than emitting an "unknown model" warning
    # on every refresh.
    "<synthetic>": {
        "input": 0.0,
        "output": 0.0,
        "cache_read": 0.0,
        "cache_creation": 0.0,
    },
    "unknown": {
        "input": 0.0,
        "output": 0.0,
        "cache_read": 0.0,
        "cache_creation": 0.0,
    },
}

# Fallback model used whenever a caller passes an unknown model identifier
# that we can't even resolve to a family (see _family_fallback_model).
_FALLBACK_MODEL = "claude-sonnet-4-6"

# Per-family fallback used when an exact model id is unknown but its family
# name is recognisable from the id (e.g. a freshly released "claude-opus-4-8"
# before the table above is updated). Anthropic embeds the family in every
# model id, so matching on it keeps a new point release billed at its real
# tier instead of being silently under-reported at Sonnet rates. Each value
# points at the most recent known member of that family.
_FAMILY_FALLBACK: Dict[str, str] = {
    "opus": "claude-opus-5",
    "fable": "claude-fable-5",
    "sonnet": "claude-sonnet-5",
    "haiku": "claude-haiku-4-5-20251001",
}

# Conversion factor: prices are per one million tokens.
_PER_MILLION = 1_000_000.0

# Trailing snapshot date on a model id, e.g. the "-20250929" in
# "claude-sonnet-4-5-20250929".
_DATE_SUFFIX = re.compile(r"-\d{8}$")

# 1-hour TTL cache writes bill at 2x the base input rate on every model.
_CACHE_WRITE_1H_MULTIPLIER = 2.0

# Cache of models already warned about, so repeated refreshes don't spam stderr.
_WARNED_MODELS: set[str] = set()


def _family_fallback_model(model: str) -> str | None:
    """Best-effort map an unknown model id to a known same-family model.

    Anthropic model ids embed the family name (``claude-opus-4-8``,
    ``claude-sonnet-4-6``), so a substring match lets a newly released point
    version inherit the correct pricing tier until ``MODEL_PRICING`` is
    updated. Returns ``None`` when no family token is recognised.
    """
    lowered = model.lower()
    for family, representative in _FAMILY_FALLBACK.items():
        if family in lowered:
            return representative
    return None


def _resolve_pricing(model: str) -> Dict[str, float]:
    """Return the pricing table for ``model``, warning once per unknown model.

    Unknown exact ids are first resolved by *family* (so a new Opus release is
    billed at the Opus tier, not Sonnet's), and only fall back to the generic
    :data:`_FALLBACK_MODEL` when even the family is unrecognisable.
    """
    pricing = MODEL_PRICING.get(model)
    if pricing is not None:
        return pricing
    # Dated snapshot ids ("claude-sonnet-4-5-20250929") price like their alias.
    pricing = MODEL_PRICING.get(_DATE_SUFFIX.sub("", model))
    if pricing is not None:
        return pricing
    fallback = _family_fallback_model(model) or _FALLBACK_MODEL
    if model not in _WARNED_MODELS:
        _WARNED_MODELS.add(model)
        warnings.warn(
            f"Unknown model {model!r}; falling back to {fallback} pricing.",
            stacklevel=3,
        )
    return MODEL_PRICING[fallback]


def get_pricing(model: str) -> Dict[str, float]:
    """Public rate lookup with the SAME fallback chain as calculate_cost.

    Display code must use this instead of ``MODEL_PRICING.get(model,
    <sonnet>)`` — otherwise an unknown model's shown per-token rate (Sonnet)
    contradicts its computed dollar amounts (family tier), and the popup's
    "tokens × rate = $" arithmetic visibly doesn't add up."""
    return _resolve_pricing(model)


def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read: int = 0,
    cache_creation: int = 0,
    cache_creation_1h: int = 0,
) -> Dict[str, float]:
    """Compute the USD cost for a single request-shaped token bundle.

    Args:
        model: Canonical model identifier (see ``MODEL_PRICING``).
        input_tokens: Non-cached input tokens billed at the full input rate.
        output_tokens: Output/generation tokens.
        cache_read: Tokens served from the prompt cache (cheap read).
        cache_creation: ALL tokens written into the prompt cache — this is
            ``usage.cache_creation_input_tokens``, which includes 1h writes.
        cache_creation_1h: The subset of ``cache_creation`` written with the
            1-hour TTL (``usage.cache_creation.ephemeral_1h_input_tokens``),
            billed at 2x input instead of the 5-minute 1.25x rate.

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
    cache_creation_1h = min(max(int(cache_creation_1h), 0), cache_creation)

    input_cost = input_tokens * pricing["input"] / _PER_MILLION
    output_cost = output_tokens * pricing["output"] / _PER_MILLION
    cache_read_cost = cache_read * pricing["cache_read"] / _PER_MILLION
    cache_creation_cost = (
        (cache_creation - cache_creation_1h) * pricing["cache_creation"]
        + cache_creation_1h * pricing["input"] * _CACHE_WRITE_1H_MULTIPLIER
    ) / _PER_MILLION

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
            "cache_read": N, "cache_creation": N, "cache_creation_1h": N}}``.
            Missing keys default to zero so callers can pass sparse dicts.

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
            cache_creation_1h=int(counts.get("cache_creation_1h", 0) or 0),
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
    "get_pricing",
]
