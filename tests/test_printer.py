import copy
import io

import pytest
from conftest import (
    BROAD_OPENING,
    FakeClient,
    blank_record,
    cite,
    pin,
    plain_sitting,
    reply,
    said,
    spent,
)

from cbc import printer
from cbc.chamber import run_sitting
from cbc.printer import CUT_SHORT, DECLINED, STAND_IN_BANNER, WIDTH, Typist
from cbc.record import WHAT_A_PIN_PROVES, load

FIRST = "Broad speaks in the opening."
SECOND = "This is speech 1 of the sitting."

LONG = (
    "The first paragraph runs well past the width of the page, so that it has to be "
    "wrapped more than once before it ends, and it does end here.\n\n"
    "A second paragraph follows a blank line.\nAnd a line break is kept as a line break."
)


class Terminal(io.StringIO):
    """A stream that says it is a terminal, as a real screen does."""

    def isatty(self):
        return True


def typed(*pieces, markers=()):
    """What the typist prints for a speech handed over in these pieces."""
    out = io.StringIO()
    typist = Typist(out)
    for index, piece in enumerate(pieces):
        typist.words(piece)
        typist.markers(markers[index] if index < len(markers) else 0)
    typist.close()
    return out.getvalue()


def shown(record):
    out = io.StringIO()
    printer.replay(record, out)
    return out.getvalue()


def sit(script, record, path, personas, out=None, **settings):
    """Hold a sitting on the fake client. Returns the finished flag and what was printed."""
    out = io.StringIO() if out is None else out
    finished = run_sitting(
        FakeClient(*script), record, path, personas, out, provenance="stand-in", **settings
    )
    return finished, out.getvalue()


def an_eventful_sitting():
    """Nine replies with one of everything a speech can be."""
    script = plain_sitting()
    script[1] = reply(
        "Broad says he speaks.",
        said(" So he does.", cite(1, 0, 1, FIRST), cite(1, 1, 2, SECOND)),
        "\n\nA second paragraph. ",
        said("He counts.", cite(1, 0, 1, SECOND)),  # stated at the wrong place
        usage=spent(input_tokens=30, output_tokens=900, cache_read=2_400, thinking=640),
    )
    script[2] = reply(stop_reason="refusal")
    script[3] = reply(stop_reason="max_tokens")
    script[4] = reply(
        said(
            "The motion stands.",
            cite(0, 0, 1, "This house would rather be told a hard truth than a kind story."),
        ),
        said(" Broad never said this.", cite(1, 0, 1, "Broad never said this.")),
        said(" Nor this.", cite(9, 0, 1, "Nor this.")),
        said(" Both of his sentences.", cite(1, 0, 2, FIRST + SECOND)),
        stop_reason="max_tokens",
        model="some-other-model",
    )
    return script


def test_a_speech_is_wrapped_at_the_page_width():
    printed = typed(LONG)
    assert printed == (
        "The first paragraph runs well past the width of the page, so that it has to be\n"
        "wrapped more than once before it ends, and it does end here.\n"
        "\n"
        "A second paragraph follows a blank line.\n"
        "And a line break is kept as a line break.\n"
    )
    assert max(len(line) for line in printed.splitlines()) <= WIDTH


@pytest.mark.parametrize("size", [1, 2, 3, 7, 40, 1_000])
def test_what_is_printed_does_not_depend_on_how_the_text_was_cut(size):
    pieces = [LONG[start : start + size] for start in range(0, len(LONG), size)]
    assert typed(*pieces) == typed(LONG)


def test_a_line_may_be_as_wide_as_the_page_and_no_wider():
    fits = "a" * 38 + " " + "b" * 39  # 78 columns
    assert typed(fits) == fits + "\n"
    one_too_many = "a" * 38 + " " + "b" * 40  # 79 columns
    assert typed(one_too_many) == "a" * 38 + "\n" + "b" * 40 + "\n"


def test_a_marker_follows_the_last_word_of_its_passage():
    printed = typed("He said so. ", "Then he left.", markers=[1])
    assert printed == "He said so. [1] Then he left.\n"


def test_two_pins_on_a_passage_give_two_markers_and_the_count_runs_on():
    printed = typed("One.", " Two.", " Three.", markers=[2, 0, 1])
    assert printed == "One. [1] [2] Two. Three. [3]\n"


def test_the_next_passage_never_touches_a_marker():
    assert typed("One.", "Two.", markers=[1]) == "One. [1] Two.\n"
    assert typed("One.", "Two.") == "One.Two.\n"  # with no marker, nothing is put between


def test_punctuation_that_follows_a_marker_stays_against_it():
    # The first live sitting on Claude Fable 5.2 printed "than being asked [1] . I offer
    # geometry." The cited passage ended before the full stop, and the next one began with it.
    printed = typed("than being asked", ". I offer geometry.", markers=[1])
    assert printed == "than being asked [1]. I offer geometry.\n"
    assert typed("enough answers", ".", markers=[2]) == "enough answers [1] [2].\n"
    # White space the speaker wrote is kept, and an opening quote is not pulled in.
    assert typed("One", " . Two.", markers=[1]) == "One [1] . Two.\n"
    assert typed("One.", '"Two."', markers=[1]) == 'One. [1] "Two."\n'


def test_a_marker_stays_with_its_paragraph():
    printed = typed("The end of a paragraph.\n\n", "The next one.", markers=[1])
    assert printed == "The end of a paragraph. [1]\n\nThe next one.\n"


def test_a_marker_moves_to_the_next_line_when_it_does_not_fit():
    line = "x" * 76 + "."
    assert typed(line, markers=[1]) == f"{line}\n[1]\n"


def test_white_space_at_the_ends_of_a_speech_is_not_printed():
    assert typed("  \n A speech. \n\n") == "A speech.\n"
    assert typed("   \n\n ") == ""
    assert typed() == ""


def test_many_blank_lines_print_as_one():
    assert typed("One.\n\n\n\n\nTwo.") == "One.\n\nTwo.\n"


def test_a_word_longer_than_the_page_is_left_whole():
    word = "y" * 90
    assert typed(f"Short. {word} after.") == f"Short.\n{word}\nafter.\n"


def test_a_replay_prints_exactly_what_the_live_sitting_printed(personas, tmp_path):
    path = tmp_path / "record.json"
    finished, live = sit(an_eventful_sitting(), blank_record(personas), path, personas)
    assert finished
    assert shown(load(path)) == live


def test_nothing_printed_is_wider_than_the_page(personas, tmp_path):
    _, live = sit(an_eventful_sitting(), blank_record(personas), tmp_path / "r.json", personas)
    assert max(len(line) for line in live.splitlines()) <= WIDTH


def test_a_sitting_carried_on_shows_the_whole_sitting(personas, tmp_path):
    script = an_eventful_sitting()
    path = tmp_path / "record.json"
    stopped = [*script[:5], reply(fails_during=ConnectionError("the line went dead"))]
    with pytest.raises(ConnectionError):
        sit(stopped, blank_record(personas), path, personas)
    finished, carried_on = sit(script[5:], load(path), path, personas)
    assert finished
    assert carried_on == shown(load(path))


def test_the_stand_in_banner_is_printed_above_a_stand_in_record(fixed_record):
    printed = shown(fixed_record)
    assert printed.startswith(
        "STAND-IN RECORD. Its speeches are a script written to test the chamber. No\n"
        "sitting produced them.\n\nTHE CBC  a sitting begun 2026-11-18T19:00:00Z\n"
    )
    assert " ".join(printed.split()).startswith(STAND_IN_BANNER)


def test_a_live_record_has_no_banner(fixed_record):
    printed = shown(fixed_record | {"provenance": "live"})
    assert printed.startswith("THE CBC  a sitting begun 2026-11-18T19:00:00Z\n")
    assert "STAND-IN" not in printed
    assert "No sitting produced them" not in printed


def test_the_top_of_a_sitting_names_the_motion_and_the_seats(fixed_record):
    printed = shown(fixed_record)
    assert "Motion: This house would ban homework.\n" in printed
    assert "Seats: Broad the questioner, Cicero the advocate, Omnibus the storyteller\n" in printed


def test_each_speech_is_printed_under_its_speakers_name(fixed_record):
    printed = shown(fixed_record)
    assert "\nBROAD  opening\nWhat is homework for? [1] If it is practice" not in printed
    assert "\nBROAD  opening\nWhat is homework for? If it is practice, a child needs it." in printed
    assert "\nCICERO  opening\nBroad asks what homework is for. [1] It is practice." in printed
    assert "\nOMNIBUS  opening\nCicero says practice needs time" in printed
    assert (
        "\nCICERO  rebuttal\nBroad has said all of this. [1] I said practice needs time. [2]"
        in printed
    )


def test_the_sentences_read_back_are_printed_from_the_record(fixed_record):
    printed = shown(fixed_record)
    assert (
        '  [1] read back from the motion, sentence 1: "This house would ban homework."\n' in printed
    )
    assert '  [1] read back from Broad, opening, sentence 1: "What is homework for?"\n' in printed
    # Two sentences are shown with a space between them, though the pin's words have none.
    assert (
        '  [1] read back from Cicero, opening, sentences 3 to 4: "Practice needs time.\n'
        '      A school day is too short for it."\n'
    ) in printed


def test_a_relocated_pin_says_so_and_shows_where_the_words_were_found(fixed_record):
    printed = shown(fixed_record)
    assert (
        '  [2] read back from Broad, opening, sentence 5 (relocated): "I will not vote\n'
        '      until I know."\n'
    ) in printed


def test_an_unresolved_pin_is_shown_as_unresolved_with_the_words_it_carried(fixed_record):
    printed = shown(fixed_record)
    assert (
        '  [3] pointed at Omnibus, opening (unresolved): "A tired child learns nothing\n'
        '      at all."\n'
    ) in printed
    assert (
        '  [4] pointed at no paper the chamber could find (unresolved): "Whatever was\n'
        '      meant."\n'
    ) in printed


def test_every_speech_is_followed_by_its_tokens_and_cost(fixed_record):
    printed = shown(fixed_record)
    assert printed.count("  [claude-haiku-5-5: 1,000 tokens in, 200 out, about $0.0002]\n") == 3
    assert "  [some-other-model: 1,000 tokens in, 200 out]\n" in printed


def test_a_declined_speech_is_explained(personas, tmp_path):
    _, live = sit(an_eventful_sitting(), blank_record(personas), tmp_path / "r.json", personas)
    assert "\nOMNIBUS  opening\n  (Claude declined this speech" in live
    assert DECLINED in " ".join(live.split())


def test_an_empty_speech_is_explained_with_its_stop_reason(personas, tmp_path):
    _, live = sit(an_eventful_sitting(), blank_record(personas), tmp_path / "r.json", personas)
    assert "\nCICERO  rebuttal\n  (This reply ended with no speech in it" in live
    assert "Its stop reason was max_tokens.)" in " ".join(live.split())


def test_a_speech_cut_short_is_flagged(personas, tmp_path):
    _, live = sit(an_eventful_sitting(), blank_record(personas), tmp_path / "r.json", personas)
    assert live.count(CUT_SHORT) == 1
    cut_short = live.index(CUT_SHORT)
    assert live.rindex("OMNIBUS  rebuttal", 0, cut_short) > live.index("CICERO  rebuttal")


def test_words_that_arrived_before_a_refusal_are_the_one_thing_a_replay_does_not_show(
    personas, tmp_path
):
    script = plain_sitting()
    script[1] = reply("Half a sentence that was", stop_reason="refusal")
    path = tmp_path / "record.json"
    _, live = sit(script, blank_record(personas), path, personas)
    again = shown(load(path))
    assert "\nCICERO  opening\nHalf a sentence that was\n" in live
    assert "Half a sentence" not in again
    assert live.replace("Half a sentence that was\n", "") == again


def test_a_sitting_that_is_not_finished_says_so(fixed_record):
    printed = shown(fixed_record)
    assert "(This sitting is unfinished: 4 of 9 speeches are in the record.)\n" in printed


def test_the_flow_sheet_of_the_fixed_record(fixed_record):
    # Every number here was counted from the pins written in the fixture, not by the code.
    printed = shown(fixed_record)
    sheet = printed[printed.index("THE FLOW") :]
    assert sheet.startswith("THE FLOW  counted from the pins in this record; no model was asked\n")
    assert "  1  Broad    opening   2 of 5  (Cicero 1, Omnibus 1)\n" in sheet
    assert "  2  Cicero   opening   2 of 4  (Omnibus 2)\n" in sheet
    assert "  3  Omnibus  opening   0 of 3\n" in sheet
    assert "  4  Cicero   rebuttal  0 of 4\n" in sheet
    assert (
        "8 pins: 5 exact, 1 relocated, 2 unresolved. An unresolved pin is shown and\n"
        "never counted as checked. Whole-speech pins, which mark no sentence as read\n"
        "back: 1.\n"
    ) in sheet
    assert "2 of 4 speeches read back another speaker.\n" in sheet
    assert (
        "Estimated cost of the sitting: about $0.0006, not counting 1 speech made by a\n"
        "model with no listed price.\n"
    ) in sheet
    assert " ".join(sheet.split()).endswith(WHAT_A_PIN_PROVES)


def test_the_sheet_counts_what_was_left_standing(fixed_record):
    # Three sentences of speech 1, two of speech 2, three of speech 3 and four of speech 4.
    printed = shown(fixed_record)
    said = " ".join(printed[printed.index("Left standing:") : printed.index("8 pins:")].split())
    assert said == (
        "Left standing: 12 sentences of the openings and rebuttals that no other speaker read "
        "back. Closings are not counted, because almost nobody speaks after them. Not read "
        "back by anyone else is all this says: it does not say that a sentence is right, or "
        "that nobody met it without pointing at it. To list them, replay the record with "
        "--standing."
    )


def test_a_sentence_both_other_speakers_read_back_is_printed_in_full(fixed_record):
    printed = shown(fixed_record)
    assert "No sentence was read back by both other speakers.\n" in printed
    # Omnibus read back sentence 1 of Broad's opening too, as Cicero already had.
    record = copy.deepcopy(fixed_record)
    record["speeches"][2]["segments"][2]["pins"] = [pin(1, 0, 1, BROAD_OPENING[0])]
    printed = shown(record)
    assert "No sentence was read back by both" not in printed
    assert (
        'Read back by both other speakers:\n  Broad, opening, sentence 1: "What is homework for?"\n'
    ) in printed


def test_neighbouring_sentences_read_back_by_both_are_printed_as_one_run(fixed_record):
    # The first live sittings listed neighbours one to a line, though each pair had been read
    # back as one passage. Here Cicero and Omnibus both read back sentences 1 and 2.
    record = copy.deepcopy(fixed_record)
    both = pin(1, 0, 2, BROAD_OPENING[0] + BROAD_OPENING[1])
    record["speeches"][1]["segments"][0]["pins"] = [both]
    record["speeches"][2]["segments"][2]["pins"] = [copy.deepcopy(both)]
    sheet = " ".join(shown(record).split())
    assert (
        "Read back by both other speakers: Broad, opening, sentences 1 to 2: "
        '"What is homework for? If it is practice, a child needs it." Left standing:'
    ) in sheet


def test_the_sheet_lists_in_full_what_was_left_standing_when_asked(fixed_record):
    out = io.StringIO()
    printer.replay(fixed_record, out, standing=True)
    printed = out.getvalue()
    listed = printed[printed.index("Left standing:") : printed.index("8 pins:")]
    assert "--standing" not in listed
    assert listed.split("pointing at it.\n")[1] == (
        "  Broad, opening\n"
        '    2. "If it is practice, a child needs it."\n'
        '    3. "If it is punishment, nobody does."\n'
        '    4. "So I ask which it is."\n'
        "  Cicero, opening\n"
        '    1. "Broad asks what homework is for."\n'
        '    2. "It is practice."\n'
        "  Omnibus, opening\n"
        '    1. "Cicero says practice needs time, and that a school day is too short."\n'
        '    2. "Broad would not vote."\n'
        '    3. "I say a tired child learns nothing."\n'
        "  Cicero, rebuttal\n"
        '    1. "Broad has said all of this."\n'
        '    2. "I said practice needs time."\n'
        '    3. "Omnibus spoke of a tired child."\n'
        '    4. "He is right."\n'
        "\n"
    )


def test_a_speech_that_was_not_delivered_has_a_row_that_says_so(fixed_record):
    record = copy.deepcopy(fixed_record)
    record["speeches"][3] |= {"state": "declined", "segments": [], "sentences": []}
    assert "  4  Cicero   rebuttal  declined\n" in shown(record)


def test_a_sitting_no_model_can_be_priced_for_says_so(fixed_record):
    record = copy.deepcopy(fixed_record)
    for speech in record["speeches"]:
        speech["model"] = "stand-in"
    printed = shown(record)
    assert (
        "No cost can be estimated: no speech was made by a model with a listed price.\n" in printed
    )
    assert "$" not in printed


def test_plain_output_holds_no_colour_codes(personas, tmp_path):
    _, live = sit(an_eventful_sitting(), blank_record(personas), tmp_path / "r.json", personas)
    assert "\x1b" not in live
    assert "\r" not in live
    assert "has the floor" not in live


def test_a_terminal_gets_bold_headings_and_a_waiting_line_that_is_wiped(personas, tmp_path):
    screen = Terminal()
    sit(plain_sitting(), blank_record(personas), tmp_path / "r.json", personas, out=screen)
    printed = screen.getvalue()
    assert "\x1b[1mBROAD  opening\x1b[0m\n" in printed
    waiting = "\x1b[2m(Broad has the floor. Thinking is not shown.)\x1b[0m"
    assert f"{waiting}\r\x1b[2KBroad speaks in the opening." in printed
    assert printed.count("has the floor") == 9


def test_the_waiting_line_is_wiped_even_when_no_words_arrive(personas, tmp_path):
    script = plain_sitting()
    script[0] = reply(stop_reason="refusal")
    screen = Terminal()
    sit(script, blank_record(personas), tmp_path / "r.json", personas, out=screen)
    waiting = "\x1b[2m(Broad has the floor. Thinking is not shown.)\x1b[0m"
    assert f"{waiting}\r\x1b[2K  (Claude declined this speech" in screen.getvalue()


def test_a_replay_on_a_terminal_shows_no_waiting_line(fixed_record):
    screen = Terminal()
    printer.replay(fixed_record, screen)
    assert "has the floor" not in screen.getvalue()
    assert "\x1b[1mTHE FLOW" in screen.getvalue()


def test_counts_are_printed_with_the_right_noun():
    assert printer.counted(1, "pin") == "1 pin"
    assert printer.counted(0, "pin") == "0 pins"
    assert printer.counted(2, "speech", "speeches") == "2 speeches"
    assert printer.counted(1, "speech", "speeches") == "1 speech"
