"""What may be committed under sittings/: real sittings only, and only ones that hold."""

import json
from pathlib import Path

from conftest import blank_record

from cbc.record import save, verify

SITTINGS = Path(__file__).parent.parent / "sittings"


def stand_ins(folder):
    """Every record under a folder whose speeches are a test script."""
    return [
        path
        for path in sorted(folder.rglob("*.json"))
        if json.loads(path.read_text(encoding="utf-8")).get("provenance") != "live"
    ]


def test_a_stand_in_record_under_a_folder_is_found(tmp_path, personas):
    live = blank_record(personas) | {"provenance": "live"}
    save(live, tmp_path / "a-real-sitting.json")
    assert stand_ins(tmp_path) == []
    save(blank_record(personas), tmp_path / "deeper" / "a-rehearsal.json")
    assert stand_ins(tmp_path) == [tmp_path / "deeper" / "a-rehearsal.json"]


def test_no_stand_in_record_is_kept_among_the_sittings():
    # A scripted record in sittings/ could be taken for a sitting that was really held.
    assert stand_ins(SITTINGS) == []


def test_every_sitting_kept_in_the_repository_holds():
    for path in sorted(SITTINGS.rglob("*.json")):
        assert verify(json.loads(path.read_text(encoding="utf-8"))) == [], path
