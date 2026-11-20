"""Everything the terminal shows. A live sitting and a replay print through the same code.

So a replay shows what the sitting showed. The one exception is a speech that was declined
or came back with no words: whatever arrived of it was on the live screen, and the record
does not keep it.

Output is plain text, wrapped at 78 columns. Only a terminal gets anything more: bold
headings, dimmed notes, and, while a speech is awaited, a waiting line that is wiped as soon
as there is something to print.
"""

import textwrap
from typing import Any, TextIO

from cbc import chair
from cbc.flow import flow
from cbc.pricing import dollars, usage_line
from cbc.record import MOTION, WHAT_A_PIN_PROVES, paper_sentences, pins_of

WIDTH = 78

STAND_IN_BANNER = (
    "STAND-IN RECORD. Its speeches are a script written to test the chamber. "
    "No sitting produced them."
)
DECLINED = (
    "(Claude declined this speech, so the record holds no words for it and later speakers "
    "are not shown it.)"
)
EMPTY = (
    "(This reply ended with no speech in it, so later speakers are not shown it. "
    "Its stop reason was {stop_reason}.)"
)
CUT_SHORT = "(This speech reached its length limit and was cut short.)"

_BOLD = "\x1b[1m"
_DIM = "\x1b[2m"
_PLAIN = "\x1b[0m"
_WIPE_LINE = "\r\x1b[2K"

# Punctuation that closes the sentence before it, so it is printed against a marker.
_CLOSES_A_SENTENCE = ".,;:!?)]’”"


def _is_terminal(out: TextIO) -> bool:
    return hasattr(out, "isatty") and out.isatty()


def _say(
    out: TextIO, text: str, indent: str = "", hang: str | None = None, style: str = ""
) -> None:
    """Print one paragraph, wrapped, with every line after the first indented by `hang`."""
    lines = textwrap.wrap(
        text,
        WIDTH,
        initial_indent=indent,
        subsequent_indent=indent if hang is None else hang,
        break_long_words=False,
        break_on_hyphens=False,
    )
    for line in lines:
        styled = f"{style}{line}{_PLAIN}" if style and _is_terminal(out) else line
        out.write(styled + "\n")


def counted(number: int, one: str, many: str | None = None) -> str:
    """A count with its noun: "1 pin", "3 pins", "2 speeches"."""
    return f"{number} {one if number == 1 else many or one + 's'}"


class Typist:
    """Prints one speech as its words arrive, wrapped at WIDTH columns.

    A live sitting feeds it the pieces of a streamed reply, and a replay feeds it the
    segments in the record. What it prints depends only on the characters and on where the
    markers fall, never on how the text was cut into pieces, which is why the two showings
    cannot differ. A word is printed once it is complete, so no line is ever taken back.
    """

    def __init__(self, out: TextIO, waiting_for: str | None = None) -> None:
        self._out = out
        self._word = ""  # the letters that have arrived since the last white space
        self._gap = False  # white space is waiting to be printed before the next word
        self._breaks = 0  # how many line breaks that white space held
        self._column = 0
        self._markers = 0
        self._after_marker = False  # a marker was just printed, with no white space after it
        self._begun = False
        # Thinking is not shown, so on a terminal a line says who the chamber is waiting for.
        self._waiting = waiting_for is not None and _is_terminal(out)
        if self._waiting:
            out.write(f"{_DIM}({waiting_for} has the floor. Thinking is not shown.){_PLAIN}")
            out.flush()

    def words(self, text: str) -> None:
        """Take the next piece of the speech, and print the words it completes."""
        for character in text:
            if character.isspace():
                self._put_word()
                self._gap = True
                self._breaks += character == "\n"
            else:
                self._word += character
        self._out.flush()

    def markers(self, count: int) -> None:
        """Number the pins of the passage that just ended, straight after its last word."""
        self._put_word()
        for _ in range(count):
            self._markers += 1
            self._put(f"[{self._markers}]", gap=True, breaks=0)
        # White space the passage ended with is still waiting, and comes after the markers.
        # With none waiting, the next passage is kept off the marker by a space, unless it
        # opens with the punctuation that closes the sentence just pinned.
        self._after_marker = count > 0 and not self._gap
        self._out.flush()

    def close(self) -> None:
        """End the speech: print the last word, and finish the line if there is one."""
        self._put_word()
        self._wipe_waiting_line()
        if self._begun:
            self._out.write("\n")
        self._out.flush()

    def _put_word(self) -> None:
        if self._word:
            apart = self._after_marker and self._word[0] not in _CLOSES_A_SENTENCE
            self._put(self._word, self._gap or apart, self._breaks)
            self._word, self._gap, self._breaks, self._after_marker = "", False, 0, False

    def _put(self, token: str, gap: bool, breaks: int) -> None:
        """Write one word or marker: on this line if it fits, on the next if it does not."""
        self._wipe_waiting_line()
        if not self._begun:
            lead = ""
        elif breaks:
            lead = "\n" * min(breaks, 2)  # one line break, or one blank line between paragraphs
        elif gap and self._column + 1 + len(token) > WIDTH:
            lead = "\n"
        else:
            lead = " " if gap else ""
        self._out.write(lead + token)
        self._column = len(token) if "\n" in lead else self._column + len(lead) + len(token)
        self._begun = True

    def _wipe_waiting_line(self) -> None:
        if self._waiting:
            self._out.write(_WIPE_LINE)
            self._waiting = False


def opening(record: dict[str, Any], out: TextIO) -> None:
    """The top of a sitting: the stand-in banner where it applies, the motion and the seats."""
    if record["provenance"] == "stand-in":
        _say(out, STAND_IN_BANNER)
        out.write("\n")
    _say(out, f"THE CBC  a sitting begun {record['started']}", style=_BOLD)
    _say(out, f"Motion: {record['motion']}", hang="  ")
    seats = ", ".join(f"{seat['name']} {seat['school']}" for seat in record["seats"])
    _say(out, f"Seats: {seats}", hang="  ")


def heading(seat: str, round_name: str, out: TextIO) -> None:
    """The line above a speech: who speaks, and in which round."""
    out.write("\n")
    _say(out, f"{seat.upper()}  {round_name}", style=_BOLD)


def notes(speech: dict[str, Any], record: dict[str, Any], out: TextIO) -> None:
    """What follows a speech: the sentences it read back, anything amiss, and its cost."""
    if speech["state"] == "delivered":
        out.write("\n")
    for number, pin in enumerate(pins_of(speech), start=1):
        _say(out, _read_back(number, pin, record), indent="  ", hang="      ", style=_DIM)
    if speech["state"] == "declined":
        _say(out, DECLINED, indent="  ")
    elif speech["state"] == "empty":
        _say(out, EMPTY.format(stop_reason=speech["stop_reason"]), indent="  ")
    elif speech["stop_reason"] == "max_tokens":
        _say(out, CUT_SHORT, indent="  ")
    _say(out, usage_line(speech["model"], speech["usage"]), indent="  ", style=_DIM)


def _read_back(number: int, pin: dict[str, Any], record: dict[str, Any]) -> str:
    """One read-back line.

    For a pin that checked, the quoted words are the record's own sentences, not the API's
    copy of them. An unresolved pin has only the words it carried, so those are shown.
    """
    if pin["check"] == "unresolved":
        where = "no paper the chamber could find"
        if pin["paper"] is not None:
            where = _paper_name(record, pin["paper"])
        words = " ".join(pin["words"].split())
        return f'[{number}] pointed at {where} (unresolved): "{words}"'
    first, last = pin["first"], pin["last"]
    which = _sentence_numbers(first, last)
    relocated = " (relocated)" if pin["check"] == "relocated" else ""
    words = " ".join(paper_sentences(record, pin["paper"])[first:last])
    name = _paper_name(record, pin["paper"])
    return f'[{number}] read back from {name}, {which}{relocated}: "{words}"'


def _sentence_numbers(first: int, last: int) -> str:
    """How a run of sentences is named on the page, counting from one."""
    return f"sentence {first + 1}" if last - first == 1 else f"sentences {first + 1} to {last}"


def _paper_name(record: dict[str, Any], paper: int) -> str:
    if paper == MOTION:
        return "the motion"
    speech = record["speeches"][paper - 1]
    return f"{speech['seat']}, {speech['round']}"


def recorded_speech(speech: dict[str, Any], record: dict[str, Any], out: TextIO) -> None:
    """Print one speech from the record, the way it was printed when it was made."""
    heading(speech["seat"], speech["round"], out)
    typist = Typist(out)
    for segment in speech["segments"]:
        typist.words(segment["text"])
        typist.markers(len(segment["pins"]))
    typist.close()
    notes(speech, record, out)


def stopped_at_cost(record: dict[str, Any], spent: float, limit: float, out: TextIO) -> None:
    """Say that the cost limit ended the sitting early, and before which speech."""
    seat, round_name = chair.order()[len(record["speeches"])]
    out.write("\n")
    _say(
        out,
        f"(The sitting stopped before {seat}'s {round_name}: its estimated cost so far, "
        f"${spent:.4f}, has reached the limit of {dollars(limit)}. The record is kept, and the "
        "sitting can be carried on from it.)",
    )


def closing(record: dict[str, Any], out: TextIO, *, standing: bool = False) -> None:
    """The end of a sitting: the flow sheet, and a note first if speeches are still to come."""
    held, due = len(record["speeches"]), len(chair.order())
    if held < due:
        out.write("\n")
        _say(out, f"(This sitting is unfinished: {held} of {due} speeches are in the record.)")
    flow_sheet(record, out, standing=standing)


def flow_sheet(record: dict[str, Any], out: TextIO, *, standing: bool = False) -> None:
    """Print the flow: what was read back, what was left standing, and the totals.

    Most sentences of a sitting are read back by nobody, so the sentences left standing are
    counted, and listed in full only when `standing` is asked for.
    """
    sheet = flow(record)
    out.write("\n")
    _say(out, "THE FLOW  counted from the pins in this record; no model was asked", style=_BOLD)
    out.write("\n")
    _say(
        out,
        "Sentences of each speech that another speaker read back, with a count for each "
        "speaker who did:",
    )
    for row in sheet["speeches"]:
        _say(out, _flow_row(row), indent="  ", hang="      ")

    out.write("\n")
    _by_both(sheet, record, out)
    out.write("\n")
    _left_standing(sheet, record, out, in_full=standing)

    checks = sheet["checks"]
    out.write("\n")
    _say(
        out,
        f"{counted(sum(checks.values()), 'pin')}: {checks['exact']} exact, "
        f"{checks['relocated']} relocated, {checks['unresolved']} unresolved. An unresolved "
        "pin is shown and never counted as checked. "
        f"Whole-speech pins, which mark no sentence as read back: {sheet['whole_speech_pins']}.",
    )
    _say(
        out,
        f"{sheet['speeches_reading_back']} of {counted(sheet['delivered'], 'speech', 'speeches')} "
        "read back another speaker.",
    )
    _say(out, _cost_line(sheet))
    out.write("\n")
    _say(out, WHAT_A_PIN_PROVES)


def _by_both(sheet: dict[str, Any], record: dict[str, Any], out: TextIO) -> None:
    """The sentences that both other speakers read back, each in full."""
    rows = [row for row in sheet["speeches"] if row["by_both"]]
    if not rows:
        _say(out, "No sentence was read back by both other speakers.")
        return
    _say(out, "Read back by both other speakers:")
    for row in rows:
        sentences = paper_sentences(record, row["n"])
        for first, last in _runs(row["by_both"]):
            where = f"{row['seat']}, {row['round']}, {_sentence_numbers(first, last)}"
            words = " ".join(sentences[first:last])
            _say(out, f'{where}: "{words}"', indent="  ", hang="      ")


def _runs(indexes: list[int]) -> list[tuple[int, int]]:
    """Sorted sentence indexes as runs of neighbours, each (first, last) with last exclusive."""
    runs: list[tuple[int, int]] = []
    for index in indexes:
        if runs and runs[-1][1] == index:
            runs[-1] = (runs[-1][0], index + 1)
        else:
            runs.append((index, index + 1))
    return runs


def _left_standing(
    sheet: dict[str, Any], record: dict[str, Any], out: TextIO, *, in_full: bool
) -> None:
    """How many sentences nobody else read back, and the sentences themselves when asked."""
    count = sum(len(row["left_standing"]) for row in sheet["speeches"])
    _say(
        out,
        f"Left standing: {counted(count, 'sentence')} of the openings and rebuttals that no "
        "other speaker read back. Closings are not counted, because almost nobody speaks "
        "after them. Not read back by anyone else is all this says: it does not say that a "
        "sentence is right, or that nobody met it without pointing at it."
        + ("" if in_full else " To list them, replay the record with --standing."),
    )
    if not in_full:
        return
    for row in sheet["speeches"]:
        if not row["left_standing"]:
            continue
        _say(out, f"{row['seat']}, {row['round']}", indent="  ")
        sentences = paper_sentences(record, row["n"])
        for index in row["left_standing"]:
            _say(out, f'{index + 1}. "{sentences[index]}"', indent="    ", hang="       ")


def _flow_row(row: dict[str, Any]) -> str:
    name = f"{row['n']}  {row['seat']:<8} {row['round']:<9}"
    if row["state"] != "delivered":
        return f"{name} {row['state']}"
    who = ", ".join(f"{seat} {count}" for seat, count in row["by"].items())
    read_back = f"{len(row['read_back'])} of {row['sentences']}"
    return f"{name} {read_back}  ({who})" if who else f"{name} {read_back}"


def _cost_line(sheet: dict[str, Any]) -> str:
    unpriced, speeches = sheet["unpriced"], len(sheet["speeches"])
    if speeches and unpriced == speeches:
        return "No cost can be estimated: no speech was made by a model with a listed price."
    line = f"Estimated cost of the sitting: about ${sheet['cost']:.4f}"
    if unpriced:
        left_out = counted(unpriced, "speech", "speeches")
        line += f", not counting {left_out} made by a model with no listed price"
    return line + "."


def replay(record: dict[str, Any], out: TextIO, *, standing: bool = False) -> None:
    """Print a recorded sitting from its file alone: no client, no key, no network."""
    opening(record, out)
    for speech in record["speeches"]:
        recorded_speech(speech, record, out)
    closing(record, out, standing=standing)
