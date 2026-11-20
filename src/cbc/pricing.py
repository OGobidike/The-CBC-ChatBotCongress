"""A rough cost for each speech, from Anthropic's list prices.

The token counts come from the API and are exact. The dollar figure is an estimate: prices
change, and a discount is not modelled. A speech that fell back to a model with no price
listed here gets no dollar figure. Only the top-level counts of a reply are read: when a
request falls back, the API also lists each attempt apart, and that list is not read.
Claude Haiku 5.5 costs more for prompts over 100,000 tokens, which is not modelled either.
"""

from dataclasses import dataclass
from typing import Any

# Read from https://platform.claude.com/docs/en/about-claude/pricing on this date.
PRICES_AS_OF = "2026-11-16"


@dataclass(frozen=True)
class Price:
    """US dollars per million tokens."""

    input: float
    output: float
    cache_write: float
    cache_read: float


PRICES = {
    "claude-fable-5-2": Price(input=8.00, output=40.00, cache_write=10.00, cache_read=0.20),
    "claude-opus-5-5": Price(input=4.00, output=20.00, cache_write=5.00, cache_read=0.20),
    "claude-sonnet-5-5": Price(input=2.00, output=10.00, cache_write=2.50, cache_read=0.10),
    "claude-haiku-5-5": Price(input=0.10, output=0.50, cache_write=0.125, cache_read=0.01),
}


def _count(usage: dict[str, int], name: str) -> int:
    return usage.get(name) or 0


def dollars(amount: float) -> str:
    """A sum of money for the terminal: in cents where that is exact, else to four places."""
    return f"${amount:.2f}" if round(amount, 2) == amount else f"${amount:.4f}"


def estimate_cost(model: str, usage: dict[str, int]) -> float | None:
    """Return the estimated cost of one speech in US dollars, or None for an unlisted model."""
    price = PRICES.get(model)
    if price is None:
        return None
    return (
        _count(usage, "input_tokens") * price.input
        + _count(usage, "output_tokens") * price.output
        + _count(usage, "cache_creation_input_tokens") * price.cache_write
        + _count(usage, "cache_read_input_tokens") * price.cache_read
    ) / 1_000_000


def sitting_cost(speeches: list[dict[str, Any]]) -> tuple[float, int]:
    """The estimated cost of the speeches so far, and how many of them could not be priced.

    Declined and empty speeches are counted too: their tokens were spent all the same.
    """
    costs = [estimate_cost(speech["model"], speech["usage"]) for speech in speeches]
    return sum(cost for cost in costs if cost is not None), costs.count(None)


def output_ceiling(model: str, max_tokens: int) -> float | None:
    """The most the output of one reply can cost in US dollars, or None for an unlisted model.

    Thinking is billed as output and counts toward max_tokens, so this covers it. What the
    model reads is extra and is not capped by max_tokens.
    """
    price = PRICES.get(model)
    return None if price is None else max_tokens * price.output / 1_000_000


def usage_line(model: str, usage: dict[str, int]) -> str:
    """One line for the terminal: the tokens of a speech and, where known, about what it cost."""
    # The API reports input in three parts. Together they are everything Claude read.
    fresh = _count(usage, "input_tokens")
    written = _count(usage, "cache_creation_input_tokens")
    read = _count(usage, "cache_read_input_tokens")
    cache_notes = []
    if read:
        cache_notes.append(f"{read:,} read from cache")
    if written:
        cache_notes.append(f"{written:,} written to cache")
    tokens_in = f"{fresh + written + read:,} tokens in"
    if cache_notes:
        tokens_in += f" ({', '.join(cache_notes)})"
    tokens_out = f"{_count(usage, 'output_tokens'):,} out"
    # Thinking is already inside the output count. Naming it explains a large one.
    thinking = _count(usage, "thinking_tokens")
    if thinking:
        tokens_out += f" ({thinking:,} of them thinking)"
    parts = [tokens_in, tokens_out]
    cost = estimate_cost(model, usage)
    if cost is not None:
        parts.append(f"about ${cost:.4f}")
    return f"[{model}: {', '.join(parts)}]"
