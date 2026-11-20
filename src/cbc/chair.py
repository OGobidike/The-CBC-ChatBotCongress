"""The Chair: who speaks when, what each speaker is asked, and where the asking may sit.

The Chair is plain code. No model chooses the order or writes a call, and a call never
holds a speaker's words, so nothing said in the chamber can pass as the Chair's instruction.
"""

from typing import Any

from cbc.seats import SEATS

ROUNDS = ("opening", "rebuttal", "closing")

# The most words a speech may run to, by round.
WORDS = {"opening": 220, "rebuttal": 180, "closing": 120}

# Where the call travels: as a system message after the papers, or as the last text of the
# user turn for a model that does not take a system message there.
CHAIRS = ("system", "user")

_TASKS = {
    "opening": "State your position on the motion.",
    "rebuttal": (
        "Answer what was actually said. When you state or answer a point another speaker "
        "made, cite the sentences of their speech that you mean."
    ),
    "closing": (
        "Say what you now hold, name any point you grant, and answer the strongest point "
        "still standing against you, citing the sentences where it was made."
    ),
}


def order() -> list[tuple[str, str]]:
    """The nine speeches of a sitting, as (seat, round), in the order they are called.

    The seats move round by one place each round, so nobody always speaks last: Broad opens
    the openings, Cicero the rebuttals and Omnibus the closings.
    """
    return [
        (SEATS[(first + turn) % len(SEATS)], round_name)
        for first, round_name in enumerate(ROUNDS)
        for turn in range(len(SEATS))
    ]


def call(seat: str, round_name: str, words: int) -> str:
    """The Chair's instruction for one speech: who is called, for what, and how long."""
    return (
        f"The Chair calls {seat} for the {round_name}. {_TASKS[round_name]} "
        f"Speak as {seat}, in {words} words at most, in plain text."
    )


def check_placement(messages: list[dict[str, Any]]) -> None:
    """Refuse a list of messages that the API documents as an error, before it is sent.

    The SDK checks none of this and a stand-in server accepts anything, so without this
    check a misplaced system message would first show itself as an error in a live sitting.
    The check is stricter than the API in one place: it also refuses two system messages in
    a row, which the API accepts and the chamber never sends.
    """
    roles = [message["role"] for message in messages]
    if not roles:
        raise ValueError("a request needs at least one message")
    if roles[0] == "system":
        raise ValueError("a system message cannot come first")
    if roles[-1] == "assistant":
        raise ValueError("a request cannot end on an assistant turn")
    for index, role in enumerate(roles):
        if role != "system":
            continue
        if roles[index - 1] != "user":
            raise ValueError("a system message must come directly after a user message")
        if roles[index + 1 : index + 2] == ["user"]:
            raise ValueError("a system message cannot be followed by a user turn")
