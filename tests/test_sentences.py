import pytest

from cbc.sentences import split

ODD = [
    "",
    "   \n\n  ",
    "No full stop at the end",
    "One. Two! Three? Four",
    'He said "No." Then he left.',
    "A point (and an aside.) Another point.",
    "It rose 3.5 per cent, e.g. in March... and then fell",
    "A first paragraph\n\nA second, with no full stop\n\n\nA third",
    "Curly quotes: “Is it so?” ‘Quite so.’ Then on.",
    "…?!.",
    "1. One item\n2. Another item",
    "\tTabs and  double  spaces.  Kept inside a sentence.\n",
]


def test_a_speech_is_cut_at_full_stops_question_marks_and_exclamation_marks():
    assert split("One. Two! Three? Four") == ["One.", "Two!", "Three?", "Four"]


def test_closing_quotes_and_brackets_stay_with_their_sentence():
    assert split('He said "No." Then he left.') == ['He said "No."', "Then he left."]
    assert split("A point (and an aside.) Another.") == ["A point (and an aside.)", "Another."]
    assert split("“Is it so?” ‘Quite so.’ Then on.") == ["“Is it so?”", "‘Quite so.’", "Then on."]


def test_a_full_stop_inside_a_number_does_not_end_a_sentence():
    assert split("It rose 3.5 per cent. Then it fell.") == [
        "It rose 3.5 per cent.",
        "Then it fell.",
    ]


def test_a_blank_line_ends_a_sentence_that_has_no_full_stop():
    assert split("A heading\n\nThe body. More body.") == ["A heading", "The body.", "More body."]


def test_a_single_line_break_does_not_end_a_sentence():
    assert split("A line that runs\nonto the next. Done.") == [
        "A line that runs\nonto the next.",
        "Done.",
    ]


def test_a_wrong_cut_only_makes_two_small_pieces():
    # The cut after "e.g." is wrong, and harmless: no letter is lost or moved.
    pieces = split("Take a trade, e.g. baking. It needs flour.")
    assert pieces == ["Take a trade, e.g.", "baking.", "It needs flour."]
    assert " ".join(pieces) == "Take a trade, e.g. baking. It needs flour."


def test_nothing_gives_no_sentences():
    assert split("") == []
    assert split("   \n\n  ") == []


@pytest.mark.parametrize("text", ODD)
def test_no_piece_is_empty_and_none_has_space_at_its_ends(text):
    for piece in split(text):
        assert piece
        assert piece == piece.strip()


@pytest.mark.parametrize("text", ODD)
def test_every_letter_survives_in_order(text):
    assert "".join("".join(split(text)).split()) == "".join(text.split())


@pytest.mark.parametrize("text", ODD)
def test_the_same_text_always_gives_the_same_sentences(text):
    assert split(text) == split(text)


@pytest.mark.parametrize("text", ODD)
def test_cutting_a_sentence_again_leaves_it_whole(text):
    # A paper is sent one sentence to a block, so a sentence must not split any further.
    for piece in split(text):
        assert split(piece) == [piece]
