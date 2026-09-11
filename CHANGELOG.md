# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `docs/SCAFFOLDING.md`: phased build checklist, verified against actual repo state rather
  than the plan in `docs/SPEC.md` -- Persona Engine and Reply Pipeline phases done, Signal
  Ingestion / Original Post Generation / Persistence / X integration / Orchestration phases
  not yet started.
- `docs/RESEARCH_NOTES.md`: source-referenced (file path + line number) findings from the
  `defi`/`karma` architecture research that `docs/SPEC.md`'s design decisions are drawn from.
- Phase 3 (Signal Ingestion): `src/signals/base.py` (`Signal` dataclass + shared
  `rank_novelty()` helper), and four working source modules -- `arxiv_feed.py` (cs.AI/cs.CL/
  cs.LG via arXiv's Atom API), `history_today.py` (Wikipedia "On this day" REST API),
  `hackernews_feed.py` (top stories via the HN Firebase API), and `arts_feed.py` (Met Museum
  Open Access API only -- Rijksmuseum/Smithsonian need API keys not yet in `.env`). Also
  `select_phase_register_and_signal()` in `src/persona/state.py`, the original-post
  equivalent of `select_register_for_reply()`: scores a fetched signal pool into a Phase +
  Register + which Signal to write about. All four sources and the scoring function verified
  against live API calls.
- Phase 4 (Original Post Generation): `build_post_prompt()` in `src/persona/prompts.py`, the
  original-post equivalent of `build_reply_prompt()` -- driven by a Phase + selected `Signal`
  instead of an incoming post. Adds `FEW_SHOT_POST_EXAMPLES` (two per Register),
  `POST_STRUCTURE_POOL`/`POST_PERSONALIZATION_POOL`/`POST_PHASE_NOTE` (post-specific knobs from
  `VOICE_GUIDE.md`), and `POST_MAX_CHARS`/`POST_TARGET_CHARS` in `config.py`. The no-signal
  branch (empty signal pool) explicitly instructs the model not to invent a fact to sound
  anchored. `tests/manual_test_posts.py`: manual harness covering six fake signal pools (one
  per reachable Phase, plus an empty pool), verified with a live run against the local
  `deepseek-coder-v2:16b`.

- Phase 5 (Persistence): `src/database.py` -- SQLite schema (`signals`, `state_history`,
  `posts`, `replied_posts`) plus a functional access layer (`init_db()`, insert/query
  functions). `state_history.phase` is nullable, deviating from the `docs/SPEC.md` snippet --
  the reply path only ever produces a Register (no Phase concept for a reply), so a
  reply-triggered row has no phase to record; `docs/SPEC.md` updated to match. `PersonaMemory`
  (`src/persona/memory.py`) now loads its anti-repetition state from the database on
  construction and gains `record_state()`/`record_reply()`, which update the in-memory lists
  and persist in one call. `engagement/reply_handler.py`'s `generate_reply()` now persists
  every reply. `tests/manual_test_posts.py` persists the triggering `Signal` and generated
  `Post` directly (no `post_handler.py` yet -- still Phase 7's job). New
  `tests/manual_test_persistence.py`: plain-assert harness proving a fresh `PersonaMemory`
  instance actually sees a prior instance's writes (simulated restart), against a temp DB and
  a fake, no-network `LLMProvider`. Verified both by that harness and by live runs of
  `manual_test_replies.py`/`manual_test_posts.py` against `deepseek-coder-v2:16b`, inspecting
  the resulting SQLite file directly.

### Changed
- Rewrote `CLAUDE.md` in one pass instead of leaving it as accumulated patches -- corrected
  stale "no code written yet" status, added local-model testing notes (`gemma4:12b` and
  `gpt-oss:20b` tested and deleted, with why), and stated standing conventions plainly rather
  than framing them as gaps.

### Fixed
- Reply length overflow: replies exceeding the character limit were being chopped
  mid-sentence by string truncation. Now the model rewrites its own reply to fit when it
  runs over (`_ensure_length()` in `reply_handler.py`), with truncation kept only as a
  last-resort safety net. Hard limit lowered to 275 chars with a 220-char soft target in
  the prompt so generation naturally leaves margin.

### Planned
- X/Twitter integration (Selenium posting + timeline scraping + reply handling) (Phase 6)

## [0.1.0] - 2026-09-11

### Added
- Project scaffolded: SPEC.md, STRUCTURE.md, README.md, CLAUDE.md, VOICE_GUIDE.md
- Persona concept defined: "curious polymath" across technology, history, and the arts
- Four-layer personality architecture designed (state engine → voice bank → prompt engine →
  anti-repetition memory), adapted from architecture research on
  [KingRaver/defi](https://github.com/KingRaver/defi) and [KingRaver/karma](https://github.com/KingRaver/karma)
- Register taxonomy defined (Delighted, Awestruck, Reverent, Wistful, Amused, Restless,
  Provoked, Giddy)
- Phase taxonomy defined (Convergence, Breakthrough, Contested, Anniversary, Excavation, Quiet)
- Provider-agnostic LLM strategy decided: Claude for development, local model (M4 MacBook Air
  via Ollama-style OpenAI-compatible endpoint) for the long-term deployment target
- Long-term deployment architecture decided: 2014 MacBook Air as orchestrator, M4 MacBook Air
  as thin inference server, connected over local network (.local hostname)
