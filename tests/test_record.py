import copy
import json

import pytest
from conftest import MOTION, STARTED, blank_record

from cbc.record import (
    FORMAT,
    count_checks,
    load,
    make_pin,
    new_record,
    save,
    unplaced_pin,
    verify,
)

PAPER = ["One fine day.", "Two came along.", "Three is a crowd.", "Four."]


def test_a_new_record_says_what_the_sitting_is_held_with(personas):
    record = blank_record(personas)
    assert record["format"] == "cbc-record/1"
    assert record["producer"] == {"name": "cbc", "version": "0.1.0", "runner": "local"}
    assert record["provenance"] == "stand-in"
    assert record["started"] == STARTED
    assert record["motion"] == MOTION
    assert record["motion_sentences"] == [MOTION]
    assert record["settings"] == {
        "model": "claude-fable-5-2",
        "effort": "medium",
        "max_tokens": 8_000,
        "chair": "system",
        "fallbacks": True,
        "words": {"opening": 220, "rebuttal": 180, "closing": 120},
    }
    assert [seat["name"] for seat in record["seats"]] == ["Broad", "Cicero", "Omnibus"]
    assert [seat["school"] for seat in record["seats"]] == [
        "the questioner",
        "the advocate",
        "the storyteller",
    ]
    assert record["speeches"] == []
    assert verify(record) == []


def test_each_seat_carries_the_sha256_of_its_character_file(personas):
    # sha256 of "You are Broad. (A stand-in for the character file.)\n", worked out with
    # the sha256sum command, not with the code under test.
    record = blank_record(personas)
    assert record["seats"][0]["persona_sha256"] == (
        "01377156acf2cf2dbc3f82ecb5d2df3fa32be2ca931a47342c9c5988b7cd0d88"
    )


def test_the_same_inputs_give_the_same_record(personas):
    assert blank_record(personas) == blank_record(personas)


def test_provenance_has_no_default_and_only_two_values(personas):
    settings = {
        "started": STARTED,
        "model": "claude-fable-5-2",
        "effort": "medium",
        "max_tokens": 8_000,
        "chair": "system",
        "fallbacks": True,
    }
    with pytest.raises(TypeError, match="provenance"):
        new_record(MOTION, personas, **settings)
    with pytest.raises(ValueError, match="provenance must be one of live, stand-in"):
        new_record(MOTION, personas, provenance="rehearsal", **settings)


def test_an_empty_motion_is_refused(personas):
    with pytest.raises(ValueError, match="the motion is empty"):
        blank_record(personas, motion="  \n ")


def test_a_record_survives_saving_and_loading(tmp_path, fixed_record):
    path = tmp_path / "sittings" / "a sitting.json"
    save(fixed_record, path)
    assert load(path) == fixed_record
    assert verify(load(path)) == []


def test_the_file_is_plain_indented_json_that_keeps_its_letters(tmp_path, personas):
    record = blank_record(personas, motion="Is “truth” a café word?")
    path = tmp_path / "record.json"
    save(record, path)
    written = path.read_bytes()
    assert written.startswith(b'{\n  "format": "cbc-record/1",\n')
    assert written.endswith(b"}\n")
    assert b"\r" not in written
    assert "Is “truth” a café word?" in written.decode("utf-8")
    assert json.loads(written) == record


def test_saving_again_replaces_the_file_and_leaves_no_draft_behind(tmp_path, personas):
    path = tmp_path / "record.json"
    save(blank_record(personas), path)
    save(blank_record(personas, motion="A second motion."), path)
    assert load(path)["motion"] == "A second motion."
    assert [file.name for file in tmp_path.iterdir()] == ["record.json"]


def test_a_failed_save_leaves_the_last_good_record_in_place(tmp_path, personas):
    path = tmp_path / "record.json"
    save(blank_record(personas), path)
    broken = blank_record(personas) | {"speeches": [object()]}  # not something JSON can hold
    with pytest.raises(TypeError):
        save(broken, path)
    assert load(path) == blank_record(personas)


def test_a_pin_is_exact_when_the_sentences_joined_are_the_words():
    assert make_pin(PAPER, 2, 1, 3, "Two came along.Three is a crowd.") == {
        "paper": 2,
        "first": 1,
        "last": 3,
        "words": "Two came along.Three is a crowd.",
        "check": "exact",
    }


def test_a_pin_at_the_wrong_place_is_relocated_and_keeps_the_stated_numbers():
    assert make_pin(PAPER, 2, 0, 1, "Three is a crowd.") == {
        "paper": 2,
        "first": 2,
        "last": 3,
        "words": "Three is a crowd.",
        "check": "relocated",
        "stated_first": 0,
        "stated_last": 1,
    }


def test_words_joined_differently_are_relocated_not_exact():
    # If an API ever joined cited sentences with a space, the pin would still be found,
    # and it would be counted apart from the exact ones.
    pin = make_pin(PAPER, 2, 1, 3, "Two came along. Three is a crowd.")
    assert (pin["check"], pin["first"], pin["last"]) == ("relocated", 1, 3)
    assert (pin["stated_first"], pin["stated_last"]) == (1, 3)


@pytest.mark.parametrize(
    "first, last, words",
    [
        (1, 2, "Two never came along."),  # words the paper does not say
        (1, 2, "came along."),  # part of a sentence is not a run of sentences
        (0, 1, ""),  # no words at all
        (7, 9, "Five."),  # a place past the end, and words not there either
        (-1, 1, "Six."),  # a place before the start
    ],
)
def test_a_pin_whose_words_are_not_in_the_paper_is_unresolved(first, last, words):
    assert make_pin(PAPER, 2, first, last, words) == {
        "paper": 2,
        "first": first,
        "last": last,
        "words": words,
        "check": "unresolved",
    }


def test_a_place_past_the_end_is_relocated_when_the_words_are_in_the_paper():
    pin = make_pin(PAPER, 2, 7, 8, "Four.")
    assert (pin["check"], pin["first"], pin["last"]) == ("relocated", 3, 4)


def test_a_pin_that_names_no_paper_is_unresolved():
    assert unplaced_pin("Some words.") == {
        "paper": None,
        "first": None,
        "last": None,
        "words": "Some words.",
        "check": "unresolved",
    }


def test_the_fixed_record_holds_and_its_pins_are_counted_by_check(fixed_record):
    assert verify(fixed_record) == []
    # By hand: speeches 1 to 4 hold 1, 1, 1 and 2 exact pins; speech 3 holds the relocated
    # one; speech 4 holds both unresolved ones.
    assert count_checks(fixed_record) == {"exact": 5, "relocated": 1, "unresolved": 2}


def tampered(record, change):
    """The faults verify finds after one change to a copy of the record."""
    forged = copy.deepcopy(record)
    change(forged)
    return verify(forged)


def test_a_changed_sentence_is_caught(fixed_record):
    def change(record):
        record["speeches"][0]["sentences"][0] = "What is homework really for?"

    faults = tampered(fixed_record, change)
    assert "speech 1 (Broad, opening): its sentences are not its text, cut into sentences" in faults


def test_a_speech_rewritten_with_care_is_caught_by_the_pins_on_it(fixed_record):
    # The text and the sentences are changed together, so the speech agrees with itself.
    # The pins other speakers put on the old words no longer hold.
    def change(record):
        first = record["speeches"][0]
        first["sentences"][0] = "What is homework really for?"
        first["segments"][0]["text"] = first["segments"][0]["text"].replace(
            "What is homework for?", "What is homework really for?"
        )

    assert tampered(fixed_record, change) == [
        "speech 2 (Cicero, opening), pin 1: it is stored as exact, "
        "but against the record it is unresolved",
        "speech 4 (Cicero, rebuttal), pin 1: it is stored as exact, "
        "but against the record it is unresolved",
    ]


def test_changed_pin_words_are_caught(fixed_record):
    def change(record):
        record["speeches"][1]["segments"][0]["pins"][0]["words"] = "What is school for?"

    assert tampered(fixed_record, change) == [
        "speech 2 (Cicero, opening), pin 1: it is stored as exact, "
        "but against the record it is unresolved"
    ]


def test_a_pin_to_a_later_speech_is_caught(fixed_record):
    def change(record):
        record["speeches"][1]["segments"][0]["pins"][0]["paper"] = 3

    assert tampered(fixed_record, change) == [
        "speech 2 (Cicero, opening), pin 1: it points at paper 3, which is not an earlier one"
    ]


def test_a_pin_to_its_own_speech_is_caught(fixed_record):
    def change(record):
        record["speeches"][1]["segments"][0]["pins"][0]["paper"] = 2

    assert tampered(fixed_record, change) == [
        "speech 2 (Cicero, opening), pin 1: it points at paper 2, which is not an earlier one"
    ]


def test_a_pin_to_a_declined_speech_is_caught(fixed_record):
    def change(record):
        record["speeches"][1] |= {"state": "declined", "segments": [], "sentences": []}

    faults = tampered(fixed_record, change)
    assert "speech 3 (Omnibus, opening), pin 1: it points at speech 2, which is declined" in faults


def test_a_declined_speech_that_holds_text_is_caught(fixed_record):
    def change(record):
        record["speeches"][3]["state"] = "declined"

    assert tampered(fixed_record, change) == [
        "speech 4 (Cicero, rebuttal): it is declined, yet it holds text"
    ]


@pytest.mark.parametrize(
    "speech, segment, stored, now",
    [
        (1, 0, "unresolved", "exact"),  # an exact pin marked down
        (1, 0, "relocated", "exact"),
        (2, 1, "exact", "relocated"),  # a relocated pin passed off as exact
        (3, 2, "exact", "unresolved"),  # an unresolved pin passed off as checked
    ],
)
def test_a_wrong_stored_check_is_caught(fixed_record, speech, segment, stored, now):
    def change(record):
        record["speeches"][speech]["segments"][segment]["pins"][0]["check"] = stored

    (fault,) = tampered(fixed_record, change)
    assert fault.endswith(f"it is stored as {stored}, but against the record it is {now}")


def test_a_pin_that_names_no_paper_cannot_be_stored_as_checked(fixed_record):
    def change(record):
        record["speeches"][3]["segments"][3]["pins"][0]["check"] = "exact"

    assert tampered(fixed_record, change) == [
        "speech 4 (Cicero, rebuttal), pin 4: it names no paper, yet it is stored as exact"
    ]


def test_a_shifted_place_is_caught(fixed_record):
    def change(record):
        pin = record["speeches"][2]["segments"][1]["pins"][0]
        pin["first"], pin["last"] = 3, 4

    assert tampered(fixed_record, change) == [
        "speech 3 (Omnibus, opening), pin 2: "
        "the place it stores is not the place its words are found"
    ]


def test_a_bad_format_is_caught(fixed_record):
    def change(record):
        record["format"] = "cbc-record/2"

    assert tampered(fixed_record, change) == ["the format is 'cbc-record/2', not 'cbc-record/1'"]


def test_a_gap_in_the_numbering_is_caught(fixed_record):
    def change(record):
        record["speeches"][2]["n"] = 5

    assert tampered(fixed_record, change) == ["the speeches are numbered [1, 2, 5, 4], not 1 to 4"]


def test_a_removed_speech_is_caught(fixed_record):
    def change(record):
        del record["speeches"][1]

    assert tampered(fixed_record, change) == ["the speeches are numbered [1, 3, 4], not 1 to 3"]


def test_a_changed_motion_is_caught(fixed_record):
    def change(record):
        record["motion"] = "This house would double homework."

    faults = tampered(fixed_record, change)
    assert "the motion's sentences are not the motion, cut into sentences" in faults


def test_changed_motion_sentences_are_caught_by_the_pin_on_them(fixed_record):
    def change(record):
        record["motion"] = "This house would double homework."
        record["motion_sentences"] = ["This house would double homework."]

    assert tampered(fixed_record, change) == [
        "speech 1 (Broad, opening), pin 1: it is stored as exact, "
        "but against the record it is unresolved"
    ]


def test_an_unknown_state_or_provenance_is_caught(fixed_record):
    def change(record):
        record["provenance"] = "rehearsal"
        record["speeches"][3]["state"] = "withdrawn"

    assert tampered(fixed_record, change) == [
        "the provenance is 'rehearsal'",
        "speech 4 (Cicero, rebuttal): its state is 'withdrawn'",
    ]


def test_a_delivered_speech_with_no_text_is_caught(fixed_record):
    def change(record):
        record["speeches"][3] |= {"segments": [], "sentences": []}

    assert tampered(fixed_record, change) == [
        "speech 4 (Cicero, rebuttal): it is delivered, yet it has no text"
    ]


@pytest.mark.parametrize(
    "not_a_record", [[], {"format": FORMAT}, {"format": FORMAT, "speeches": 3}]
)
def test_a_file_that_is_not_a_record_gets_a_plain_verdict(not_a_record):
    (fault,) = verify(not_a_record)
    assert fault.startswith("this is not shaped like a cbc-record/1 record")
