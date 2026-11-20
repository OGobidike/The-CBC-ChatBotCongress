"""Sentences: the smallest thing a speaker can point at."""

import re

# A sentence ends at a full stop, question mark or exclamation mark (with any closing quotes
# or brackets) when white space or the end of the text follows, or at a blank line.
_END = re.compile(r"""[.!?]+["'”’)\]]*(?=\s|\Z)|\n\s*\n""")


def split(text: str) -> list[str]:
    """Cut a speech into its sentences, in order, each stripped and none empty.

    The same cut is used three times: for the blocks a speech is sent in, for the sentences
    kept in the record, and when a record is checked. So a clumsy cut (after "e.g.", say)
    only makes two small pieces out of one sentence. It can never make a pin wrong, because
    a pin is checked against these same pieces.
    """
    pieces = []
    start = 0
    for end in _END.finditer(text):
        pieces.append(text[start : end.end()])
        start = end.end()
    pieces.append(text[start:])
    return [piece.strip() for piece in pieces if piece.strip()]
