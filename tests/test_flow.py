import pytest
from conftest import pin

from cbc.flow import flow


def rows(record):
    return {row["n"]: row for row in flow(record)["speeches"]}


def test_the_sheet_counts_what_another_speaker_read_back(fixed_record):
    # Counted from the pins written in the fixture, not by the code under test.
    # Speech 1 (five sentences): Cicero read back sentence 1 in speech 2, and Omnibus read
    # back sentence 5 in speech 3 (the relocated pin). Cicero's pin over the whole speech
    # marks nothing.
    assert rows(fixed_record)[1] == {
        "n": 1,
        "seat": "Broad",
        "round": "opening",
        "state": "delivered",
        "sentences": 5,
        "read_back": [0, 4],
        "by_both": [],
        "by": {"Cicero": 1, "Omnibus": 1},
        "left_standing": [1, 2, 3],
    }
    # Speech 2 (four sentences): Omnibus read back sentences 3 and 4. Cicero's pin on
    # sentence 3 is on his own speech, so it does not count.
    second = rows(fixed_record)[2]
    assert (second["read_back"], second["by"]) == ([2, 3], {"Omnibus": 2})
    assert second["left_standing"] == [0, 1]


def test_an_unresolved_pin_reads_nothing_back(fixed_record):
    # The only pin on speech 3 is Cicero's unresolved one.
    third = rows(fixed_record)[3]
    assert (third["read_back"], third["by"]) == ([], {})
    assert third["left_standing"] == [0, 1, 2]


def test_the_totals_of_the_fixed_record(fixed_record):
    sheet = flow(fixed_record)
    assert sheet["checks"] == {"exact": 5, "relocated": 1, "unresolved": 2}
    assert sheet["whole_speech_pins"] == 1
    # Speeches 2 and 3 read back another speaker. Speech 1 pinned only the motion, and
    # speech 4 only a whole speech, its own speech and two pins that did not resolve.
    assert sheet["speeches_reading_back"] == 2
    assert sheet["delivered"] == 4


def test_the_cost_counts_the_speeches_that_can_be_priced(fixed_record):
    # Three speeches on Haiku 5.5, each 1,000 tokens in at $0.10 and 200 out at $0.50 a
    # million: 3 x (100 + 100) / 1,000,000. The fourth names a model with no listed price.
    sheet = flow(fixed_record)
    assert sheet["cost"] == pytest.approx(0.0006)
    assert sheet["unpriced"] == 1


def test_a_pin_on_the_motion_never_counts_as_reading_back_another_speaker(fixed_record):
    del fixed_record["speeches"][1:]
    sheet = flow(fixed_record)
    assert sheet["checks"]["exact"] == 1
    assert sheet["speeches_reading_back"] == 0


def test_a_pin_over_a_whole_long_speech_marks_no_sentence(fixed_record):
    # Take away every pin on speech 1 but the one that covers all five of its sentences.
    fixed_record["speeches"][1]["segments"][0]["pins"] = []
    fixed_record["speeches"][2]["segments"][1]["pins"] = []
    first = rows(fixed_record)[1]
    assert first["read_back"] == []
    assert first["left_standing"] == [0, 1, 2, 3, 4]
    assert flow(fixed_record)["whole_speech_pins"] == 1


def test_a_pin_over_a_whole_short_speech_reads_back_each_sentence(fixed_record):
    # Speech 3 has three sentences, fewer than the four that make a whole-speech pin.
    whole = "".join(fixed_record["speeches"][2]["sentences"])
    fixed_record["speeches"][3]["segments"][2]["pins"] = [pin(3, 0, 3, whole)]
    third = rows(fixed_record)[3]
    assert (third["read_back"], third["by"]) == ([0, 1, 2], {"Cicero": 3})
    assert flow(fixed_record)["whole_speech_pins"] == 1  # still only the one on speech 1


def test_the_sentences_of_a_closing_are_not_listed_as_left_standing(fixed_record):
    fixed_record["speeches"][3]["round"] = "closing"
    assert rows(fixed_record)[4]["left_standing"] == []
    fixed_record["speeches"][3]["round"] = "rebuttal"
    assert rows(fixed_record)[4]["left_standing"] == [0, 1, 2, 3]


def test_a_declined_speech_has_a_row_and_nothing_to_read_back(fixed_record):
    fixed_record["speeches"][3] |= {"state": "declined", "segments": [], "sentences": []}
    fourth = rows(fixed_record)[4]
    assert (fourth["state"], fourth["sentences"], fourth["left_standing"]) == ("declined", 0, [])
    assert flow(fixed_record)["delivered"] == 3


def test_a_record_with_no_speeches_has_an_empty_sheet(fixed_record):
    fixed_record["speeches"] = []
    assert flow(fixed_record) == {
        "speeches": [],
        "checks": {"exact": 0, "relocated": 0, "unresolved": 0},
        "whole_speech_pins": 0,
        "speeches_reading_back": 0,
        "delivered": 0,
        "cost": 0,
        "unpriced": 0,
    }
