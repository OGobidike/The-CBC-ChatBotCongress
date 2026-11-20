"""The flow of a sitting: which sentences another speaker read back, and which were left standing.

Everything here is counted from the pins in the record. No model is asked, and nothing is
stored, so the flow cannot drift from the record it describes.

It counts pointing and nothing more. A sentence that was read back was pointed at by another
speaker; a sentence left standing was not read back by anyone. Neither says who argued
better, or whether a point was met without being pointed at.
"""

from typing import Any

from cbc.pricing import sitting_cost
from cbc.record import MOTION, count_checks, pins_of

# A pin over every sentence of a speech this long is a pointer at the speech as a whole,
# not a reading back of any one sentence, so it is counted apart.
WHOLE_SPEECH = 4

# Almost nobody speaks after a closing, so its sentences are not listed as left standing.
LAST_ROUND = "closing"


def flow(record: dict[str, Any]) -> dict[str, Any]:
    """The flow sheet's numbers for a record.

    A pin counts as a reading back by another speaker only when it checked (exact or
    relocated), points at a speech (not the motion), and that speech was made by somebody
    else. Whole-speech pins are counted apart and mark no sentence.
    """
    speeches = record["speeches"]
    readers: dict[int, dict[int, set[str]]] = {speech["n"]: {} for speech in speeches}
    whole_speech_pins = 0
    speeches_reading_back = 0
    for speech in speeches:
        read_back_another = False
        for pin in pins_of(speech):
            if pin["check"] == "unresolved" or pin["paper"] == MOTION:
                continue
            target = speeches[pin["paper"] - 1]
            if _covers_whole_speech(pin, target):
                whole_speech_pins += 1
            elif target["seat"] != speech["seat"]:
                read_back_another = True
                for sentence in range(pin["first"], pin["last"]):
                    readers[target["n"]].setdefault(sentence, set()).add(speech["seat"])
        speeches_reading_back += read_back_another
    cost, unpriced = sitting_cost(speeches)
    return {
        "speeches": [_row(speech, readers[speech["n"]]) for speech in speeches],
        "checks": count_checks(record),
        "whole_speech_pins": whole_speech_pins,
        "speeches_reading_back": speeches_reading_back,
        "delivered": sum(speech["state"] == "delivered" for speech in speeches),
        "cost": cost,
        "unpriced": unpriced,
    }


def _covers_whole_speech(pin: dict[str, Any], target: dict[str, Any]) -> bool:
    length = len(target["sentences"])
    return length >= WHOLE_SPEECH and (pin["first"], pin["last"]) == (0, length)


def _row(speech: dict[str, Any], readers: dict[int, set[str]]) -> dict[str, Any]:
    """One speech on the sheet: how much of it was read back, by whom, and what was not."""
    by: dict[str, int] = {}
    for seats in readers.values():
        for seat in seats:
            by[seat] = by.get(seat, 0) + 1
    listed = speech["state"] == "delivered" and speech["round"] != LAST_ROUND
    return {
        "n": speech["n"],
        "seat": speech["seat"],
        "round": speech["round"],
        "state": speech["state"],
        "sentences": len(speech["sentences"]),
        "read_back": sorted(readers),
        # With three seats, two readers means both of the other speakers.
        "by_both": sorted(index for index, seats in readers.items() if len(seats) >= 2),
        "by": dict(sorted(by.items())),
        "left_standing": [
            index for index in range(len(speech["sentences"])) if listed and index not in readers
        ],
    }
