"""A stand-in for Claude that replies in the API's streaming format, citations included.

The real Anthropic SDK talks to it through httpx2.MockTransport: no key, no network, no cost.
It keeps the API's promise about a citation: the cited text is taken from the documents the
request itself sent, never from the script. A scripted pin only names a paper by its title,
a few words that pick out its first sentence, and how many sentences it runs to.

Every speech it plays is a script written to test the chamber. No sitting produced any of them.
"""

import json
from pathlib import Path

import anthropic
import httpx2

SCRIPT = Path(__file__).parent / "fixtures" / "standin_sitting.json"


def load_script():
    """The scripted sitting: its motion, and its nine speeches in the Chair's order."""
    script = json.loads(SCRIPT.read_text(encoding="utf-8"))
    return script["motion"], script["speeches"]


def event(name, data):
    return f"event: {name}\ndata: {json.dumps({'type': name, **data})}\n\n"


def documents(body):
    """Every document block in a request, in the order the API numbers them."""
    return [
        block
        for message in body["messages"]
        if isinstance(message["content"], list)
        for block in message["content"]
        if block.get("type") == "document"
    ]


def citation(body, pin):
    """Build one citation the way the API promises to: out of the request's own documents."""
    for index, document in enumerate(documents(body)):
        if document["title"] != pin["paper"]:
            continue
        blocks = [block["text"] for block in document["source"]["content"]]
        first = next(i for i, text in enumerate(blocks) if pin["anchor"] in text)
        last = first + pin["sentences"]
        return {
            "type": "content_block_location",
            "cited_text": "".join(blocks[first:last]),
            "document_index": index,
            "document_title": document["title"],
            "start_block_index": first,
            "end_block_index": last,
        }
    raise AssertionError(f"the request holds no paper titled {pin['paper']!r}")


def pieces(text):
    """Cut a passage where no word ends, as a stream does: in thirds, wherever they fall."""
    third = max(1, len(text) // 3)
    return [piece for piece in (text[:third], text[third : 2 * third], text[2 * third :]) if piece]


def streamed_reply(body, speech, model):
    """One scripted speech as server-sent events: a thinking block, then a block a passage.

    A passage written as {"fallback": {"from": ..., "to": ...}} becomes the block the API
    sends where one model hands over to another. A speech marked "cut_off" stops before the
    events that end a whole reply.
    """
    spent = speech.get("usage", {})
    opening = {
        "id": "msg_standin",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [],
        "stop_reason": None,
        "stop_sequence": None,
        "usage": {
            "input_tokens": spent.get("input_tokens", 0),
            "output_tokens": 0,
            "cache_creation_input_tokens": spent.get("cache_creation_input_tokens", 0),
            "cache_read_input_tokens": spent.get("cache_read_input_tokens", 0),
        },
    }
    thinking = {"type": "thinking", "thinking": "", "signature": ""}
    signed = {"type": "signature_delta", "signature": "signed-by-the-stand-in"}
    events = [
        event("message_start", {"message": opening}),
        event("content_block_start", {"index": 0, "content_block": thinking}),
        event("content_block_delta", {"index": 0, "delta": signed}),
        event("content_block_stop", {"index": 0}),
    ]
    for index, passage in enumerate(speech["segments"], start=1):
        if "fallback" in passage:
            hop = passage["fallback"]
            block = {
                "type": "fallback",
                "from": {"model": hop["from"]},
                "to": {"model": hop["to"]},
                "trigger": {"type": "refusal", "category": None},
            }
            events.append(event("content_block_start", {"index": index, "content_block": block}))
            events.append(event("content_block_stop", {"index": index}))
            continue
        start = {"type": "text", "text": ""}
        events.append(event("content_block_start", {"index": index, "content_block": start}))
        for piece in pieces(passage["text"]):
            delta = {"type": "text_delta", "text": piece}
            events.append(event("content_block_delta", {"index": index, "delta": delta}))
        for pin in passage["pins"]:
            delta = {"type": "citations_delta", "citation": citation(body, pin)}
            events.append(event("content_block_delta", {"index": index, "delta": delta}))
        events.append(event("content_block_stop", {"index": index}))
    if speech.get("cut_off"):
        return "".join(events)
    ending = {"stop_reason": speech.get("stop_reason", "end_turn"), "stop_sequence": None}
    counted = {"output_tokens": spent.get("output_tokens", 0)}
    if "thinking_tokens" in spent:
        counted["output_tokens_details"] = {"thinking_tokens": spent["thinking_tokens"]}
    events += [
        event("message_delta", {"delta": ending, "usage": counted}),
        event("message_stop", {}),
    ]
    return "".join(events)


class StandInServer:
    """Answers each request with the next scripted speech, and keeps what it was sent.

    It names itself as the model in every reply unless told otherwise, so a record made
    from it cannot be read as the work of a Claude model.
    """

    def __init__(self, speeches, model="stand-in"):
        self.speeches = list(speeches)
        self.model = model
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        body = json.loads(request.content)
        reply = streamed_reply(body, self.speeches.pop(0), self.model)
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, text=reply)

    def body(self, index):
        return json.loads(self.requests[index].content)

    def bodies(self):
        return [self.body(index) for index in range(len(self.requests))]

    def client(self):
        return anthropic.Anthropic(
            api_key="not-a-real-key",
            base_url="https://stand-in.invalid",
            http_client=httpx2.Client(transport=httpx2.MockTransport(self)),
            max_retries=0,
        )
