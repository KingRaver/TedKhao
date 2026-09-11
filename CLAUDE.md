# CLAUDE.md — TedKhao

You are working on TedKhao: an AI social media personality for X/Twitter — a "curious
polymath" that posts and replies about technology, history, and the arts. It is a
reimagining of a bot-personality architecture researched from two crypto-trading bot repos
([KingRaver/defi](https://github.com/KingRaver/defi), [KingRaver/karma](https://github.com/KingRaver/karma))
by the same author — the *personality engineering pattern* from those repos is reused; the
crypto domain, content, and phrase banks are not.

## Project Summary

TedKhao is not a chatbot and not a trading bot — it's a scheduled, semi-autonomous social
media presence. It ingests signal from live sources (arXiv, Wikipedia "On this day", Hacker
News, museum open-data APIs) and its own X timeline, classifies the current moment into a
Register (tone) and Phase (macro content shape), and generates original posts and replies
through an LLM behind a provider-agnostic abstraction. The persona's defining trait is
genuine, wide-ranging curiosity that moves freely across domains rather than covering them as
fixed beats.

## Architecture at a Glance

Four layers, each in its own module (see `docs/STRUCTURE.md` for the full tree):

1. **State engine** (`src/persona/state.py`) — scores the signal pool into a Register + Phase.
2. **Voice bank** (`src/persona/voice_bank.py`) — static, hand-written phrase fragments keyed
   by Register, for cheap reliable flavor without an LLM call.
3. **Prompt engine** (`src/persona/prompts.py`) — builds the actual LLM prompt: fixed persona
   description + randomized tone/structure/personalization knobs + anti-bot humanization
   instructions.
4. **Memory** (`src/persona/memory.py`) — tracks recent registers/phases/topics/reply targets
   to keep output varied.

Key non-obvious decision: **the LLM is provider-agnostic by design**, not just in theory. The
long-term deployment target is two machines — a 2014 MacBook Air running everything except
model inference, and a MacBook Air M4 running a local model (via Ollama or equivalent)
exposed as an OpenAI-compatible endpoint over the local network. The persona logic should
never know or care which provider answered a given call. Development happens against Claude
via the same abstraction (`src/llm_provider.py`) that will later point at the M4.

## How to Read the Docs

- **`docs/SPEC.md`** — the full technical specification: architecture, data models, LLM
  integration design, deployment plan, open questions. Read this first when picking up work
  after time away.
- **`docs/STRUCTURE.md`** — the annotated file tree and the reasoning behind module
  boundaries. Consult before adding a new file — there's almost certainly a designated home
  for it.
- **`VOICE_GUIDE.md`** — the character bible: registers, phases, tone rules, what TedKhao
  would and wouldn't say. Consult before writing or editing any prompt template or voice-bank
  content — this is the source of truth for "does this sound like TedKhao."
- **`CHANGELOG.md`** — what's actually been built, in order. More reliable than memory for
  "have I done X yet."

## How to Update the Docs

- When a decision in `docs/SPEC.md`'s "Open Questions" section gets resolved, move it into the
  relevant section and remove it from Open Questions — don't leave resolved questions sitting
  there.
- When the file tree changes structurally (a new top-level module, a renamed package),
  update `docs/STRUCTURE.md` in the same change, not as a follow-up.
- Every meaningful change gets a `CHANGELOG.md` entry under `[Unreleased]`. Cut a version
  entry only when the user asks for one.
- If a design decision changes the Register or Phase taxonomy, update both `docs/SPEC.md` and
  `VOICE_GUIDE.md` together — they must stay in sync since they describe the same taxonomy at
  different levels of detail (spec = mechanism, voice guide = character).

## Key Conventions

- Persona logic (`src/persona/`) must stay domain-generic in *mechanism* — only
  `voice_bank.py`'s content and the taxonomy in `state.py` are allowed to be
  tech/history/arts-specific. Don't let domain-specific logic leak into `prompts.py` or
  `memory.py`.
- Every signal source in `src/signals/` implements the common interface in
  `src/signals/base.py`. Don't special-case one source's shape elsewhere in the codebase.
- `src/bot.py` stays a thin orchestrator. If you find yourself adding a non-trivial function
  directly to `bot.py`, it almost certainly belongs in `persona/`, `signals/`, or
  `engagement/` instead — this is the exact failure mode that made the reference repos'
  `bot.py` files grow past 9,000 lines.
- LLM calls always go through `src/llm_provider.py`'s abstraction — never call an SDK
  directly from persona/engagement code.

## Current Status

**Phase: scaffolding complete, no code written yet.** SPEC.md, STRUCTURE.md, README.md,
VOICE_GUIDE.md, and this file exist. The Register/Phase taxonomy is finalized. Nothing in
`src/` has been implemented.

**Next up**: build the persona layer first (`state.py`, `voice_bank.py`, `prompts.py`,
`memory.py`) against a small hand-written fixture of fake signals, before wiring up any real
signal source or the X/Twitter integration — validate the voice works before automating
anything.

## Re-entry Checklist

If you're picking this project up mid-stream:

1. Read `CHANGELOG.md`'s `[Unreleased]` section to see what's actually built vs. planned.
2. Skim `docs/SPEC.md`'s "Open Questions" — anything resolved since should be reflected there.
3. If touching persona/voice logic, re-read `VOICE_GUIDE.md` before writing anything —
   register/phase names and rules must match exactly.
4. Check whether `.env` exists and has a valid `ANTHROPIC_API_KEY` before assuming the bot can
   run end-to-end.
5. If the two-machine architecture is in play, confirm which machine you're on and which
   provider `src/llm_provider.py` is configured to hit — don't assume Claude by default once
   the local-model path exists.
