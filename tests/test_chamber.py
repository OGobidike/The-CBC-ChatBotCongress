import copy
import io

import pytest
from conftest import MOTION, FakeClient, blank_record, cite, plain_sitting, reply, said, spent

from cbc import chamber
from cbc.chair import call, order
from cbc.chamber import (
    FALLBACK_BETA,
    ReplyLost,
    build_request,
    papers_on_the_table,
    run_sitting,
    speak,
)
from cbc.printer import Typist
from cbc.record import load, verify
from cbc.seats import charter

FIRST = "Broad speaks in the opening."  # the first sentence of speech 1 in plain_sitting
SECOND = "This is speech 1 of the sitting."


def hear(client, record, personas):
    """Ask for the next speech of the order and add it to the record, printing nowhere."""
    seat, round_name = order()[len(record["speeches"])]
    speech = speak(client, record, seat, round_name, personas, Typist(io.StringIO()))
    record["speeches"].append(speech)
    return speech


def sit(client, record, path, personas, **settings):
    """Hold a sitting. Returns whether it finished, and everything that was printed."""
    out = io.StringIO()
    finished = run_sitting(client, record, path, personas, out, provenance="stand-in", **settings)
    return finished, out.getvalue()


def after_one_speech(personas):
    record = blank_record(personas)
    hear(FakeClient(plain_sitting()[0]), record, personas)
    return record


def documents(request):
    return [block for block in request["messages"][0]["content"] if block["type"] == "document"]


def test_the_request_depends_on_the_record_and_nothing_else(personas):
    record = after_one_speech(personas)
    before = copy.deepcopy(record)
    first = build_request(record, "Cicero", "opening", personas)
    assert record == before
    assert build_request(copy.deepcopy(record), "Cicero", "opening", personas) == first


def test_the_system_prompt_is_the_character_then_the_charter_with_the_one_cache_mark(personas):
    request = build_request(after_one_speech(personas), "Cicero", "opening", personas)
    assert request["system"] == [
        {
            "type": "text",
            "text": personas["Cicero"] + charter("Cicero"),
            "cache_control": {"type": "ephemeral"},
        }
    ]
    assert "cache_control" not in request
    assert "cache_control" not in str(request["messages"])


def test_the_system_prompt_is_the_same_for_every_call_to_a_seat(personas):
    record = blank_record(personas)
    opening = build_request(record, "Cicero", "opening", personas)["system"]
    client = FakeClient(*plain_sitting())
    for _ in range(3):
        hear(client, record, personas)
    assert build_request(record, "Cicero", "rebuttal", personas)["system"] == opening


def test_the_papers_are_the_motion_then_every_speech_so_far(personas):
    record = blank_record(personas)
    client = FakeClient(*plain_sitting())
    for _ in range(4):
        hear(client, record, personas)
    # Omnibus speaks fifth, and is handed his own opening with the others.
    request = build_request(record, "Omnibus", "rebuttal", personas)
    assert [paper["title"] for paper in documents(request)] == [
        "The motion",
        "Speech 1: Broad, opening",
        "Speech 2: Cicero, opening",
        "Speech 3: Omnibus, opening",
        "Speech 4: Cicero, rebuttal",
    ]
    assert request["messages"][0]["content"][0] == {
        "type": "text",
        "text": (
            f"The motion before the house: {MOTION}\n\nThe documents that follow are the "
            "record of this sitting so far: the motion, then each speech in the order it "
            "was made."
        ),
    }


def test_each_paper_is_one_block_to_a_sentence_with_citations_on(personas):
    request = build_request(after_one_speech(personas), "Cicero", "opening", personas)
    motion, first = documents(request)
    assert motion == {
        "type": "document",
        "source": {"type": "content", "content": [{"type": "text", "text": MOTION}]},
        "title": "The motion",
        "context": "The motion this sitting debates.",
        "citations": {"enabled": True},
    }
    assert first["source"]["content"] == [
        {"type": "text", "text": FIRST},
        {"type": "text", "text": SECOND},
    ]
    assert first["citations"] == {"enabled": True}
    assert first["context"] == (
        "Speech 1 of this sitting, made by Broad in the opening round. "
        "It is a record of what was said to the house."
    )


def test_the_chairs_call_comes_last_as_a_system_message(personas):
    request = build_request(blank_record(personas), "Broad", "opening", personas)
    assert [message["role"] for message in request["messages"]] == ["user", "system"]
    assert request["messages"][1]["content"] == call("Broad", "opening", 220)


def test_the_chair_can_speak_in_the_user_turn_instead(personas):
    record = blank_record(personas, chair="user")
    request = build_request(record, "Broad", "opening", personas)
    assert [message["role"] for message in request["messages"]] == ["user"]
    assert request["messages"][0]["content"][-1] == {
        "type": "text",
        "text": call("Broad", "opening", 220),
    }


def test_the_word_limit_of_each_round_comes_from_the_record(personas):
    record = blank_record(personas)
    record["settings"]["words"]["opening"] = 90
    request = build_request(record, "Broad", "opening", personas)
    assert "in 90 words at most" in request["messages"][1]["content"]


def test_thinking_is_adaptive_and_no_removed_setting_is_sent(personas):
    request = build_request(blank_record(personas, effort="high"), "Broad", "opening", personas)
    assert request["thinking"] == {"type": "adaptive"}
    assert request["output_config"] == {"effort": "high"}
    assert request["max_tokens"] == 8_000
    assert {"temperature", "top_p", "top_k"}.isdisjoint(request)


def test_models_with_a_fallback_ask_for_it(personas):
    client = FakeClient(*plain_sitting())
    hear(client, blank_record(personas), personas)
    request = client.calls[0]
    assert request["endpoint"] == "beta.messages"
    assert request["betas"] == [FALLBACK_BETA]
    assert request["fallbacks"] == "default"


def test_haiku_is_sent_without_a_fallback(personas):
    client = FakeClient(*plain_sitting())
    hear(client, blank_record(personas, model="claude-haiku-5-5"), personas)
    request = client.calls[0]
    assert request["endpoint"] == "messages"
    assert "fallbacks" not in request
    assert "betas" not in request


def test_fallbacks_can_be_switched_off(personas):
    client = FakeClient(*plain_sitting())
    hear(client, blank_record(personas, fallbacks=False), personas)
    request = client.calls[0]
    assert request["endpoint"] == "messages"
    assert "fallbacks" not in request
    assert "betas" not in request


def test_a_citation_becomes_a_pin_on_the_sentences_it_names(personas):
    record = after_one_speech(personas)
    client = FakeClient(reply("Broad says he speaks.", said(" So he does.", cite(1, 0, 1, FIRST))))
    speech = hear(client, record, personas)
    assert speech["segments"] == [
        {"text": "Broad says he speaks.", "pins": []},
        {
            "text": " So he does.",
            "pins": [{"paper": 1, "first": 0, "last": 1, "words": FIRST, "check": "exact"}],
        },
    ]
    assert speech["sentences"] == ["Broad says he speaks.", "So he does."]
    assert verify(record) == []


def test_a_speech_can_pin_the_motion(personas):
    record = blank_record(personas)
    speech = hear(
        FakeClient(reply(said("The motion is plain.", cite(0, 0, 1, MOTION)))), record, personas
    )
    assert speech["segments"][0]["pins"] == [
        {"paper": 0, "first": 0, "last": 1, "words": MOTION, "check": "exact"}
    ]


def test_two_pins_on_one_passage_are_both_kept_in_order(personas):
    record = after_one_speech(personas)
    passage = said("Broad said two things.", cite(1, 1, 2, SECOND), cite(1, 0, 1, FIRST))
    speech = hear(FakeClient(reply(passage)), record, personas)
    assert [(pin["first"], pin["check"]) for pin in speech["segments"][0]["pins"]] == [
        (1, "exact"),
        (0, "exact"),
    ]


def test_a_pin_can_run_over_several_sentences(personas):
    record = after_one_speech(personas)
    speech = hear(
        FakeClient(reply(said("All of it.", cite(1, 0, 2, FIRST + SECOND)))), record, personas
    )
    assert speech["segments"][0]["pins"] == [
        {"paper": 1, "first": 0, "last": 2, "words": FIRST + SECOND, "check": "exact"}
    ]


def test_a_speech_with_no_citation_has_no_pins_and_nothing_invented(personas):
    record = after_one_speech(personas)
    speech = hear(FakeClient(reply("I point at nothing. I only speak.")), record, personas)
    assert speech["state"] == "delivered"
    assert speech["segments"] == [{"text": "I point at nothing. I only speak.", "pins": []}]
    assert verify(record) == []


def test_text_blocks_are_never_merged(personas):
    record = blank_record(personas)
    speech = hear(FakeClient(reply("One. ", "Two. ", "Three.")), record, personas)
    assert [segment["text"] for segment in speech["segments"]] == ["One. ", "Two. ", "Three."]
    assert speech["sentences"] == ["One.", "Two.", "Three."]


def test_a_citation_at_the_wrong_place_is_relocated(personas):
    record = after_one_speech(personas)
    speech = hear(FakeClient(reply(said("He counts.", cite(1, 0, 1, SECOND)))), record, personas)
    assert speech["segments"][0]["pins"] == [
        {
            "paper": 1,
            "first": 1,
            "last": 2,
            "words": SECOND,
            "check": "relocated",
            "stated_first": 0,
            "stated_last": 1,
        }
    ]
    assert verify(record) == []


@pytest.mark.parametrize(
    "citation",
    [
        cite(1, 0, 1, FIRST, kind="char_location"),  # a kind the chamber does not read
        cite(1, 0, 1, FIRST, kind="web_search_result_location"),
        cite(7, 0, 1, FIRST),  # a document that was never sent
        cite(-1, 0, 1, FIRST),
        cite(None, 0, 1, FIRST),
        cite(1, None, None, FIRST),
    ],
)
def test_a_citation_the_chamber_cannot_read_is_unresolved_and_never_a_crash(personas, citation):
    record = after_one_speech(personas)
    speech = hear(FakeClient(reply(said("He spoke.", citation))), record, personas)
    assert speech["segments"][0]["pins"] == [
        {"paper": None, "first": None, "last": None, "words": FIRST, "check": "unresolved"}
    ]
    assert verify(record) == []


def test_words_the_paper_never_said_are_unresolved_and_kept(personas):
    record = after_one_speech(personas)
    forged = cite(1, 0, 1, "Broad never said this.")
    speech = hear(FakeClient(reply(said("He spoke.", forged))), record, personas)
    assert speech["segments"][0]["pins"] == [
        {
            "paper": 1,
            "first": 0,
            "last": 1,
            "words": "Broad never said this.",
            "check": "unresolved",
        }
    ]
    assert verify(record) == []


def test_a_declined_speech_keeps_its_number_and_holds_no_words(personas):
    record = after_one_speech(personas)
    speech = hear(FakeClient(reply("Half a sen", stop_reason="refusal")), record, personas)
    assert (speech["n"], speech["seat"], speech["state"]) == (2, "Cicero", "declined")
    assert speech["stop_reason"] == "refusal"
    assert speech["segments"] == [] and speech["sentences"] == []
    assert verify(record) == []


def test_a_declined_speech_is_kept_out_of_later_requests_and_the_map_stays_right(personas):
    record = after_one_speech(personas)
    third = "Omnibus speaks in the opening."
    client = FakeClient(
        reply(stop_reason="refusal"),
        plain_sitting()[2],
        # Document 2 of this request is speech 3, because speech 2 was never sent.
        reply(said("Omnibus spoke.", cite(2, 0, 1, third))),
    )
    hear(client, record, personas)
    hear(client, record, personas)
    assert papers_on_the_table(record) == [0, 1, 3]
    speech = hear(client, record, personas)
    assert [paper["title"] for paper in documents(client.calls[2])] == [
        "The motion",
        "Speech 1: Broad, opening",
        "Speech 3: Omnibus, opening",
    ]
    assert speech["n"] == 4
    assert speech["segments"][0]["pins"] == [
        {"paper": 3, "first": 0, "last": 1, "words": third, "check": "exact"}
    ]
    assert verify(record) == []


def test_a_reply_that_ran_out_while_thinking_is_an_empty_speech(personas):
    record = after_one_speech(personas)
    speech = hear(FakeClient(reply(stop_reason="max_tokens")), record, personas)
    assert (speech["state"], speech["stop_reason"]) == ("empty", "max_tokens")
    assert speech["segments"] == [] and speech["sentences"] == []
    assert papers_on_the_table(record) == [0, 1]
    assert verify(record) == []


def test_a_reply_of_white_space_alone_is_an_empty_speech(personas):
    record = blank_record(personas)
    speech = hear(FakeClient(reply(" \n\n ")), record, personas)
    assert speech["state"] == "empty"
    assert speech["segments"] == []


def test_a_speech_cut_short_stays_delivered(personas):
    record = blank_record(personas)
    speech = hear(FakeClient(reply("Once upon a", stop_reason="max_tokens")), record, personas)
    assert (speech["state"], speech["stop_reason"]) == ("delivered", "max_tokens")
    assert speech["sentences"] == ["Once upon a"]


def test_the_record_names_the_model_that_replied(personas):
    record = blank_record(personas)
    speech = hear(FakeClient(reply("A speech.", model="claude-opus-5")), record, personas)
    assert record["settings"]["model"] == "claude-fable-5-2"
    assert speech["model"] == "claude-opus-5"


def test_token_counts_are_kept_with_thinking_apart(personas):
    record = blank_record(personas)
    usage = spent(input_tokens=30, output_tokens=900, cache_write=2_400, cache_read=0, thinking=640)
    speech = hear(FakeClient(reply("A speech.", usage=usage)), record, personas)
    assert speech["usage"] == {
        "input_tokens": 30,
        "output_tokens": 900,
        "thinking_tokens": 640,
        "cache_creation_input_tokens": 2_400,
        "cache_read_input_tokens": 0,
    }


def test_thinking_tokens_are_zero_when_the_reply_does_not_break_them_out(personas):
    record = blank_record(personas)
    usage = spent()
    usage.cache_read_input_tokens = None  # some counts come back as None
    speech = hear(FakeClient(reply("A speech.", usage=usage)), record, personas)
    assert speech["usage"]["thinking_tokens"] == 0
    assert speech["usage"]["cache_read_input_tokens"] == 0


def test_a_reply_that_stops_early_is_lost_not_recorded(personas):
    record = after_one_speech(personas)
    with pytest.raises(ReplyLost, match="Cicero's opening stopped before it was whole"):
        hear(FakeClient(reply("Half a sen", cut_off=True)), record, personas)
    assert len(record["speeches"]) == 1


def test_the_placement_check_runs_before_every_request(personas, monkeypatch):
    def refuse(messages):
        raise ValueError("badly placed")

    monkeypatch.setattr(chamber.chair, "check_placement", refuse)
    client = FakeClient(*plain_sitting())
    with pytest.raises(ValueError, match="badly placed"):
        hear(client, blank_record(personas), personas)
    assert client.calls == []


def test_a_whole_sitting_is_nine_speeches_in_the_chairs_order(personas, tmp_path):
    client = FakeClient(*plain_sitting())
    record = blank_record(personas)
    finished, _ = sit(client, record, tmp_path / "record.json", personas)
    assert finished
    assert [(speech["seat"], speech["round"]) for speech in record["speeches"]] == order()
    assert [speech["n"] for speech in record["speeches"]] == list(range(1, 10))
    assert load(tmp_path / "record.json") == record
    assert verify(record) == []
    # Each request holds one more paper than the last: the motion, then every speech so far.
    assert [len(documents(request)) for request in client.calls] == list(range(1, 10))


def test_a_failed_request_leaves_the_record_as_it_was(personas, tmp_path):
    script = plain_sitting()
    script[4] = reply("Half a sen", fails_during=ConnectionError("the line went dead"))
    path = tmp_path / "record.json"
    record = blank_record(personas)
    with pytest.raises(ConnectionError):
        sit(FakeClient(*script), record, path, personas)
    assert len(record["speeches"]) == 4
    assert load(path) == record


def test_nothing_is_written_until_the_first_speech_is_whole(personas, tmp_path):
    path = tmp_path / "record.json"
    client = FakeClient(reply(fails_before=ConnectionError("no line at all")))
    with pytest.raises(ConnectionError):
        sit(client, blank_record(personas), path, personas)
    assert not path.exists()


def test_a_sitting_stopped_after_speech_four_and_resumed_equals_one_that_was_not(
    personas, tmp_path
):
    whole_client = FakeClient(*plain_sitting())
    whole = blank_record(personas)
    sit(whole_client, whole, tmp_path / "whole.json", personas)

    script = plain_sitting()
    stopped_client = FakeClient(
        *script[:4], reply(fails_during=ConnectionError("the line went dead"))
    )
    path = tmp_path / "stopped.json"
    with pytest.raises(ConnectionError):
        sit(stopped_client, blank_record(personas), path, personas)
    assert len(load(path)["speeches"]) == 4

    resumed_client = FakeClient(*script[4:])
    resumed = load(path)
    finished, _ = sit(resumed_client, resumed, path, personas)
    assert finished
    assert resumed == whole
    assert load(path) == whole
    # The five requests after the stop are the very ones the unbroken sitting sent.
    assert resumed_client.calls == whole_client.calls[4:]


def test_the_sitting_stops_cleanly_when_its_cost_reaches_the_limit(personas, tmp_path):
    # Each reply here is 120 tokens in and 40 out on Fable 5.2: (120 x 8 + 40 x 40) /
    # 1,000,000 = $0.00256. Two speeches cost $0.00512, three cost $0.00768.
    client = FakeClient(*plain_sitting())
    record = blank_record(personas)
    path = tmp_path / "record.json"
    finished, printed = sit(client, record, path, personas, max_cost=0.006)
    assert not finished
    assert len(client.calls) == 3
    assert len(record["speeches"]) == 3
    assert load(path) == record
    assert "The sitting stopped before Cicero's rebuttal" in printed
    assert "$0.0077, has reached the limit of $0.0060" in printed
    assert "THE FLOW" not in printed


def test_a_sitting_stopped_by_its_cost_can_be_carried_on_with_a_higher_limit(personas, tmp_path):
    script = plain_sitting()
    path = tmp_path / "record.json"
    sit(FakeClient(*script), blank_record(personas), path, personas, max_cost=0.006)
    resumed = load(path)
    finished, _ = sit(FakeClient(*script[3:]), resumed, path, personas, max_cost=1.00)
    assert finished
    assert len(resumed["speeches"]) == 9


def test_a_cost_limit_of_nothing_sends_no_request(personas, tmp_path):
    client = FakeClient(*plain_sitting())
    finished, _ = sit(
        client, blank_record(personas), tmp_path / "record.json", personas, max_cost=0
    )
    assert not finished
    assert client.calls == []


def test_a_stand_in_record_cannot_be_carried_on_as_a_live_sitting(personas, tmp_path):
    client = FakeClient(*plain_sitting())
    with pytest.raises(ValueError, match="this record is stand-in, and a live sitting cannot add"):
        run_sitting(
            client,
            blank_record(personas),
            tmp_path / "record.json",
            personas,
            io.StringIO(),
            provenance="live",
        )
    assert client.calls == []


def test_provenance_must_be_given(personas, tmp_path):
    with pytest.raises(TypeError, match="provenance"):
        run_sitting(
            FakeClient(), blank_record(personas), tmp_path / "r.json", personas, io.StringIO()
        )


def test_a_sitting_is_finished_with_the_characters_it_began_with(personas, tmp_path):
    record = after_one_speech(personas)
    changed = personas | {"Cicero": "You are Cicero, rewritten since the sitting began.\n"}
    client = FakeClient(*plain_sitting())
    with pytest.raises(ValueError, match="a character file has changed since this sitting began"):
        sit(client, record, tmp_path / "record.json", changed)
    assert client.calls == []


def test_an_unknown_effort_is_refused_before_any_request(personas, tmp_path):
    client = FakeClient(*plain_sitting())
    with pytest.raises(ValueError, match="effort must be one of low, medium, high, xhigh, max"):
        sit(client, blank_record(personas, effort="heroic"), tmp_path / "record.json", personas)
    assert client.calls == []


def test_an_unknown_chair_is_refused_before_any_request(personas, tmp_path):
    client = FakeClient(*plain_sitting())
    with pytest.raises(ValueError, match="chair must be one of system, user"):
        sit(client, blank_record(personas, chair="assistant"), tmp_path / "record.json", personas)
    assert client.calls == []


def test_a_record_that_does_not_follow_the_chairs_order_is_not_carried_on(personas, tmp_path):
    record = after_one_speech(personas)
    record["speeches"][0]["seat"] = "Omnibus"
    client = FakeClient(*plain_sitting())
    with pytest.raises(ValueError, match="do not follow the Chair's order"):
        sit(client, record, tmp_path / "record.json", personas)
    assert client.calls == []
