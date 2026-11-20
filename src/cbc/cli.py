"""The command line: hold a sitting, replay a recorded one, or check a record."""

import argparse
import json
import re
import shlex
import sys
import textwrap
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

import anthropic
import httpx2
from dotenv import load_dotenv

from cbc import chair, printer
from cbc.chamber import (
    DEFAULT_EFFORT,
    DEFAULT_MAX_COST,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    EFFORTS,
    ReplyLost,
    run_sitting,
)
from cbc.pricing import dollars, output_ceiling
from cbc.record import WHAT_A_PIN_PROVES, count_checks, load, new_record, verify
from cbc.seats import load_personas

NO_KEY = (
    "The CBC needs a Claude API key to hold a sitting.\n"
    "Copy .env.example to .env and paste your key into it, or set ANTHROPIC_API_KEY.\n"
    "Keys are made at https://platform.claude.com/settings/keys"
)
NO_MOTION = 'Give the motion in quotes: cbc debate "This house would ..."'
RESUME_KEEPS_ITS_SETTINGS = (
    "--resume carries on with the motion and settings in the record. "
    "Leave out --model, --effort, --chair, --no-fallbacks and --out."
)
# Shown when the API refuses a sitting's first request outright. These are the two parts of
# a request's shape that can be changed from the command line.
TWO_SWITCHES = (
    "Two switches change the shape of the request: --chair user sends the Chair's call in "
    "the user turn, and --no-fallbacks leaves out the server-side fallback."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cbc",
        description=(
            "The CBC, a Chatbot Congress: Broad, Cicero and Omnibus debate a motion on Claude. "
            "Each speaker is handed every earlier speech, and the sentences a speaker points "
            "at are read back from the record under the speech."
        ),
        epilog=WHAT_A_PIN_PROVES,
    )
    commands = parser.add_subparsers(dest="command", required=True)

    debate = commands.add_parser(
        "debate",
        help="hold a sitting on a motion, and record it",
        description="Hold a sitting on a motion: nine speeches, streamed here and recorded.",
    )
    debate.add_argument("motion", nargs="?", help="the motion to debate, in quotes")
    debate.add_argument(
        "--model", help=f"the Claude model that plays every seat (default: {DEFAULT_MODEL})"
    )
    debate.add_argument(
        "--effort",
        choices=EFFORTS,
        help=f"how hard the model works on each speech (default: {DEFAULT_EFFORT})",
    )
    debate.add_argument(
        "--out",
        metavar="PATH",
        help="where the record is saved (default: sittings/<UTC date>-<the motion>.json)",
    )
    debate.add_argument(
        "--resume",
        metavar="PATH",
        help="carry on a sitting that stopped, from its record, with the settings in it",
    )
    debate.add_argument(
        "--max-cost",
        type=float,
        default=DEFAULT_MAX_COST,
        metavar="D",
        help=(
            "stop before a speech once the sitting's estimated cost has reached this many "
            "dollars (default: %(default).2f)"
        ),
    )
    debate.add_argument(
        "--chair",
        choices=chair.CHAIRS,
        help=(
            "how the Chair's call is sent: as a system message after the papers, or as the "
            "last text of the user turn (default: system)"
        ),
    )
    debate.add_argument(
        "--no-fallbacks",
        action="store_true",
        help="do not ask the API to run a declined request again on another model",
    )

    replay = commands.add_parser(
        "replay",
        help="print a recorded sitting and its flow sheet",
        description="Print a recorded sitting and its flow sheet. No key, no network.",
    )
    replay.add_argument("path", help="the record file")
    replay.add_argument(
        "--standing",
        action="store_true",
        help="list in full every sentence of the openings and rebuttals that nobody else read back",
    )

    check = commands.add_parser(
        "verify",
        help="check every pin of a record against the record itself",
        description=(
            "Check a record: its sentences, its numbering, and every pin against the paper "
            f"it points at. No key, no network. {WHAT_A_PIN_PROVES}"
        ),
    )
    check.add_argument("path", help="the record file")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    client: Any = None,
    out: TextIO | None = None,
    now: datetime | None = None,
) -> int:
    """Run one command. Returns the exit code.

    0: done, or a sitting stopped at its cost limit. 1: a record that does not hold, or a
    sitting cut off by an error or stopped by hand. 2: no usable key, or a command that
    cannot be run as given.

    A client handed in here is a stand-in, and the record it makes is marked as one. Only a
    client this function makes for itself, for the real API, makes a live record.
    """
    out = sys.stdout if out is None else out
    args = build_parser().parse_args(argv)
    if args.command == "replay":
        return _replay(args.path, out, standing=args.standing)
    if args.command == "verify":
        return _verify(args.path, out)
    return _debate(args, client, out, now)


def _debate(args: argparse.Namespace, client: Any, out: TextIO, now: datetime | None) -> int:
    load_dotenv()
    personas = load_personas()
    # Only a client made here, for the real API, is live. One handed in is a stand-in.
    provenance = "live" if client is None else "stand-in"
    try:
        if args.resume:
            record, path = _record_to_resume(args), Path(args.resume)
        else:
            record, path = _fresh_record(args, personas, provenance, now)
    except ValueError as error:
        print(error, file=out)
        return 2
    if client is None:
        client = anthropic.Anthropic()

    print(ceiling(record, args.max_cost), file=out)
    print(file=out)
    try:
        finished = run_sitting(
            client, record, path, personas, out, provenance=provenance, max_cost=args.max_cost
        )
    except ValueError as error:
        print(f"This sitting cannot be held: {error}.", file=out)
        return 2
    except TypeError as error:
        # The SDK raises this before any request when it finds no key at all.
        if "authentication" not in str(error):
            raise
        print(f"\n{NO_KEY}", file=out)
        return 2
    except anthropic.AuthenticationError:
        print(f"\nClaude did not accept the API key.\n{NO_KEY}", file=out)
        return 2
    except (anthropic.APIConnectionError, httpx2.TransportError, ReplyLost):
        print("\nThe connection to Claude was lost before the speech was whole.", file=out)
        return _cut_off(record, path, out)
    except anthropic.APIStatusError as error:
        # Rate limits, a reached spend limit, an unknown model name, a server fault.
        print(f"\nClaude replied with an error: {error.message}", file=out)
        if isinstance(error, anthropic.BadRequestError) and not record["speeches"]:
            print(TWO_SWITCHES, file=out)
        return _cut_off(record, path, out)
    except KeyboardInterrupt:
        print("\nStopped.", file=out)
        return _cut_off(record, path, out)

    where = shlex.quote(str(path))
    if finished:
        print(f"\nThe record is in {path}.\nReplay it with: cbc replay {where}", file=out)
    elif record["speeches"]:
        print(f"Carry on with a higher limit: cbc debate --resume {where} --max-cost D", file=out)
    else:
        print("No speech was recorded, so no file was written.", file=out)
    return 0


def _fresh_record(
    args: argparse.Namespace, personas: dict[str, str], provenance: str, now: datetime | None
) -> tuple[dict[str, Any], Path]:
    """A new record and the path it will be saved to. Raises ValueError with plain words."""
    if not (args.motion or "").strip():
        raise ValueError(NO_MOTION)
    started = datetime.now(UTC) if now is None else now
    path = Path(args.out) if args.out else default_path(args.motion, started)
    if path.exists():
        raise ValueError(
            f"{path} already exists. Carry a stopped sitting on with --resume, "
            "or name another file with --out."
        )
    record = new_record(
        args.motion,
        personas,
        provenance=provenance,
        started=started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        model=args.model or DEFAULT_MODEL,
        effort=args.effort or DEFAULT_EFFORT,
        max_tokens=DEFAULT_MAX_TOKENS,
        chair=args.chair or "system",
        fallbacks=not args.no_fallbacks,
    )
    return record, path


def default_path(motion: str, started: datetime) -> Path:
    """Where a new sitting is saved unless --out says otherwise: named by day and motion."""
    slug = re.sub(r"[^a-z0-9]+", "-", motion.lower()).strip("-")[:60].rstrip("-")
    return Path("sittings") / f"{started:%Y-%m-%d}-{slug or 'motion'}.json"


def _record_to_resume(args: argparse.Namespace) -> dict[str, Any]:
    """The record a stopped sitting left, checked. Raises ValueError with plain words."""
    if args.model or args.effort or args.chair or args.no_fallbacks or args.out:
        raise ValueError(RESUME_KEEPS_ITS_SETTINGS)
    record = _load_checked(args.resume)
    if args.motion and args.motion != record["motion"]:
        raise ValueError(f"The motion in {args.resume} is: {record['motion']}")
    return record


def _load_checked(path: str) -> dict[str, Any]:
    """Read a record and check it. Raises ValueError, in plain words, if it does not hold."""
    try:
        record = load(path)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read a record from {path}: {error}") from error
    faults = verify(record)
    if faults:
        listed = "\n".join(f"  {fault}" for fault in faults)
        raise ValueError(f"The record in {path} does not hold:\n{listed}")
    return record


def ceiling(record: dict[str, Any], max_cost: float) -> str:
    """What a sitting can cost, in plain words, printed before its first request."""
    settings = record["settings"]
    to_come = len(chair.order()) - len(record["speeches"])
    lines = [f"{printer.counted(to_come, 'speech', 'speeches')} to come, on {settings['model']}."]
    most = output_ceiling(settings["model"], settings["max_tokens"])
    if most is None:
        lines.append(
            f"There is no listed price for {settings['model']}, so no cost can be estimated "
            "and --max-cost cannot stop this sitting."
        )
    else:
        lines.append(
            f"Each may write up to {settings['max_tokens']:,} tokens, thinking included: at "
            f"most about ${most:.4f} a speech, plus what the model reads."
        )
        lines.append(
            f"The sitting stops before a speech once its estimated cost has reached "
            f"{dollars(max_cost)} (--max-cost), so it can pass that by one speech at most."
        )
    return "\n".join(textwrap.fill(line, printer.WIDTH) for line in lines)


def _cut_off(record: dict[str, Any], path: Path, out: TextIO) -> int:
    """Say what was kept of a sitting that an error cut off, and how to carry it on."""
    held = len(record["speeches"])
    if held:
        print(
            f"The record so far ({held} of {len(chair.order())} speeches) is kept in {path}.\n"
            f"Carry on with: cbc debate --resume {shlex.quote(str(path))}",
            file=out,
        )
    else:
        print("No speech was recorded, so no file was written.", file=out)
    return 1


def _replay(path: str, out: TextIO, *, standing: bool = False) -> int:
    try:
        record = _load_checked(path)
    except ValueError as error:
        print(error, file=out)
        return 1
    printer.replay(record, out, standing=standing)
    return 0


def _verify(path: str, out: TextIO) -> int:
    try:
        record = _load_checked(path)
    except ValueError as error:
        print(error, file=out)
        return 1
    checks = count_checks(record)
    checked = printer.counted(checks["exact"] + checks["relocated"], "pin")
    speeches = printer.counted(len(record["speeches"]), "speech", "speeches")
    print(
        f"the record holds: {checked} checked ({checks['exact']} exact, "
        f"{checks['relocated']} relocated), {checks['unresolved']} unresolved, in {speeches}",
        file=out,
    )
    if record["provenance"] == "stand-in":
        print(printer.STAND_IN_BANNER, file=out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
