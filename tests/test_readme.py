"""The README shows a passage from a real sitting. This checks it against the record."""

import io
import re
from pathlib import Path

from cbc import printer
from cbc.record import load

ROOT = Path(__file__).resolve().parent.parent

# In the README: a comment naming the record, then a fenced block holding the passage.
EXCERPT = re.compile(r"<!-- excerpt: (\S+) -->\n+```\n(.*?)\n```", re.DOTALL)


def test_the_passage_in_the_readme_is_what_its_record_replays():
    found = EXCERPT.findall((ROOT / "README.md").read_text(encoding="utf-8"))
    assert found, "the README should show a passage from a recorded sitting"
    for path, passage in found:
        out = io.StringIO()
        printer.replay(load(ROOT / path), out)
        assert passage in out.getvalue(), f"the passage is not in a replay of {path}"
