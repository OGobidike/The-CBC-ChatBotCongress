import pytest

from cbc.pricing import PRICES, estimate_cost, output_ceiling, sitting_cost, usage_line


def usage(input_tokens=120, output_tokens=40, cache_write=0, cache_read=0, thinking=0):
    """Token counts as a record keeps them."""
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "thinking_tokens": thinking,
        "cache_creation_input_tokens": cache_write,
        "cache_read_input_tokens": cache_read,
    }


def test_cost_adds_up_each_kind_of_token():
    # 1,000 in at $8, 500 out at $40, 2,000 written to cache at $10, 4,000 read at $0.20,
    # all per million tokens.
    spent = usage(input_tokens=1_000, output_tokens=500, cache_write=2_000, cache_read=4_000)
    expected = (1_000 * 8 + 500 * 40 + 2_000 * 10 + 4_000 * 0.20) / 1_000_000
    assert estimate_cost("claude-fable-5-2", spent) == pytest.approx(expected)


def test_thinking_tokens_are_not_charged_twice():
    # They are already inside the output count.
    plain = usage(output_tokens=500)
    with_thinking = usage(output_tokens=500, thinking=300)
    assert estimate_cost("claude-fable-5-2", with_thinking) == estimate_cost(
        "claude-fable-5-2", plain
    )


def test_an_unlisted_model_gets_no_dollar_figure():
    assert estimate_cost("some-future-model", usage()) is None
    assert "$" not in usage_line("some-future-model", usage())


def test_the_line_shows_tokens_and_an_estimate():
    line = usage_line("claude-haiku-5-5", usage(input_tokens=1_204, output_tokens=312))
    assert line == "[claude-haiku-5-5: 1,204 tokens in, 312 out, about $0.0003]"


def test_tokens_in_counts_everything_claude_read():
    # The API reports the cached part of the input separately from the fresh part.
    first = usage(input_tokens=4, output_tokens=127, cache_write=2_875)
    line = usage_line("claude-haiku-5-5", first)
    assert line.startswith("[claude-haiku-5-5: 2,879 tokens in (2,875 written to cache), 127 out")


def test_cache_reads_and_writes_are_both_shown():
    later = usage(input_tokens=4, output_tokens=594, cache_write=150, cache_read=2_882)
    line = usage_line("claude-fable-5-2", later)
    assert "3,036 tokens in (2,882 read from cache, 150 written to cache), 594 out" in line


def test_thinking_is_named_inside_the_output_count():
    line = usage_line("claude-fable-5-2", usage(output_tokens=2_000, thinking=1_590))
    assert "2,000 out (1,590 of them thinking)" in line


def test_a_missing_count_is_treated_as_zero():
    # A record written by another runner may leave a count out, or store it as null.
    assert estimate_cost("claude-opus-5-5", {"input_tokens": 10, "output_tokens": None}) == (
        pytest.approx(10 * 4 / 1_000_000)
    )


def test_cache_reads_cost_less_than_fresh_input():
    for price in PRICES.values():
        assert price.cache_read < price.input < price.output


def test_a_sitting_costs_the_sum_of_its_priced_speeches():
    speeches = [
        {"model": "claude-fable-5-2", "usage": usage(input_tokens=1_000, output_tokens=500)},
        {"model": "claude-haiku-5-5", "usage": usage(input_tokens=1_000, output_tokens=500)},
        {"model": "some-future-model", "usage": usage()},
    ]
    # Fable: (1,000 x 8 + 500 x 40) / 1,000,000. Haiku: (1,000 x 0.10 + 500 x 0.50) / 1,000,000.
    total, unpriced = sitting_cost(speeches)
    assert total == pytest.approx(0.028 + 0.00035)
    assert unpriced == 1


def test_no_speeches_cost_nothing():
    assert sitting_cost([]) == (0, 0)


def test_the_most_a_reply_can_write_at_the_token_limit():
    # 8,000 tokens at $40 a million on Fable 5.2, and at $0.50 a million on Haiku 5.5.
    assert output_ceiling("claude-fable-5-2", 8_000) == pytest.approx(0.32)
    assert output_ceiling("claude-haiku-5-5", 8_000) == pytest.approx(0.004)
    assert output_ceiling("some-future-model", 8_000) is None
