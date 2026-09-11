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
   description + few-shot examples + randomized tone/structure/personalization knobs.
4. **Memory** (`src/persona/memory.py`) — tracks recent registers/phases/topics/reply targets
   to keep output varied.

Key non-obvious decisions:

- **The LLM is provider-agnostic by design**, not just in theory (`src/llm_provider.py`). The
  long-term deployment target is two machines — a 2014 MacBook Air running everything except
  model inference, and a MacBook Air M4 running a local model (via Ollama) exposed as an
  OpenAI-compatible endpoint over the local network. Persona logic never knows or cares which
  provider answered a call.
- **Reply length is fixed at the generation layer, not by truncating strings.** The prompt
  gives a soft target (`REPLY_TARGET_CHARS`) below the hard limit (`REPLY_MAX_CHARS`), and if
  a reply still comes back over limit, the model is asked to rewrite it shorter
  (`_ensure_length()` in `reply_handler.py`). String truncation (`_sentence_aware_truncate()`)
  is a last-resort safety net only, not the primary mechanism — it should rarely fire.
- **Few-shot examples and a large voice bank exist on purpose, not as bloat.** Abstract rules
  ("sound witty, not like an assistant") give a model very little to pattern-match against —
  concrete worked examples do far more, especially for smaller/local models. This is why the
  reference repos' phrase banks run to thousands of lines, and why `voice_bank.py` and the
  `FEW_SHOT_EXAMPLES` in `prompts.py` are deliberately more extensive than a first draft would
  suggest is necessary.

## How to Read the Docs

Read in this order when picking up the project after time away:

1. **`docs/SCAFFOLDING.md`** — the authoritative phase-by-phase build checklist, checked off
   against actually-verified state (file inventory + test runs), not against what `SPEC.md`
   describes on paper. If this file's "Current Status" section below ever disagrees with
   `SCAFFOLDING.md`, trust `SCAFFOLDING.md` and fix this file to match.
2. **`CHANGELOG.md`** — `[Unreleased]` section shows what's actually landed, in order.
3. **`docs/SPEC.md`** — full technical specification: architecture, data models, LLM
   integration design, deployment plan, open questions.
4. **`docs/STRUCTURE.md`** — annotated file tree and the reasoning behind module boundaries.
   Consult before adding a new file — there's almost certainly a designated home for it.
5. **`VOICE_GUIDE.md`** — the character bible: registers, phases, tone rules, what TedKhao
   would and wouldn't say. Consult before touching any prompt template or voice-bank content —
   this is the source of truth for "does this sound like TedKhao."
6. **`docs/RESEARCH_NOTES.md`** — the underlying `defi`/`karma` research (file paths, line
   numbers, verbatim findings) that `docs/SPEC.md`'s architecture decisions are drawn from.
   Consult when a design choice needs re-justifying or re-examining, rather than re-researching
   the source repos from scratch.

## How to Update the Docs

- When a `docs/SPEC.md` "Open Questions" item gets resolved, move it into the relevant section
  and remove it from Open Questions — don't leave resolved questions sitting there.
- When the file tree changes structurally (new top-level module, renamed package), update
  `docs/STRUCTURE.md` in the same change, not as a follow-up.
- When a phase's status changes, update `docs/SCAFFOLDING.md` in the same change.
- Every meaningful change gets a `CHANGELOG.md` entry under `[Unreleased]`. Cut a version
  entry only when the user asks for one.
- If a design decision changes the Register or Phase taxonomy, update `docs/SPEC.md` and
  `VOICE_GUIDE.md` together — they describe the same taxonomy at different levels of detail
  (spec = mechanism, voice guide = character) and must stay in sync.

## Key Conventions

- Persona logic (`src/persona/`) stays domain-generic in *mechanism* — only
  `voice_bank.py`'s content and the taxonomy in `state.py` are allowed to be
  tech/history/arts-specific. Don't let domain-specific logic leak into `prompts.py` or
  `memory.py`.
- Every signal source in `src/signals/` implements the common interface in
  `src/signals/base.py`. Don't special-case one source's shape elsewhere in the codebase.
- `src/bot.py` stays a thin orchestrator. If you find yourself adding a non-trivial function
  directly to `bot.py`, it almost certainly belongs in `persona/`, `signals/`, or
  `engagement/` instead — this is the exact failure mode that made the reference repos'
  `bot.py` files grow past 9,000 lines.
- LLM calls always go through `src/llm_provider.py`'s abstraction — never call an SDK directly
  from persona/engagement code.
- Never ask the user to paste an API key or other credential into chat. Have them add it to
  `.env` directly and confirm separately once it's in place.
- Never pull/download a new Ollama model without stating the exact model name and
  approximate size and getting explicit approval first. Run `ollama list` to check what's
  already available before assuming a download is needed.
- A confirming or clarifying question from the user ("you will test X?") is not authorization
  to start implementing. Answer it; wait for an explicit instruction before writing code.

## Current Status

Phases 1 (Persona Engine), 2 (Reply Pipeline), 3 (Signal Ingestion), 4 (Original Post
Generation), 5 (Persistence), and 7 (Orchestration) are built and manually tested. Phase 6
(X/Twitter Integration) is built but only partially verified — see `docs/SCAFFOLDING.md` for
the checkbox-level breakdown. Both Phase 6's actual posting/login and Phase 7's reply-cycle
live-posting path remain unverified end-to-end for the same reason: `TWITTER_USERNAME`/
`TWITTER_PASSWORD` are still empty in this repo's `.env`. Phase 8 (Local-Model Deployment,
partially validated) and Phase 9 (Automated Tests) have no code yet beyond Phase 8's confirmed
same-machine Ollama path.

**Open item carried over from Phase 2, not resolved, now also observed on the post path**:
voice quality hasn't been validated across enough trials to trust it, for either replies or
original posts. Known failure modes seen so far: generic-assistant phrasing still recurs
occasionally, register selection is unreliable on posts/signals with no clear topic signal, and
the "personal reaction" personalization knob has produced fabricated (non-factual) detail on
more than one occasion — most recently, `build_post_prompt()`'s no-signal branch fabricated a
detail during Phase 4's own test run despite an explicit instruction not to invent facts when
there's no signal to anchor to. Don't treat any single test run as a verdict on this.

**Next up**: add real `TWITTER_USERNAME`/`TWITTER_PASSWORD` to `.env` (with a deliberate,
explicit go-ahead before running live against a real X account) to unblock end-to-end
verification of Phase 6's login/posting and Phase 7's reply cycle, keep gathering
reply/post-quality trials, or start Phase 8/9 — see `docs/SCAFFOLDING.md` for the full list
either way.

## Local Model Testing Notes

Findings from developing against Ollama on the M4 MacBook Air. Machine/model-specific —
re-verify with `ollama list` rather than trusting this is still accurate if picking this up
much later.

Currently available locally: `qwen2.5-coder:7b`, `deepseek-coder-v2:16b`, `nomic-embed-text`.

- `qwen2.5-coder:7b` / `deepseek-coder-v2:16b` — fast, no reasoning-loop issues, but both are
  code-specialized and produced generic/assistant-flavored prose rather than TedKhao's voice.
  Fine for pipeline-mechanics testing; don't treat their voice quality as representative of
  what a general-purpose instruct model would produce.
- `gemma4:12b` and `gpt-oss:20b` were tested and then deliberately deleted (`ollama rm`) after
  proving unusable — don't re-pull either without a specific reason:
  - `gemma4:12b` got stuck in an unterminated chain-of-thought loop; the OpenAI-compatible
    endpoint returned everything in a `reasoning` field and an empty `content` field even at
    1200+ max_tokens.
  - `gpt-oss:20b` was functional but too slow for interactive testing on this hardware.

## Re-entry Checklist

If you're picking this project up mid-stream:

1. Read `docs/SCAFFOLDING.md` for the authoritative phase status.
2. Read `CHANGELOG.md`'s `[Unreleased]` section for what's actually landed.
3. Skim `docs/SPEC.md`'s "Open Questions" for anything resolved since.
4. If touching persona/voice logic, re-read `VOICE_GUIDE.md` first — register/phase names and
   rules must match exactly.
5. Check whether `.env` exists and has a valid `ANTHROPIC_API_KEY` before assuming the bot can
   run end-to-end against Claude.
6. If testing against a local model, run `ollama list` first and read "Local Model Testing
   Notes" above — especially the no-download-without-approval rule.
7. If the two-machine architecture is in play, confirm which machine you're on and which
   provider `src/llm_provider.py` is configured to hit — don't assume Claude by default once
   the local-model path is active.
