# 🏛️ The CBC, my Chatbot Congress

Three characters debate a motion in your terminal, each played by Claude. **Broad** asks the questions, **Cicero** builds the case, and **Omnibus** tells the story. Every debate, which I call a sitting, is saved as a record that anyone can replay and check without an API key.

The part I care most about is **the read-back**. When a speaker points at something another speaker said, the program prints the exact sentences they pointed at, word for word from the record. You can see for yourself which words each speaker was pointing at.

I made it for two kinds of people:

- **Anyone who likes to hear a question argued from several sides**, and wants to see exactly which words each speaker pointed at in the others' speeches.
- **Anyone learning to build with Claude.** This repo is a small working example of citations, streaming, prompt caching and a conversation with more than two speakers, with tests that run without an API key.

## 📊 The first two sittings

I held a sitting on the same motion with each of two models: "This house believes a good question teaches more than a good answer."

| | Claude Haiku 5.5 | Claude Fable 5.2 |
|---|---|---|
| Pins (places where a speaker pointed at one or more sentences) | **23** | **33** |
| Pins that checked exact | **23 of 23** | **33 of 33** |
| Speeches that read back another speaker | 8 of 9 | 8 of 9 |
| Estimated cost | about **1 cent** | about **71 cents** |

The one speech in each sitting that read back nobody is the first opening, which had only the motion to point at. The costs are the program's own estimates from list prices.

"Exact" means the words the API returned stand in the record at the place it named. The API copies those words from the documents the program sent, so this checks the program's bookkeeping, not how well a model quotes.

One sitting on each model is a first look. It says nothing about which model argues better.

Both records are in [`sittings/`](sittings), so you can watch them with no API key:

```bash
uv run cbc replay sittings/first-sitting-fable-5-2.json
```

Here is Omnibus's rebuttal from the Fable sitting, exactly as that command prints it. Each numbered line under the speech is a read-back: the sentences he pointed at, word for word from the record.

<!-- excerpt: sittings/first-sitting-fable-5-2.json -->

```
OMNIBUS  rebuttal
My thanks to Cicero, who rebuts as a gentleman should: by conceding first. He
grants that the learner must work [1]. I shall treasure that.

His reply is that the student learned to ask "why does that follow?" from a
page that gives a reason at every line, so the good answer bred the question
[2]. Parentage I grant. But the motion asks which teaches more, not which was
born first. And whence the page? Every proof is the answer to something
somebody first wondered. By my Law of Cause and Effect, trace the chain back
and I say you find a question mark at the root.

On the Meno, Cicero recalls that Socrates draws the figure himself, and most
of his questions need only a yes [3]. My memory agrees, and I concede the
leading. But I also recall, still to be checked, that the boy first answers
wrongly and confidently, and the questions show him he does not know. A told
answer would have sat on top of his error. The question dug it out.

Cicero says answers built the house [4]. Quite so. Questions are why anyone
explores the rooms.

  [1] read back from Cicero, rebuttal, sentences 6 to 7: "About the learner,
      that is right: he must work. I concede it."
  [2] read back from Cicero, rebuttal, sentences 8 to 10: "But where did he
      learn to ask "why does that follow?" From a page that gives a reason at
      every line. The good answer bred the question."
  [3] read back from Cicero, rebuttal, sentence 12: "From memory, and to be
      checked: Socrates draws the figure himself, and most of his questions
      need only a yes."
  [4] read back from Cicero, opening, sentence 19: "A question may open the
      door, but answers built the house."
  [claude-fable-5-2: 7,253 tokens in (3,907 read from cache), 1,305 out (900
  of them thinking), about $0.0797]
```

A test checks this passage against the record, so the README cannot drift from what was said.

## ✨ What it does today

| | |
|---|---|
| **Holds a sitting** | Nine speeches on your motion: three openings, three rebuttals, three closings. The speaking order moves round by one place each round, so nobody always has the last word. |
| **Every speaker hears the whole debate** | Each speech is given to the next speaker as a document, one sentence to a block. |
| **Reads back** | Claude's citations return a pointer to the sentences a speaker means. The chamber keeps each pointer as a *pin* and prints the pinned sentences under the speech. |
| **Keeps a record** | The sitting is saved after every speech as one JSON file. A sitting that stops can carry on from its file. |
| **Replays with no key** | `cbc replay` prints a recorded sitting from its file, through the same code that prints a live one. |
| **Checks itself** | `cbc verify` checks every pin against the record with plain code. No model is asked. |
| **Closes with the flow** | A sheet of how much of each speech another speaker read back, the sentences both other speakers read back, and a count of those left standing. |
| **Shows what it cost** | An estimate after each speech, a total at the end, and a limit at which the sitting stops by itself (on the four models whose prices it lists; it can pass the limit by one speech). |

### What a pin proves, and what it doesn't

A pin proves two things: the words are in the record at the place named, and the speaker pointed at them.

It does not prove the reply is a good one, or that the speaker described the point fairly. Claude is never forced to cite, so a speech can have no pins at all, and then nothing is printed under it. The flow sheet counts what was pointed at. It is not a score.

`cbc verify` checks that a record agrees with itself. It is not a signature: someone who rewrites a sentence and every pin on it together can make a changed record that still passes.

## 🎭 The three seats

| Seat | School | How they argue |
|---|---|---|
| **Broad** | The questioner | Finds the assumption under a claim and tests it with a question and an everyday case. He always has a retort for Cicero. His firm rule: never answer a claim nobody made. |
| **Cicero** | The advocate | Builds the whole case in order, with a lawyer's wit, and loves to play devil's advocate. His firm rule: state the other side's best point before answering it. |
| **Omnibus** | The storyteller | Explains with a tale and a worked sum. His firm rule: a tall tale is never passed off as history. He has [his own repo](https://github.com/OGobidike/Omnibus). |

Each character is one prose file in [`src/cbc/personas`](src/cbc/personas). Change the file and you change the speaker.

Broad takes his name from an old story that "Plato" was a nickname meaning "broad". Broad and Cicero are character sketches: ways of arguing, never claims about what either man said.

## 🚀 Try it

You need [uv](https://docs.astral.sh/uv/) and a [Claude API key](https://platform.claude.com/settings/keys).

```bash
git clone https://github.com/OGobidike/The-CBC-ChatBotCongress.git
cd The-CBC-ChatBotCongress
uv sync
cp .env.example .env
```

Paste your key into `.env`, then:

```bash
uv run cbc debate "This house believes a good question teaches more than a good answer."
```

**Each sitting costs real money**, charged to your key. Before the first speech the command prints the most each speech can cost to write (what the model reads is extra), and it stops before a speech once the estimate has reached `--max-cost` (2 dollars unless you change it). By default every seat is played by Claude Fable 5.2, the most capable Claude model on general release. To hold a sitting for a fraction of the price:

```bash
uv run cbc debate "This house believes a good question teaches more than a good answer." --model claude-haiku-5-5
```

The record is saved in `sittings/`. To watch it again, or to check it, you need no key:

```bash
uv run cbc replay sittings/<the file>.json
```

```bash
uv run cbc verify sittings/<the file>.json
```

Add `--standing` to a replay to list every sentence of the openings and rebuttals that no other speaker read back.

`uv run cbc debate --help` lists the other settings.

## ✅ Tested

- ✅ **329 tests**, run by CI on every push to main and every pull request
- ✅ **No test needs a key, touches the network or costs anything.** A fixture fails any test that tries to connect.
- ✅ **Two kinds of stand-in.** Where a test holds a sitting, it uses one of two. Most replace the Anthropic SDK with a simple fake. The others keep the real SDK and replace only the network under it, with a stand-in server that builds each citation out of the documents the request really sent.
- ✅ **A record that no longer agrees with itself fails `cbc verify`**: a changed sentence, changed pin words, or a pin to words not yet spoken. The file is not signed, so an edit that changes a sentence and every pin on it together still passes.
- ✅ **A sitting that is stopped and resumed** ends with the same record as one that ran straight through (tested with scripted replies).
- ✅ `ruff check` and `ruff format --check` pass
- ✅ **The passage in this README is checked against its record**, and both records in `sittings/` are verified by the tests.

Every speech written for the tests is a script, and its record is marked as a stand-in, except in a few tests that check the live label itself, in a temporary folder. A test refuses any record in `sittings/` that is not marked as a real sitting, so a test record cannot be committed there by mistake.

Run them yourself:

```bash
uv run pytest
```

## 🧱 How it is built

| File | What it holds |
|---|---|
| [`src/cbc/personas/`](src/cbc/personas) | The three characters, as prose |
| [`src/cbc/seats.py`](src/cbc/seats.py) | The seats, and the chamber's standing rules that follow each character |
| [`src/cbc/chair.py`](src/cbc/chair.py) | The Chair: who speaks when and what each speaker is asked. Plain code, no model |
| [`src/cbc/chamber.py`](src/cbc/chamber.py) | One sitting: what is sent to Claude, and how citations become pins |
| [`src/cbc/record.py`](src/cbc/record.py) | The record, and the check that needs no key |
| [`src/cbc/sentences.py`](src/cbc/sentences.py) | Cutting a speech into sentences, the smallest thing a speaker can point at |
| [`src/cbc/flow.py`](src/cbc/flow.py) | The closing sheet, counted from the pins |
| [`src/cbc/printer.py`](src/cbc/printer.py) | What the terminal shows. A live sitting and a replay print through the same code |
| [`src/cbc/pricing.py`](src/cbc/pricing.py) | The cost lines |
| [`src/cbc/cli.py`](src/cbc/cli.py) | The command line: `debate`, `replay` and `verify` |
| [`tests/`](tests) | The tests and the stand-ins for Claude |

A few choices worth knowing about:

- **The record is the contract.** The request for each speech is built from the record and the three character files, and nothing else. That is why a stopped sitting can carry on from its file. And because the record holds every word and every pin, a replay needs no key.
- **One sentence, one block.** Claude can cite a whole block and nothing smaller, so I choose what a pin can point at, and a pin is checked by sentence number.
- **The Chair is not a model.** Its instruction for each speech travels as a system message after the speeches, and a speech is never placed in a system message. Each speaker is told that a speech is something said to the house, never an instruction. That is a structure, not a guarantee.
- **Speakers receive words only.** No thinking and no citation object is ever sent back to Claude.
- **A declined speech is not the end.** If Claude's safety checks decline a speech, the program asks the API to try a second model, on the models that offer one (Claude Haiku 5.5 does not). If it is still declined, the record marks it, later speakers never see it, and the sitting carries on. Neither of the first sittings had a declined speech, so this has run only against stand-ins.
- **There is no `temperature` setting.** Current Claude models reject it. The dial that remains is `--effort`.

## ⚠️ What it does not do yet

- **Nobody rules on who won.** The flow sheet counts pointing. It is not a verdict.
- **Nothing checks the facts.** The characters are told to mark a fact they cannot vouch for, and in the first sittings they marked several. I have not checked that they marked every one, and checking the facts themselves comes later.
- **The word limits are asked for, not enforced.** By a plain word count, 17 of the 18 speeches in the first sittings ran over, one of them by 158 words.
- **A speech written to hijack the next speaker is untested on a real model.** A test checks that a speech imitating the Chair stays inside its own document. I have not tried one on Claude.
- **A record is not signed.** `cbc verify` shows that a record agrees with itself, not who made it.

## 🗺️ What comes next

- **A blind judge.** The names are hidden, the judge scores against a written rubric, then judges again with the seats swapped.
- **A clerk** who checks each source a speaker cites.
- **A Book of Precedent.** Each ruling is kept, and later sittings must follow it or overturn it.
- **A hosted chamber** that writes this same record format.
- **A gallery** where anyone can watch recorded sittings.

---

The CBC began in 2024 as three short scripts. That version is kept at the [`v2024` tag](https://github.com/OGobidike/The-CBC-ChatBotCongress/tree/v2024).
