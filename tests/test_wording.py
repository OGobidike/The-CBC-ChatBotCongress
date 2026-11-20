"""The words the chamber may use for what a pin shows.

A pin shows that words were said and that a speaker pointed at them. It cannot show that a
point was met, beaten or let go, so the code, the help text and the screen never say so.
"""

import io
import re
from pathlib import Path

import pytest
from standin import StandInServer, load_script

import cbc
from cbc import printer
from cbc.chamber import run_sitting
from cbc.cli import build_parser
from cbc.record import new_record
from cbc.seats import load_personas

SOURCE = Path(cbc.__file__).parent

# Each of these claims more than a pin can show.
CLAIMS_TOO_MUCH = re.compile(r"\b(answered|refuted|dropped|won|taken up)\b(?!')", re.IGNORECASE)


def a_whole_screen(tmp_path):
    motion, speeches = load_script()
    personas = load_personas()
    record = new_record(
        motion,
        personas,
        provenance="stand-in",
        started="2026-11-18T19:00:00Z",
        model="claude-fable-5-2",
        effort="medium",
        max_tokens=8_000,
        chair="system",
        fallbacks=True,
    )
    out = io.StringIO()
    client = StandInServer(speeches).client()
    run_sitting(client, record, tmp_path / "record.json", personas, out, provenance="stand-in")
    return out.getvalue()


@pytest.mark.parametrize("path", sorted(SOURCE.glob("*.py")), ids=lambda path: path.name)
def test_no_source_file_claims_more_than_a_pin_can_show(path):
    assert CLAIMS_TOO_MUCH.findall(path.read_text(encoding="utf-8")) == []


def test_the_package_was_found():
    assert {path.name for path in SOURCE.glob("*.py")} >= {"chamber.py", "flow.py", "printer.py"}


def test_the_help_text_claims_no_more():
    parser = build_parser()
    commands = parser._subparsers._group_actions[0].choices.values()
    for text in (parser.format_help(), *(command.format_help() for command in commands)):
        assert CLAIMS_TOO_MUCH.findall(text) == []


def test_the_screen_claims_no_more(tmp_path):
    screen = a_whole_screen(tmp_path)
    assert CLAIMS_TOO_MUCH.findall(screen) == []
    assert "read back from" in screen
    assert "Left standing" in screen
    assert "Not read back by anyone else" in " ".join(screen.split())


def test_the_other_notes_claim_no_more():
    notes = (printer.DECLINED, printer.EMPTY, printer.CUT_SHORT, printer.STAND_IN_BANNER)
    assert CLAIMS_TOO_MUCH.findall(" ".join(notes)) == []


def test_the_check_would_catch_each_word():
    for claim in ("answered", "Refuted", "dropped", "won", "taken up"):
        assert CLAIMS_TOO_MUCH.findall(f"the point was {claim} by Cicero")
    assert CLAIMS_TOO_MUCH.findall("answer the point; it won't drop; a wonder") == []
