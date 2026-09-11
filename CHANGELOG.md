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
- Signal ingestion modules (arXiv, Wikipedia "On this day", Hacker News, museum APIs)
- State engine (Register + Phase classification)
- Voice bank content for all 8 registers
- Prompt engine (tone/structure/personalization knobs)
- LLM provider abstraction (Anthropic adapter + OpenAI-compatible/local adapter)
- X/Twitter integration (Selenium posting + timeline scraping + reply handling)
- SQLite schema and database layer

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
