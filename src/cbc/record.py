"""The record of a sitting: the file a debate leaves behind, and the check anyone can run.

The format, cbc-record/1, is the contract. Whatever runs a sitting writes this file, and
whatever shows one reads it. A record holds every speech as it was said, cut into sentences,
and every pin: a pointer from a passage of one speech to the sentences of an earlier paper
that the speaker pointed at while saying it. Paper 0 is the motion and paper n is speech n.

A pin names sentences `first` to `last` of its paper, `last` exclusive, and carries the
cited `words` exactly as the API gave them and a `check`: how well the pointer held against
the record. A relocated pin also keeps the API's own numbers, as `stated_first` and
`stated_last`. A pin made from a citation that named no paper the chamber could read has
null for its paper and its place.

A pin is checked with plain code, and a record can be checked again by anyone with no API
key. What that proves is limited, and WHAT_A_PIN_PROVES says how.
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from cbc import __version__
from cbc.chair import WORDS
from cbc.seats import SCHOOLS, SEATS
from cbc.sentences import split

FORMAT = "cbc-record/1"
MOTION = 0  # the paper number of the motion; speech n is paper n

# "stand-in" marks a record whose replies are a script written to test the chamber.
PROVENANCES = ("live", "stand-in")

# delivered: the speech has text. declined: Claude declined the request. empty: the reply
# ended with no text at all. Only a delivered speech is a paper that others can point at.
STATES = ("delivered", "declined", "empty")

# exact: the words stand at the stated place, letter for letter. relocated: they stand in
# the same paper, but not letter for letter at that place. unresolved: they were not found.
CHECKS = ("exact", "relocated", "unresolved")

WHAT_A_PIN_PROVES = (
    "A pin proves two things only: the words are in the record at the place named, and the "
    "speaker pointed at them. It does not prove the answer is a good one, or that the "
    "speaker's own sentence beside it states the point fairly."
)


def new_record(
    motion: str,
    personas: dict[str, str],
    *,
    provenance: str,
    started: str,
    model: str,
    effort: str,
    max_tokens: int,
    chair: str,
    fallbacks: bool,
) -> dict[str, Any]:
    """An empty record for one sitting: the motion, the settings and the seats, no speeches.

    The settings are what every request of the sitting is sent with, and each seat carries
    the sha256 of its character file, so the record says what the sitting was held with.
    The start time is passed in, so that the same inputs always give the same record.
    """
    if provenance not in PROVENANCES:
        raise ValueError(f"provenance must be one of {', '.join(PROVENANCES)}; got {provenance!r}")
    if not split(motion):
        raise ValueError("the motion is empty")
    return {
        "format": FORMAT,
        "producer": {"name": "cbc", "version": __version__, "runner": "local"},
        "provenance": provenance,
        "started": started,
        "motion": motion,
        "motion_sentences": split(motion),
        "settings": {
            "model": model,
            "effort": effort,
            "max_tokens": max_tokens,
            "chair": chair,
            # Whether a server-side fallback is asked for, on the models that have one.
            "fallbacks": fallbacks,
            "words": dict(WORDS),
        },
        "seats": seat_entries(personas),
        "speeches": [],
    }


def seat_entries(personas: dict[str, str]) -> list[dict[str, str]]:
    """Each seat as the record names it: who, which school, and which character file."""
    return [
        {
            "name": seat,
            "school": SCHOOLS[seat],
            "persona_sha256": hashlib.sha256(personas[seat].encode("utf-8")).hexdigest(),
        }
        for seat in SEATS
    ]


def paper_sentences(record: dict[str, Any], paper: int) -> list[str]:
    """The sentences of one paper: the motion's, or those of the speech with that number."""
    if paper == MOTION:
        return record["motion_sentences"]
    return record["speeches"][paper - 1]["sentences"]


def pins_of(speech: dict[str, Any]) -> list[dict[str, Any]]:
    """Every pin of a speech, in the order its passages were said."""
    return [pin for segment in speech["segments"] for pin in segment["pins"]]


def count_checks(record: dict[str, Any]) -> dict[str, int]:
    """How many pins the record holds, by how well each one checked."""
    counts = dict.fromkeys(CHECKS, 0)
    for speech in record["speeches"]:
        for pin in pins_of(speech):
            counts[pin["check"]] += 1
    return counts


def make_pin(sentences: list[str], paper: int, first: int, last: int, words: str) -> dict[str, Any]:
    """Check a pointer against the paper it names, and return the pin with its verdict.

    `words` is what the API said was cited and `first`/`last` are the sentences it named,
    `last` exclusive. The pin is exact when those sentences, joined with nothing between
    them, are the words. Failing that, the paper is searched for a run of sentences that
    says the same once all white space is taken out of both; a pin found that way is
    relocated, and it keeps the API's own numbers beside the place found. Anything else is
    kept as unresolved, to be shown and never counted as checked.
    """
    pin = {"paper": paper, "first": first, "last": last, "words": words, "check": "unresolved"}
    if 0 <= first < last <= len(sentences) and "".join(sentences[first:last]) == words:
        return pin | {"check": "exact"}
    found = _find(sentences, words)
    if found is None:
        return pin
    return pin | {
        "first": found[0],
        "last": found[1],
        "check": "relocated",
        "stated_first": first,
        "stated_last": last,
    }


def unplaced_pin(words: str) -> dict[str, Any]:
    """A pin for a pointer that names no paper the chamber can read. It stays unresolved."""
    return {"paper": None, "first": None, "last": None, "words": words, "check": "unresolved"}


def _find(sentences: list[str], words: str) -> tuple[int, int] | None:
    """The first run of sentences that says `words`, comparing with white space taken out."""
    wanted = "".join(words.split())
    if not wanted:
        return None
    for first in range(len(sentences)):
        run = ""
        for last in range(first + 1, len(sentences) + 1):
            run += "".join(sentences[last - 1].split())
            if run == wanted:
                return first, last
            if not wanted.startswith(run):
                break
    return None


def verify(record: dict[str, Any]) -> list[str]:
    """Every fault in a record, in plain words. An empty list means the record holds.

    It needs no client and no key: the record holds both the sentences and the pins, so
    every pin is checked again here exactly as it was checked when it was made.
    """
    try:
        return _faults(record)
    except (AttributeError, IndexError, KeyError, TypeError) as error:
        # A file that is not a record at all should get a plain verdict, not a traceback.
        problem = f"{type(error).__name__}: {error}"
        return [f"this is not shaped like a {FORMAT} record ({problem})"]


def _faults(record: dict[str, Any]) -> list[str]:
    if record.get("format") != FORMAT:
        return [f"the format is {record.get('format')!r}, not {FORMAT!r}"]
    faults = []
    if record["provenance"] not in PROVENANCES:
        faults.append(f"the provenance is {record['provenance']!r}")
    if record["motion_sentences"] != split(record["motion"]):
        faults.append("the motion's sentences are not the motion, cut into sentences")
    speeches = record["speeches"]
    numbers = [speech["n"] for speech in speeches]
    if numbers != list(range(1, len(speeches) + 1)):
        # Pins name papers by number, so nothing past this point could be trusted.
        return [*faults, f"the speeches are numbered {numbers}, not 1 to {len(speeches)}"]
    for speech in speeches:
        faults += _speech_faults(record, speech)
    return faults


def _speech_faults(record: dict[str, Any], speech: dict[str, Any]) -> list[str]:
    where = f"speech {speech['n']} ({speech['seat']}, {speech['round']})"
    state = speech["state"]
    if state not in STATES:
        return [f"{where}: its state is {state!r}"]
    if state != "delivered":
        if speech["segments"] or speech["sentences"]:
            return [f"{where}: it is {state}, yet it holds text"]
        return []
    faults = []
    text = "".join(segment["text"] for segment in speech["segments"])
    if speech["sentences"] != split(text):
        faults.append(f"{where}: its sentences are not its text, cut into sentences")
    if not speech["sentences"]:
        faults.append(f"{where}: it is delivered, yet it has no text")
    for number, pin in enumerate(pins_of(speech), start=1):
        fault = _pin_fault(record, speech["n"], pin)
        if fault:
            faults.append(f"{where}, pin {number}: {fault}")
    return faults


def _pin_fault(record: dict[str, Any], n: int, pin: dict[str, Any]) -> str | None:
    """What is wrong with one pin of speech `n`, or None when it holds."""
    paper = pin["paper"]
    if paper is None:
        if pin["check"] == "unresolved":
            return None
        return f"it names no paper, yet it is stored as {pin['check']}"
    if not isinstance(paper, int) or not 0 <= paper < n:
        return f"it points at paper {paper!r}, which is not an earlier one"
    if paper != MOTION and record["speeches"][paper - 1]["state"] != "delivered":
        return f"it points at speech {paper}, which is {record['speeches'][paper - 1]['state']}"
    stated = pin.get("stated_first", pin["first"]), pin.get("stated_last", pin["last"])
    now = make_pin(paper_sentences(record, paper), paper, *stated, pin["words"])
    if now["check"] != pin["check"]:
        return f"it is stored as {pin['check']}, but against the record it is {now['check']}"
    if now != pin:
        return "the place it stores is not the place its words are found"
    return None


def save(record: dict[str, Any], path: str | Path) -> None:
    """Write the record whole or not at all: to a draft beside it, then into place.

    A sitting saves after every speech, so a crash part of the way through a write must
    never leave half a file where the last good record was.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    draft = path.with_name(path.name + ".tmp")
    with open(draft, "w", encoding="utf-8", newline="\n") as file:
        json.dump(record, file, indent=2, ensure_ascii=False)
        file.write("\n")
    os.replace(draft, path)


def load(path: str | Path) -> dict[str, Any]:
    """Read a record file. It is not checked here: call verify on what comes back."""
    with open(path, encoding="utf-8") as file:
        return json.load(file)
