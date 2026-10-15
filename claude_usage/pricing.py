"""Pure-function module for Claude API cost estimation.

Prices are expressed as USD per million tokens. Values reflect public
Anthropic pricing as of July 2026 (verify at https://www.anthropic.com/pricing).
The module has no side effects aside from emitting a ``warnings.warn`` when
callers request an unknown model (in which case we silently fall back to
Sonnet pricing so billing never crashes a running collector).

Cache rates follow the standard Anthropic formula:
    cache_read        = input_rate × 0.1   (0.025 on Fable 5.1, 0.05 on Opus 5.5
                                            and Sonnet 5.5; tabled per model)
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
    # Opus 5.5 (Sep 2026): successor to Opus 5 at a LOWER $4/$20 tier, with
    # cache reads at $0.20 (0.05x input, not the usual 0.1x). Must be tabled:
    # the "opus" family fallback resolves to Opus 5, which over-reported it
    # 25% on input/output but 2.5x on cache reads ($0.50 vs $0.20) — ~2x
    # overall on cache-read-heavy Claude Code traffic.
    # (Fast mode bills $8/$40 but shares the model id; we price standard.)
    "claude-opus-5-5": {
        "input": 4.0,
        "output": 20.0,
        "cache_read": 0.20,
        "cache_creation": 5.00,
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
    # Sonnet 5.5: successor to Sonnet 5 at the same $2/$10 tier, but like
    # Opus 5.5 its cache hits bill at 0.05x input: $0.10, not Sonnet 5's
    # $0.20. Untabled, the "sonnet" family fallback doubled every cache read.
    "claude-sonnet-5-5": {
        "input": 2.0,
        "output": 10.0,
        "cache_read": 0.10,
        "cache_creation": 2.50,
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
    # Mythos 5.1 / Mythos 5 (Project Glasswing, limited availability) price
    # exactly like Fable 5.1 / Fable 5. "mythos" matched no family, so
    # before these rows they fell to the generic Sonnet fallback ($3/$15)
    # and were under-reported 3.3x.
    "claude-mythos-5-1": {
        "input": 10.0,
        "output": 50.0,
        "cache_read": 0.25,
        "cache_creation": 12.50,
    },
    "claude-mythos-5": {
        "input": 10.0,
        "output": 50.0,
        "cache_read": 1.00,
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
    # Anthropic's published alias for Opus 4 is "claude-opus-4-0"; the bare
    # form above only catches the dated id after the -YYYYMMDD strip.
    "claude-opus-4-0": {
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
    # Likewise "claude-sonnet-4-0" is the published alias for Sonnet 4.
    "claude-sonnet-4-0": {
        "input": 3.0,
        "output": 15.0,
        "cache_read": 0.30,
        "cache_creation": 3.75,
    },
    # Haiku 5.5 is priced by prompt length, per request: up to 100,000
    # prompt tokens (input + cache reads + cache writes) it is $0.10/$0.50,
    # over that the WHOLE request, output included, is $0.50/$2.50. The
    # second card lives under its own key; billing_model() picks it per
    # request before anything is aggregated (see _LONG_PROMPT_TIERS).
    "claude-haiku-5-5": {
        "input": 0.10,
        "output": 0.50,
        "cache_read": 0.01,
        "cache_creation": 0.125,
    },
    "claude-haiku-5-5[>100k]": {
        "input": 0.50,
        "output": 2.50,
        "cache_read": 0.05,
        "cache_creation": 0.625,
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
# name is recognisable from the id (e.g. a freshly released "claude-opus-6"
# before the table above is updated). Anthropic embeds the family in every
# model id, so matching on it keeps a new release billed at its own tier
# instead of being silently under-reported at Sonnet rates.
#
# Every current id is tabled, and dated ids are stripped to their alias
# first, so in practice this only ever prices a release we have not seen
# yet. For those, each value points at the MOST EXPENSIVE current member of
# the family rather than the newest: in a spend tool an over-count is the
# safer mistake, and the unknown-model warning fires either way, which is
# the signal to table it. Hence Opus 5 ($5/$25, $0.50 reads) over the
# cheaper Opus 5.5, Fable 5 / Mythos 5 ($1.00 reads) over their 5.1
# ($0.25), and Haiku 4.5 ($1/$5) over Haiku 5.5.
_FAMILY_FALLBACK: Dict[str, str] = {
    "opus": "claude-opus-5",
    "fable": "claude-fable-5",
    "mythos": "claude-mythos-5",
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


# Models whose price depends on the length of each request's prompt:
# model id -> (threshold, key of the rate card used above the threshold).
# Anthropic counts every input token toward the threshold, cache reads and
# cache writes included, and prices each request on its own.
_LONG_PROMPT_TIERS: Dict[str, tuple[int, str]] = {
    "claude-haiku-5-5": (100_000, "claude-haiku-5-5[>100k]"),
}


def billing_model(model: str, prompt_tokens: int) -> str:
    """Return the pricing key for ONE request of *model*.

    For most models that is just *model*. For a prompt-length-tiered model
    (Haiku 5.5) a request whose prompt is over the threshold is billed
    entirely at a second rate card, so its tokens have to be kept apart from
    the short requests: pricing a summed bucket would decide the tier on the
    total, not per request. Callers pass ``input + cache_read +
    cache_creation`` for that single request, before aggregating.
    """
    tier = _LONG_PROMPT_TIERS.get(_DATE_SUFFIX.sub("", model))
    if tier is not None and prompt_tokens > tier[0]:
        return tier[1]
    return model


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
