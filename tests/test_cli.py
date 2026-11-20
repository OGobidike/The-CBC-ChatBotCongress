import io
import json
from datetime import UTC, datetime

import anthropic
import httpx2
import pytest
from conftest import MOTION, FakeClient, cite, plain_sitting, reply, said

from cbc import printer
from cbc.cli import NO_KEY, NO_MOTION, RESUME_KEEPS_ITS_SETTINGS, TWO_SWITCHES, default_path, main
from cbc.record import load, save, verify

NOW = datetime(2026, 11, 18, 19, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def no_env_file(monkeypatch):
    """Keep a developer's real .env out of the tests."""
    monkeypatch.setattr("cbc.cli.load_dotenv", lambda: None)


def run(*args, client=None):
    """Run the command line. Returns the exit code and everything printed."""
    out = io.StringIO()
    code = main(list(args), client=client, out=out, now=NOW)
    return code, out.getvalue()


def a_sitting_with_pins():
    script = plain_sitting()
    first = "Broad speaks in the opening."
    script[1] = reply("Broad says he speaks.", said(" So he does.", cite(1, 0, 1, first)))
    return script


def refused(status, kind):
    """The error the SDK raises when the API answers a request with this status."""
    request = httpx2.Request("POST", "https://stand-in.invalid/v1/messages")
    return kind(
        "plain words from the API", response=httpx2.Response(status, request=request), body=None
    )


def test_help_lists_the_three_commands(capsys):
    with pytest.raises(SystemExit) as stopped:
        main(["--help"])
    assert stopped.value.code == 0
    shown = capsys.readouterr().out
    for command in ("debate", "replay", "verify"):
        assert command in shown
    # Wherever the read-back is described, what a pin does not prove is said too.
    assert "A pin proves two things only" in " ".join(shown.split())


def test_a_sitting_from_the_ceiling_to_the_record(tmp_path):
    path = tmp_path / "sitting.json"
    code, printed = run(
        "debate", MOTION, "--out", str(path), client=FakeClient(*a_sitting_with_pins())
    )
    assert code == 0
    assert printed.startswith("9 speeches to come, on claude-fable-5-2.\n")
    assert printed.index("--max-cost") < printed.index("BROAD  opening") < printed.index("THE FLOW")
    assert printed.endswith(f"\nThe record is in {path}.\nReplay it with: cbc replay {path}\n")
    record = load(path)
    assert verify(record) == []
    assert len(record["speeches"]) == 9
    assert record["motion"] == MOTION
    assert record["started"] == "2026-11-18T19:00:00Z"


def test_the_ceiling_is_said_in_plain_words_before_the_first_request(tmp_path):
    _, printed = run(
        "debate", MOTION, "--out", str(tmp_path / "s.json"), client=FakeClient(*plain_sitting())
    )
    ceiling = printed[: printed.index("\n\n")]
    # 8,000 output tokens at $40 a million is $0.32.
    assert " ".join(ceiling.split()) == (
        "9 speeches to come, on claude-fable-5-2. "
        "Each may write up to 8,000 tokens, thinking included: at most about $0.3200 a speech, "
        "plus what the model reads. "
        "The sitting stops before a speech once its estimated cost has reached $2.00 "
        "(--max-cost), so it can pass that by one speech at most."
    )
    assert max(len(line) for line in ceiling.splitlines()) <= 78


def test_a_model_with_no_listed_price_is_said_to_have_no_ceiling(tmp_path):
    client = FakeClient(*plain_sitting())
    _, printed = run(
        "debate",
        MOTION,
        "--out",
        str(tmp_path / "s.json"),
        "--model",
        "some-future-model",
        client=client,
    )
    assert " ".join(printed[: printed.index("\n\n")].split()) == (
        "9 speeches to come, on some-future-model. "
        "There is no listed price for some-future-model, so no cost can be estimated and "
        "--max-cost cannot stop this sitting."
    )


def test_a_client_handed_in_never_makes_a_live_record(tmp_path):
    path = tmp_path / "sitting.json"
    run("debate", MOTION, "--out", str(path), client=FakeClient(*plain_sitting()))
    assert load(path)["provenance"] == "stand-in"


def test_only_the_client_the_command_line_makes_for_itself_is_live(tmp_path, monkeypatch):
    # The real client is swapped for the fake at the one place the command line makes it,
    # to check the label that a real sitting gets. The record never leaves tmp_path.
    client = FakeClient(*plain_sitting())
    monkeypatch.setattr("cbc.cli.anthropic.Anthropic", lambda: client)
    path = tmp_path / "sitting.json"
    code, printed = run("debate", MOTION, "--out", str(path))
    assert code == 0
    assert load(path)["provenance"] == "live"
    assert "STAND-IN" not in printed


def test_a_sitting_is_saved_under_sittings_by_day_and_motion(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code, _ = run("debate", "Is a kind story a false one?", client=FakeClient(*plain_sitting()))
    assert code == 0
    saved = tmp_path / "sittings" / "2026-11-18-is-a-kind-story-a-false-one.json"
    assert len(load(saved)["speeches"]) == 9


def test_the_file_name_is_made_of_plain_letters_and_is_never_empty():
    long = "This house would rather be told a hard truth than a kind story, every single time!"
    assert default_path(long, NOW).name == (
        "2026-11-18-this-house-would-rather-be-told-a-hard-truth-than-a-kind-sto.json"
    )
    assert default_path("¿¡…?", NOW).name == "2026-11-18-motion.json"


def test_a_record_already_there_is_never_overwritten(tmp_path):
    path = tmp_path / "sitting.json"
    path.write_text("an earlier sitting", encoding="utf-8")
    client = FakeClient(*plain_sitting())
    code, printed = run("debate", MOTION, "--out", str(path), client=client)
    assert code == 2
    assert printed == (
        f"{path} already exists. Carry a stopped sitting on with --resume, "
        "or name another file with --out.\n"
    )
    assert path.read_text(encoding="utf-8") == "an earlier sitting"
    assert client.calls == []


@pytest.mark.parametrize("args", [["debate"], ["debate", "   "]])
def test_a_sitting_needs_a_motion(args):
    client = FakeClient(*plain_sitting())
    code, printed = run(*args, client=client)
    assert code == 2
    assert printed == NO_MOTION + "\n"
    assert client.calls == []


def test_the_chosen_settings_reach_the_record_and_the_request(tmp_path):
    client = FakeClient(*plain_sitting())
    path = tmp_path / "sitting.json"
    chosen = ["--model", "claude-haiku-5-5", "--effort", "low", "--chair", "user", "--no-fallbacks"]
    run("debate", MOTION, "--out", str(path), *chosen, client=client)
    assert load(path)["settings"] == {
        "model": "claude-haiku-5-5",
        "effort": "low",
        "max_tokens": 8_000,
        "chair": "user",
        "fallbacks": False,
        "words": {"opening": 220, "rebuttal": 180, "closing": 120},
    }
    request = client.calls[0]
    assert request["model"] == "claude-haiku-5-5"
    assert request["output_config"] == {"effort": "low"}
    assert [message["role"] for message in request["messages"]] == ["user"]
    assert request["endpoint"] == "messages"


def test_no_fallbacks_takes_the_plain_path_on_a_model_that_has_them(tmp_path):
    client = FakeClient(*plain_sitting())
    run("debate", MOTION, "--out", str(tmp_path / "s.json"), "--no-fallbacks", client=client)
    assert all(request["endpoint"] == "messages" for request in client.calls)
    assert all("fallbacks" not in request and "betas" not in request for request in client.calls)


def test_a_missing_key_gives_plain_instructions(tmp_path):
    # This is the error the SDK raises, before any request, when it finds no key.
    missing = TypeError("Could not resolve authentication method. Expected one of api_key, ...")
    path = tmp_path / "sitting.json"
    code, printed = run(
        "debate", MOTION, "--out", str(path), client=FakeClient(reply(fails_before=missing))
    )
    assert code == 2
    assert printed.rstrip().endswith(NO_KEY)
    assert not path.exists()


def test_the_real_sdk_with_no_key_gives_the_same_instructions(tmp_path, monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"):
        monkeypatch.delenv(name, raising=False)

    def unauthorized(request):
        # Reached only if the SDK finds a credential somewhere this test did not look.
        error = {"type": "authentication_error", "message": "invalid x-api-key"}
        return httpx2.Response(401, json={"type": "error", "error": error})

    keyless = anthropic.Anthropic(
        base_url="https://stand-in.invalid",
        http_client=httpx2.Client(transport=httpx2.MockTransport(unauthorized)),
        max_retries=0,
    )
    code, printed = run("debate", MOTION, "--out", str(tmp_path / "s.json"), client=keyless)
    assert code == 2
    assert printed.rstrip().endswith(NO_KEY)


def test_any_other_type_error_is_not_swallowed(tmp_path):
    client = FakeClient(reply(fails_before=TypeError("a real bug")))
    with pytest.raises(TypeError, match="a real bug"):
        run("debate", MOTION, "--out", str(tmp_path / "s.json"), client=client)


def test_a_key_claude_does_not_accept_is_explained(tmp_path):
    rejected = refused(401, anthropic.AuthenticationError)
    code, printed = run(
        "debate",
        MOTION,
        "--out",
        str(tmp_path / "s.json"),
        client=FakeClient(reply(fails_before=rejected)),
    )
    assert code == 2
    assert f"Claude did not accept the API key.\n{NO_KEY}" in printed


@pytest.mark.parametrize(
    "failure",
    [
        {"fails_during": httpx2.ReadError("the line went dead")},
        {
            "fails_before": anthropic.APIConnectionError(
                request=httpx2.Request("POST", "https://x.invalid")
            )
        },
        {"cut_off": True},
    ],
)
def test_a_lost_connection_keeps_the_record_so_far_and_says_how_to_carry_on(tmp_path, failure):
    script = plain_sitting()
    script[4] = reply("Half a sen", **failure)
    path = tmp_path / "sitting.json"
    code, printed = run("debate", MOTION, "--out", str(path), client=FakeClient(*script))
    assert code == 1
    assert "The connection to Claude was lost before the speech was whole." in printed
    assert printed.rstrip().endswith(
        f"The record so far (4 of 9 speeches) is kept in {path}.\n"
        f"Carry on with: cbc debate --resume {path}"
    )
    assert len(load(path)["speeches"]) == 4
    assert verify(load(path)) == []


def test_an_error_from_the_api_is_shown_and_the_record_so_far_kept(tmp_path):
    script = plain_sitting()
    script[2] = reply(fails_before=refused(429, anthropic.RateLimitError))
    path = tmp_path / "sitting.json"
    code, printed = run("debate", MOTION, "--out", str(path), client=FakeClient(*script))
    assert code == 1
    assert "Claude replied with an error: plain words from the API" in printed
    assert TWO_SWITCHES not in printed
    assert f"The record so far (2 of 9 speeches) is kept in {path}." in printed


def test_a_request_the_api_refuses_outright_points_at_the_two_switches(tmp_path):
    client = FakeClient(reply(fails_before=refused(400, anthropic.BadRequestError)))
    path = tmp_path / "sitting.json"
    code, printed = run("debate", MOTION, "--out", str(path), client=client)
    assert code == 1
    assert "Claude replied with an error: plain words from the API" in printed
    assert TWO_SWITCHES in printed
    assert printed.rstrip().endswith("No speech was recorded, so no file was written.")
    assert not path.exists()


def test_a_refusal_part_of_the_way_through_does_not_point_at_the_switches(tmp_path):
    # A sitting that is carried on keeps its settings, so the switches would be no help.
    script = plain_sitting()
    script[2] = reply(fails_before=refused(400, anthropic.BadRequestError))
    code, printed = run(
        "debate", MOTION, "--out", str(tmp_path / "s.json"), client=FakeClient(*script)
    )
    assert code == 1
    assert TWO_SWITCHES not in printed
    assert "Carry on with: cbc debate --resume" in printed


def test_stopping_by_hand_keeps_the_record_so_far(tmp_path):
    script = plain_sitting()
    script[3] = reply("Half a sen", fails_during=KeyboardInterrupt())
    path = tmp_path / "sitting.json"
    code, printed = run("debate", MOTION, "--out", str(path), client=FakeClient(*script))
    assert code == 1
    assert "\nStopped.\n" in printed
    assert f"Carry on with: cbc debate --resume {path}" in printed
    assert len(load(path)["speeches"]) == 3


def test_a_sitting_that_stopped_is_carried_on_from_its_record(tmp_path):
    script = a_sitting_with_pins()
    whole = tmp_path / "whole.json"
    run("debate", MOTION, "--out", str(whole), client=FakeClient(*script))

    stopped = tmp_path / "stopped.json"
    cut = [*script[:4], reply(fails_during=httpx2.ReadError("the line went dead"))]
    run("debate", MOTION, "--out", str(stopped), client=FakeClient(*cut))
    code, printed = run("debate", "--resume", str(stopped), client=FakeClient(*script[4:]))
    assert code == 0
    assert printed.startswith("5 speeches to come, on claude-fable-5-2.\n")
    assert load(stopped) == load(whole)


def test_carrying_on_keeps_the_settings_in_the_record(tmp_path):
    script = plain_sitting()
    path = tmp_path / "sitting.json"
    cut = [*script[:4], reply(fails_during=httpx2.ReadError("the line went dead"))]
    run(
        "debate", MOTION, "--out", str(path), "--model", "claude-haiku-5-5", client=FakeClient(*cut)
    )
    client = FakeClient(*script[4:])
    for flags in (
        ["--model", "claude-fable-5-2"],
        ["--effort", "high"],
        ["--chair", "user"],
        ["--no-fallbacks"],
    ):
        code, printed = run("debate", "--resume", str(path), *flags, client=client)
        assert (code, printed) == (2, RESUME_KEEPS_ITS_SETTINGS + "\n")
    code, printed = run(
        "debate", "--resume", str(path), "--out", str(tmp_path / "other.json"), client=client
    )
    assert (code, printed) == (2, RESUME_KEEPS_ITS_SETTINGS + "\n")
    assert client.calls == []
    code, _ = run("debate", "--resume", str(path), client=client)
    assert code == 0
    assert {request["model"] for request in client.calls} == {"claude-haiku-5-5"}


def test_carrying_on_with_another_motion_is_refused(tmp_path):
    script = plain_sitting()
    path = tmp_path / "sitting.json"
    cut = [*script[:4], reply(fails_during=httpx2.ReadError("the line went dead"))]
    run("debate", MOTION, "--out", str(path), client=FakeClient(*cut))
    client = FakeClient(*script[4:])
    code, printed = run("debate", "Another motion entirely.", "--resume", str(path), client=client)
    assert (code, printed) == (2, f"The motion in {path} is: {MOTION}\n")
    code, _ = run("debate", MOTION, "--resume", str(path), client=client)
    assert code == 0


def test_a_record_that_does_not_hold_is_not_carried_on(tmp_path, fixed_record):
    fixed_record["speeches"][1]["segments"][0]["pins"][0]["words"] = "What is school for?"
    path = tmp_path / "forged.json"
    save(fixed_record, path)
    client = FakeClient(*plain_sitting())
    code, printed = run("debate", "--resume", str(path), client=client)
    assert code == 2
    assert printed.startswith(
        f"The record in {path} does not hold:\n  speech 2 (Cicero, opening), pin 1:"
    )
    assert client.calls == []


def test_a_stand_in_cannot_carry_on_a_live_record(tmp_path, fixed_record):
    path = tmp_path / "live.json"
    save(fixed_record | {"provenance": "live"}, path)
    client = FakeClient(*plain_sitting())
    code, printed = run("debate", "--resume", str(path), client=client)
    assert code == 2
    assert printed.rstrip().endswith(
        "This sitting cannot be held: this record is live, and a stand-in sitting cannot add to it."
    )
    assert client.calls == []


def test_the_cost_limit_stops_the_sitting_and_says_how_to_carry_on(tmp_path):
    # Each fake reply costs $0.00256 on Fable 5.2, so three of them pass $0.006.
    path = tmp_path / "sitting.json"
    client = FakeClient(*plain_sitting())
    code, printed = run("debate", MOTION, "--out", str(path), "--max-cost", "0.006", client=client)
    assert code == 0
    assert "reached $0.0060 (--max-cost)" in " ".join(printed.split())
    assert "The sitting stopped before Cicero's rebuttal" in printed
    assert printed.rstrip().endswith(
        f"Carry on with a higher limit: cbc debate --resume {path} --max-cost D"
    )
    assert len(load(path)["speeches"]) == 3
    code, _ = run(
        "debate", "--resume", str(path), "--max-cost", "1", client=FakeClient(*plain_sitting()[3:])
    )
    assert code == 0
    assert len(load(path)["speeches"]) == 9


def test_a_limit_of_nothing_holds_no_sitting_and_writes_no_file(tmp_path):
    path = tmp_path / "sitting.json"
    client = FakeClient(*plain_sitting())
    code, printed = run("debate", MOTION, "--out", str(path), "--max-cost", "0", client=client)
    assert code == 0
    assert printed.rstrip().endswith("No speech was recorded, so no file was written.")
    assert client.calls == [] and not path.exists()


def test_a_path_with_a_space_is_quoted_in_the_line_to_copy(tmp_path):
    path = tmp_path / "my sitting.json"
    _, printed = run("debate", MOTION, "--out", str(path), client=FakeClient(*plain_sitting()))
    assert printed.rstrip().endswith(f"Replay it with: cbc replay '{path}'")


def test_replay_prints_what_the_sitting_printed_with_no_client(tmp_path):
    path = tmp_path / "sitting.json"
    _, live = run("debate", MOTION, "--out", str(path), client=FakeClient(*a_sitting_with_pins()))
    code, again = run("replay", str(path))
    assert code == 0
    assert again in live
    assert again.startswith("STAND-IN RECORD.")
    one_line = " ".join(again.split())
    assert (
        '[1] read back from Broad, opening, sentence 1: "Broad speaks in the opening."' in one_line
    )
    assert "THE FLOW" in again


def test_replay_lists_what_was_left_standing_only_when_asked(tmp_path, fixed_record):
    path = tmp_path / "record.json"
    save(fixed_record, path)
    _, short = run("replay", str(path))
    code, full = run("replay", str(path), "--standing")
    assert code == 0
    listed = '    2. "If it is practice, a child needs it."\n'
    assert listed not in short.split("THE FLOW")[1]
    assert "replay the record with --standing" in " ".join(short.split())
    assert listed in full.split("THE FLOW")[1]


def test_verify_says_a_record_holds_and_counts_its_pins(tmp_path, fixed_record):
    path = tmp_path / "record.json"
    save(fixed_record, path)
    code, printed = run("verify", str(path))
    assert code == 0
    # Five exact pins and one relocated one are checked. The two unresolved ones are not.
    assert printed == (
        "the record holds: 6 pins checked (5 exact, 1 relocated), 2 unresolved, in 4 speeches\n"
        f"{printer.STAND_IN_BANNER}\n"
    )


def test_verify_says_nothing_of_a_stand_in_about_a_live_record(tmp_path, fixed_record):
    path = tmp_path / "record.json"
    save(fixed_record | {"provenance": "live"}, path)
    code, printed = run("verify", str(path))
    assert (code, printed.count("\n")) == (0, 1)
    assert printed.startswith("the record holds: 6 pins checked")


def test_verify_lists_every_fault_and_fails(tmp_path, fixed_record):
    fixed_record["speeches"][1]["segments"][0]["pins"][0]["words"] = "What is school for?"
    fixed_record["speeches"][2]["segments"][0]["pins"][0]["paper"] = 4
    path = tmp_path / "forged.json"
    save(fixed_record, path)
    code, printed = run("verify", str(path))
    assert code == 1
    assert printed == (
        f"The record in {path} does not hold:\n"
        "  speech 2 (Cicero, opening), pin 1: it is stored as exact, "
        "but against the record it is unresolved\n"
        "  speech 3 (Omnibus, opening), pin 1: it points at paper 4, which is not an earlier one\n"
    )


def test_a_record_that_does_not_hold_is_not_replayed(tmp_path, fixed_record):
    fixed_record["speeches"][1]["segments"][0]["pins"][0]["words"] = "What is school for?"
    path = tmp_path / "forged.json"
    save(fixed_record, path)
    code, printed = run("replay", str(path))
    assert code == 1
    assert printed.startswith(f"The record in {path} does not hold:")
    assert "BROAD" not in printed


@pytest.mark.parametrize("command", ["verify", "replay"])
def test_a_file_that_cannot_be_read_gets_a_plain_message(tmp_path, command):
    missing = tmp_path / "nowhere.json"
    code, printed = run(command, str(missing))
    assert code == 1
    assert printed.startswith(f"Could not read a record from {missing}:")

    not_json = tmp_path / "notes.json"
    not_json.write_text("these are not the papers", encoding="utf-8")
    code, printed = run(command, str(not_json))
    assert code == 1
    assert printed.startswith(f"Could not read a record from {not_json}:")

    not_a_record = tmp_path / "list.json"
    not_a_record.write_text(json.dumps(["a", "list"]), encoding="utf-8")
    code, printed = run(command, str(not_a_record))
    assert code == 1
    assert "this is not shaped like a cbc-record/1 record" in printed
