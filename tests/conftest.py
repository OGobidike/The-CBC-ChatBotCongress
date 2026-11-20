"""Stand-ins for Claude, so the tests need no key, no network and no money.

Every speech in these tests is a script written to test the chamber. No sitting produced any
of them, and the records they make are marked "stand-in". The few tests that need a record
marked "live", to check how that label is handled, make it in memory or in a temporary folder.
"""

import copy
import socket
from types import SimpleNamespace

import pytest

from cbc.chair import order
from cbc.record import new_record
from cbc.seats import SEATS

MOTION = "This house would rather be told a hard truth than a kind story."
STARTED = "2026-11-18T19:00:00Z"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Fail any test that tries to open a network connection."""

    def refuse(*args, **kwargs):
        raise AssertionError("a test tried to reach the network")

    monkeypatch.setattr(socket.socket, "connect", refuse)


@pytest.fixture
def personas():
    """Three short stand-ins for the character files."""
    return {seat: f"You are {seat}. (A stand-in for the character file.)\n" for seat in SEATS}


def blank_record(personas, motion=MOTION, **settings):
    """A record with no speeches yet, marked as a stand-in."""
    chosen = {
        "model": "claude-fable-5-2",
        "effort": "medium",
        "max_tokens": 8_000,
        "chair": "system",
        "fallbacks": True,
    } | settings
    return new_record(motion, personas, provenance="stand-in", started=STARTED, **chosen)


def cite(document, first, last, words, kind="content_block_location"):
    """A citation as the SDK hands it over: a pointer at blocks first to last of a document."""
    return SimpleNamespace(
        type=kind,
        cited_text=words,
        document_index=document,
        start_block_index=first,
        end_block_index=last,
    )


def said(text, *citations):
    """One text block of a reply, with the citations that came with it."""
    return SimpleNamespace(type="text", text=text, citations=list(citations) or None)


def thinking_block():
    return SimpleNamespace(type="thinking", thinking="", signature="sig")


def spent(input_tokens=120, output_tokens=40, cache_write=0, cache_read=0, thinking=None):
    details = None if thinking is None else SimpleNamespace(thinking_tokens=thinking)
    return SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_input_tokens=cache_write,
        cache_read_input_tokens=cache_read,
        output_tokens_details=details,
    )


def reply(
    *passages,
    model="claude-fable-5-2",
    stop_reason="end_turn",
    usage=None,
    fails_before=None,
    fails_during=None,
    cut_off=False,
):
    """Script one reply: its passages in order (a plain string is a passage with no citation).

    `fails_before` is raised on opening the stream, where the SDK raises a missing key or a
    refused request. `fails_during` is raised after the passages have streamed. A `cut_off`
    reply ends without the event that closes a whole one.
    """
    blocks = [said(passage) if isinstance(passage, str) else passage for passage in passages]
    final = SimpleNamespace(
        content=[thinking_block(), *blocks],
        model=model,
        stop_reason=stop_reason,
        usage=spent() if usage is None else usage,
    )
    return SimpleNamespace(
        final=final, fails_before=fails_before, fails_during=fails_during, cut_off=cut_off
    )


def plain_sitting():
    """Nine short replies in the Chair's order, two sentences each and no citations."""
    return [
        reply(f"{seat} speaks in the {round_name}. This is speech {number} of the sitting.")
        for number, (seat, round_name) in enumerate(order(), start=1)
    ]


class FakeStream:
    """Behaves like the SDK's stream: a context manager that yields events, then the reply."""

    def __init__(self, scripted):
        self._scripted = scripted

    def __enter__(self):
        if self._scripted.fails_before is not None:
            raise self._scripted.fails_before
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        for block in self._scripted.final.content:
            if block.type == "text":
                middle = len(block.text) // 2
                for piece in (block.text[:middle], block.text[middle:]):
                    yield SimpleNamespace(type="text", text=piece)
            yield SimpleNamespace(type="content_block_stop", content_block=block)
        if self._scripted.fails_during is not None:
            raise self._scripted.fails_during
        if not self._scripted.cut_off:
            yield SimpleNamespace(type="message_stop")

    def get_final_message(self):
        return self._scripted.final


class FakeMessages:
    def __init__(self, script, calls, endpoint):
        self._script = script
        self._calls = calls
        self._endpoint = endpoint

    def stream(self, **request):
        self._calls.append({"endpoint": self._endpoint, **copy.deepcopy(request)})
        return FakeStream(self._script.pop(0))


class FakeClient:
    """Plays back scripted replies and records every request it was sent."""

    def __init__(self, *script):
        self.script = list(script)
        self.calls = []
        self.messages = FakeMessages(self.script, self.calls, "messages")
        self.beta = SimpleNamespace(messages=FakeMessages(self.script, self.calls, "beta.messages"))


def pin(paper, first, last, words, check="exact", **stated):
    return {"paper": paper, "first": first, "last": last, "words": words, "check": check} | stated


def speech(n, seat, round_name, sentences, *segments, **changes):
    """A scripted speech for a record. Each segment is (text, pin, pin, ...)."""
    return {
        "n": n,
        "seat": seat,
        "round": round_name,
        "model": "claude-haiku-5-5",
        "stop_reason": "end_turn",
        "state": "delivered",
        "segments": [{"text": text, "pins": list(pins)} for text, *pins in segments],
        "sentences": sentences,
        "usage": {
            "input_tokens": 1_000,
            "output_tokens": 200,
            "thinking_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        },
    } | changes


HOMEWORK = "This house would ban homework."
BROAD_OPENING = [
    "What is homework for?",
    "If it is practice, a child needs it.",
    "If it is punishment, nobody does.",
    "So I ask which it is.",
    "I will not vote until I know.",
]


@pytest.fixture
def fixed_record(personas):
    """Four scripted speeches that hold one pin of every kind.

    The sentences and the pins are spelled out here, not made by the code under test, so
    the tests that use this record check the code against work it did not do itself.
    """
    record = blank_record(personas, motion=HOMEWORK, model="claude-haiku-5-5")
    record["speeches"] = [
        speech(
            1, "Broad", "opening", BROAD_OPENING, (" ".join(BROAD_OPENING), pin(0, 0, 1, HOMEWORK))
        ),
        speech(
            2,
            "Cicero",
            "opening",
            [
                "Broad asks what homework is for.",
                "It is practice.",
                "Practice needs time.",
                "A school day is too short for it.",
            ],
            ("Broad asks what homework is for.", pin(1, 0, 1, "What is homework for?")),
            (" It is practice. Practice needs time. A school day is too short for it.",),
        ),
        speech(
            3,
            "Omnibus",
            "opening",
            [
                "Cicero says practice needs time, and that a school day is too short.",
                "Broad would not vote.",
                "I say a tired child learns nothing.",
            ],
            (
                "Cicero says practice needs time, and that a school day is too short.",
                pin(2, 2, 4, "Practice needs time.A school day is too short for it."),
            ),
            (
                " Broad would not vote.",
                # The place stated was sentence 1. The words stand at sentence 5.
                pin(1, 4, 5, BROAD_OPENING[4], "relocated", stated_first=0, stated_last=1),
            ),
            (" I say a tired child learns nothing.",),
        ),
        speech(
            4,
            "Cicero",
            "rebuttal",
            [
                "Broad has said all of this.",
                "I said practice needs time.",
                "Omnibus spoke of a tired child.",
                "He is right.",
            ],
            # A pin over the whole of a five-sentence speech.
            ("Broad has said all of this.", pin(1, 0, 5, "".join(BROAD_OPENING))),
            # A pin on the speaker's own earlier speech.
            (" I said practice needs time.", pin(2, 2, 3, "Practice needs time.")),
            # Words that speech 3 never said.
            (
                " Omnibus spoke of a tired child.",
                pin(3, 2, 3, "A tired child learns nothing at all.", "unresolved"),
            ),
            # A pointer that named no paper the chamber could read.
            (" He is right.", pin(None, None, None, "Whatever was meant.", "unresolved")),
            model="some-other-model",
        ),
    ]
    return record
