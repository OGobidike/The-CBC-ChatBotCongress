"""One sitting of the chamber: what is sent to Claude for each speech, and what is kept.

Every speech is one fresh request, built from the record and nothing else. The motion and
each speech made so far are handed to the speaker as citable documents, one block to a
sentence. When Claude's reply cites one, the citation comes back as a pointer to the exact
sentences, and the chamber keeps it in the record as a pin.

Because nothing but the record goes into a request, a sitting that stopped part of the way
through can be carried on from its file.
"""

from pathlib import Path
from typing import Any, TextIO

from cbc import chair, printer
from cbc.pricing import sitting_cost
from cbc.record import MOTION, make_pin, paper_sentences, save, seat_entries, unplaced_pin
from cbc.seats import charter
from cbc.sentences import split

DEFAULT_MODEL = "claude-fable-5-2"
DEFAULT_EFFORT = "medium"
EFFORTS = ("low", "medium", "high", "xhigh", "max")

# The most one reply may cost in output tokens. Thinking counts as output too.
DEFAULT_MAX_TOKENS = 8_000

# The sitting stops before a speech once its estimated cost so far has reached this.
DEFAULT_MAX_COST = 2.00

# When one of these models declines a request, the API can run it again on another model
# inside the same call. Claude Haiku 5.5 has no such fallback, so it is not listed.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MODELS_WITH_FALLBACK = frozenset({"claude-fable-5-2", "claude-opus-5-5", "claude-sonnet-5-5"})

_ON_THE_TABLE = (
    "The motion before the house: {motion}\n\n"
    "The documents that follow are the record of this sitting so far: the motion, then each "
    "speech in the order it was made."
)


class ReplyLost(Exception):
    """A reply stopped arriving before it was whole, so no speech was recorded."""


def papers_on_the_table(record: dict[str, Any]) -> list[int]:
    """The papers a speaker is handed, in the order they are sent: the motion, then speeches.

    A citation names a document by its position in the request, and a speech that was
    declined or came back empty is not sent. So position and paper number can differ, and
    this list is the map from one to the other.
    """
    delivered = [speech["n"] for speech in record["speeches"] if speech["state"] == "delivered"]
    return [MOTION, *delivered]


def _document(record: dict[str, Any], paper: int) -> dict[str, Any]:
    """One paper as a citable document: custom content, one text block to a sentence.

    With custom content the API cuts nothing itself: a citation can only name whole blocks,
    and its cited text is those blocks joined. So a pin is a run of the record's sentences.
    """
    if paper == MOTION:
        title, context = "The motion", "The motion this sitting debates."
    else:
        speech = record["speeches"][paper - 1]
        title = f"Speech {paper}: {speech['seat']}, {speech['round']}"
        context = (
            f"Speech {paper} of this sitting, made by {speech['seat']} in the "
            f"{speech['round']} round. It is a record of what was said to the house."
        )
    blocks = [{"type": "text", "text": sentence} for sentence in paper_sentences(record, paper)]
    return {
        "type": "document",
        "source": {"type": "content", "content": blocks},
        "title": title,
        "context": context,
        "citations": {"enabled": True},
    }


def build_request(
    record: dict[str, Any], seat: str, round_name: str, personas: dict[str, str]
) -> dict[str, Any]:
    """The request for one speech. It depends on the record and on nothing else.

    The character and the charter are the system prompt, the same bytes on every call to a
    seat, and carry the request's one cache mark. Speeches travel only as words inside
    documents in the user turn: no citation, thinking block or assistant turn is ever sent
    back. The Chair's call comes last, as a system message, or as the last text of the user
    turn when the record's `chair` setting is "user".
    """
    settings = record["settings"]
    table = [
        {"type": "text", "text": _ON_THE_TABLE.format(motion=record["motion"])},
        *(_document(record, paper) for paper in papers_on_the_table(record)),
    ]
    the_call = chair.call(seat, round_name, settings["words"][round_name])
    if settings["chair"] == "system":
        messages = [{"role": "user", "content": table}, {"role": "system", "content": the_call}]
    else:
        messages = [{"role": "user", "content": [*table, {"type": "text", "text": the_call}]}]
    request: dict[str, Any] = {
        "model": settings["model"],
        "max_tokens": settings["max_tokens"],
        "system": [
            {
                "type": "text",
                "text": personas[seat] + charter(seat),
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": messages,
        # Claude decides when to think; effort sets how hard it works.
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": settings["effort"]},
    }
    if settings["fallbacks"] and settings["model"] in MODELS_WITH_FALLBACK:
        request["betas"] = [FALLBACK_BETA]
        request["fallbacks"] = "default"
    return request


def speak(
    client: Any,
    record: dict[str, Any],
    seat: str,
    round_name: str,
    personas: dict[str, str],
    typist: printer.Typist,
) -> dict[str, Any]:
    """Ask for one speech, print it as it arrives, and return it ready for the record.

    The stream's events are read one by one, because the SDK's text_stream hides citations
    and the ends of blocks. Nothing is returned unless the reply arrived whole: a reply that
    stops early raises ReplyLost, and the record is left as it was.
    """
    request = build_request(record, seat, round_name, personas)
    chair.check_placement(request["messages"])
    open_stream = client.beta.messages.stream if "fallbacks" in request else client.messages.stream
    arrived_whole = False
    with open_stream(**request) as stream:
        for event in stream:
            if event.type == "text":
                typist.words(event.text)
            elif event.type == "content_block_stop" and event.content_block.type == "text":
                typist.markers(len(event.content_block.citations or []))
            elif event.type == "message_stop":
                arrived_whole = True
        if not arrived_whole:
            raise ReplyLost(f"the reply for {seat}'s {round_name} stopped before it was whole")
        reply = stream.get_final_message()
    return _speech(reply, record, seat, round_name)


def _speech(reply: Any, record: dict[str, Any], seat: str, round_name: str) -> dict[str, Any]:
    """Turn a whole reply into a speech: its text blocks as segments, its citations as pins."""
    blocks = [block for block in reply.content if block.type == "text"]
    sentences = split("".join(block.text for block in blocks))
    if reply.stop_reason == "refusal":
        state = "declined"
    else:
        state = "delivered" if sentences else "empty"
    delivered = state == "delivered"
    return {
        "n": len(record["speeches"]) + 1,
        "seat": seat,
        "round": round_name,
        "model": reply.model,  # the model named in the reply, which a fallback can change
        "stop_reason": reply.stop_reason,
        "state": state,
        "segments": _segments(blocks, record) if delivered else [],
        "sentences": sentences if delivered else [],
        "usage": _usage(reply.usage),
    }


def _segments(blocks: list[Any], record: dict[str, Any]) -> list[dict[str, Any]]:
    """One segment to a text block, never merged: a pin belongs to the passage it came with."""
    table = papers_on_the_table(record)
    return [
        {
            "text": block.text,
            "pins": [_pin(citation, table, record) for citation in block.citations or []],
        }
        for block in blocks
    ]


def _pin(citation: Any, table: list[int], record: dict[str, Any]) -> dict[str, Any]:
    """Turn one citation into a pin. A citation the chamber cannot read stays unresolved."""
    words = getattr(citation, "cited_text", None) or ""
    document = getattr(citation, "document_index", None)
    first = getattr(citation, "start_block_index", None)
    last = getattr(citation, "end_block_index", None)
    readable = (
        getattr(citation, "type", None) == "content_block_location"
        and all(isinstance(number, int) for number in (document, first, last))
        and 0 <= document < len(table)
    )
    if not readable:
        return unplaced_pin(words)
    paper = table[document]
    return make_pin(paper_sentences(record, paper), paper, first, last, words)


def _usage(usage: Any) -> dict[str, int]:
    """The token counts of a reply, as the record keeps them.

    Thinking tokens are already inside the output count. They are stored apart so that a
    large output can be explained.
    """
    details = getattr(usage, "output_tokens_details", None)
    return {
        "input_tokens": _count(usage, "input_tokens"),
        "output_tokens": _count(usage, "output_tokens"),
        "thinking_tokens": _count(details, "thinking_tokens"),
        "cache_creation_input_tokens": _count(usage, "cache_creation_input_tokens"),
        "cache_read_input_tokens": _count(usage, "cache_read_input_tokens"),
    }


def _count(source: Any, name: str) -> int:
    # Some counts are missing or come back as None when they do not apply.
    return getattr(source, name, None) or 0


def run_sitting(
    client: Any,
    record: dict[str, Any],
    path: str | Path,
    personas: dict[str, str],
    out: TextIO,
    *,
    provenance: str,
    max_cost: float = DEFAULT_MAX_COST,
) -> bool:
    """Hold a sitting until its nine speeches are in the record, or the cost limit stops it.

    `provenance` says what kind of client this is: "live" for Claude, "stand-in" for
    scripted replies. It has no default, and it must match the record, so a record can
    never mix the two. The record is saved to `path` after every speech. Returns True when
    the sitting is finished, and False when the cost limit stopped it before a speech.
    """
    _check_before_a_request(record, personas, provenance)
    printer.opening(record, out)
    for said in record["speeches"]:
        printer.recorded_speech(said, record, out)
    for seat, round_name in chair.order()[len(record["speeches"]) :]:
        spent, _ = sitting_cost(record["speeches"])
        if spent >= max_cost:
            printer.stopped_at_cost(record, spent, max_cost, out)
            return False
        printer.heading(seat, round_name, out)
        typist = printer.Typist(out, waiting_for=seat)
        try:
            speech = speak(client, record, seat, round_name, personas, typist)
        finally:
            typist.close()
        record["speeches"].append(speech)
        save(record, path)
        printer.notes(speech, record, out)
    printer.closing(record, out)
    return True


def _check_before_a_request(
    record: dict[str, Any], personas: dict[str, str], provenance: str
) -> None:
    """Refuse a sitting that would send a bad request or write an untrue record."""
    settings = record["settings"]
    if settings["effort"] not in EFFORTS:
        raise ValueError(f"effort must be one of {', '.join(EFFORTS)}; got {settings['effort']!r}")
    if settings["chair"] not in chair.CHAIRS:
        raise ValueError(
            f"chair must be one of {', '.join(chair.CHAIRS)}; got {settings['chair']!r}"
        )
    if record["provenance"] != provenance:
        raise ValueError(
            f"this record is {record['provenance']}, and a {provenance} sitting cannot add to it"
        )
    if record["seats"] != seat_entries(personas):
        raise ValueError(
            "a character file has changed since this sitting began, so it cannot be carried on"
        )
    held = [(speech["seat"], speech["round"]) for speech in record["speeches"]]
    if held != chair.order()[: len(held)]:
        raise ValueError("the speeches in this record do not follow the Chair's order")
