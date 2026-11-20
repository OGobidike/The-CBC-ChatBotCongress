import pytest

from cbc.chair import ROUNDS, WORDS, call, check_placement, order
from cbc.seats import SEATS

USER = {"role": "user", "content": "the papers"}
SYSTEM = {"role": "system", "content": "the Chair's call"}
ASSISTANT = {"role": "assistant", "content": "a speech"}


def test_a_sitting_is_nine_speeches_in_three_rounds():
    assert order() == [
        ("Broad", "opening"),
        ("Cicero", "opening"),
        ("Omnibus", "opening"),
        ("Cicero", "rebuttal"),
        ("Omnibus", "rebuttal"),
        ("Broad", "rebuttal"),
        ("Omnibus", "closing"),
        ("Broad", "closing"),
        ("Cicero", "closing"),
    ]


def test_nobody_always_speaks_last():
    last_of_each_round = [order()[index][0] for index in (2, 5, 8)]
    assert sorted(last_of_each_round) == sorted(SEATS)


def test_the_call_names_the_seat_the_round_and_the_word_limit():
    words = call("Cicero", "rebuttal", 180)
    assert words.startswith("The Chair calls Cicero for the rebuttal.")
    assert "Speak as Cicero, in 180 words at most, in plain text." in words


def test_an_opening_asks_for_a_position_and_for_no_citing():
    words = call("Broad", "opening", 220)
    assert "State your position on the motion." in words
    assert "cite" not in words and "citing" not in words


def test_a_rebuttal_asks_for_the_sentences_meant():
    words = call("Omnibus", "rebuttal", 180)
    assert "Answer what was actually said." in words
    assert "cite the sentences of their speech that you mean" in words


def test_a_closing_asks_what_is_granted_and_what_still_stands():
    words = call("Broad", "closing", 120)
    assert "name any point you grant" in words
    assert "the strongest point still standing against you, citing" in words


@pytest.mark.parametrize("round_name", ROUNDS)
def test_no_call_asks_for_private_notes_or_reasoning(round_name):
    # Asking a speaker to show its reasoning invites a refusal, which is billed.
    words = call("Cicero", round_name, WORDS[round_name]).lower()
    for asked in ("reasoning", "notes", "scratchpad", "step by step", "think"):
        assert asked not in words


def test_the_calls_the_chamber_sends_are_well_placed():
    check_placement([USER, SYSTEM])
    check_placement([USER])


def test_a_system_message_cannot_come_first():
    with pytest.raises(ValueError, match="cannot come first"):
        check_placement([SYSTEM, USER])


def test_a_system_message_must_come_directly_after_a_user_message():
    with pytest.raises(ValueError, match="directly after a user message"):
        check_placement([USER, ASSISTANT, SYSTEM])


def test_a_system_message_cannot_be_followed_by_a_user_turn():
    with pytest.raises(ValueError, match="followed by a user turn"):
        check_placement([USER, SYSTEM, USER])


def test_a_request_cannot_end_on_an_assistant_turn():
    with pytest.raises(ValueError, match="end on an assistant turn"):
        check_placement([USER, SYSTEM, ASSISTANT])


def test_an_earlier_exchange_with_the_chair_is_still_well_placed():
    check_placement([USER, SYSTEM, ASSISTANT, USER, SYSTEM])


def test_two_system_messages_in_a_row_are_refused_though_the_api_takes_them():
    with pytest.raises(ValueError, match="directly after a user message"):
        check_placement([USER, SYSTEM, SYSTEM])


def test_a_request_needs_a_message():
    with pytest.raises(ValueError, match="at least one message"):
        check_placement([])
