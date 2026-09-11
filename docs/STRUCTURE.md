# TedKhao — Project Structure

A deliberate departure from the reference architecture's monolithic files (the source repos'
`bot.py` files run 9,000-10,500 lines each) — each of the four personality layers, and each
signal source, gets its own module.

```
tedkhao/
├── README.md                   # Project overview, setup, usage
├── CLAUDE.md                   # Claude Code's reference for working in this repo
├── CHANGELOG.md                # Keep a Changelog-format history
├── VOICE_GUIDE.md              # TedKhao's voice/character bible (the "style guide" for a bot with no UI)
├── .env.example                # Template for required environment variables
├── .gitignore
├── requirements.txt
│
├── docs/
│   ├── SPEC.md                 # Full technical specification
│   ├── STRUCTURE.md            # This file
│   ├── SCAFFOLDING.md          # Historical phase-by-phase build checklist (Phases 1-9)
│   ├── REVIEW_CHECKLIST.md     # Live post-launch remediation tracker (RC-101-110)
│   ├── PUBLICATION_MIGRATION.md # RC-102 publication schema, migration, and reconciliation
│   ├── VOICE_TRIALS.md         # RC-108+ model-backed generation trials, separate from deterministic tests
│   ├── LIVE_VALIDATION_PROCEDURE.md # RC-110 authorized live-account validation procedure
│   └── RESEARCH_NOTES.md       # Source-referenced findings from the defi/karma research
│
├── src/
│   ├── bot.py                  # Thin orchestrator: wires up the analysis/post cycle, no business logic inline
│   ├── config.py                # Configuration, env loading, constants
│   ├── database.py              # SQLite schema + access layer
│   ├── llm_provider.py          # Provider-agnostic LLM abstraction (Anthropic, OpenAI-compatible/local)
│   ├── datetime_utils.py        # Timezone-safe datetime helpers
│   │
│   ├── persona/                 # The four-layer personality engine
│   │   ├── __init__.py
│   │   ├── state.py              # Register + Phase classification (replaces mood_config.py)
│   │   ├── voice_bank.py         # Hand-written phrase/reference fragments keyed by Register
│   │   ├── prompts.py            # Prompt templates + tone/structure/personalization knobs
│   │   └── memory.py             # Anti-repetition tracking (recent registers/phases/topics)
│   │
│   ├── signals/                  # Content-signal ingestion (replaces the market-data half of the reference bots)
│   │   ├── __init__.py
│   │   ├── base.py                # Common Signal dataclass + fetch() interface
│   │   ├── arxiv_feed.py          # Technology domain signal
│   │   ├── history_today.py       # History domain signal (Wikipedia/Wikidata "On this day")
│   │   ├── hackernews_feed.py     # Technology domain signal (trending discussion)
│   │   ├── arts_feed.py           # Arts domain signal (Met/Rijksmuseum/Smithsonian open APIs)
│   │   └── timeline_scraper.py    # X/Twitter timeline scraping (Selenium) — conversation-driven signal
│   │
│   ├── engagement/                # Perception + reply targeting (replaces content_analyzer.py)
│   │   ├── __init__.py
│   │   ├── content_analyzer.py    # Classifies incoming posts: topic, sentiment, question/opinion
│   │   ├── reply_handler.py       # Scores reply opportunities, generates replies via prompt engine
│   │   ├── publication.py         # RC-102 durable publication transitions and browser boundary
│   │   └── post_handler.py        # Original-post equivalent of reply_handler.py (Phase 7)
│   │
│   └── utils/
│       ├── __init__.py
│       ├── browser.py             # Selenium WebDriver setup + RC-103 BrowserSession ownership + RC-104 confirmation
│       └── logger.py              # Centralized logging
│
├── data/
│   ├── tedkhao.db                 # Main SQLite database (gitignored)
│   └── backup/                    # Automated backups (gitignored)
│
├── logs/                          # Application logs (gitignored)
│
└── tests/                          # Manual harnesses, plain asserts -- no pytest suite yet (Phase 9)
    ├── run_offline.py              # RC-101 entry point: runs every offline-safe harness below
    ├── manual_test_publication.py  # RC-102/RC-103 lifecycle, atomicity, copied migration/restore checks
    ├── manual_test_browser_session.py      # RC-103 fake-driver BrowserSession lifecycle checks
    ├── manual_test_browser_confirmation.py # RC-104 fake-driver submission confirmation checks
    ├── manual_test_persistence.py  # Phase 5 schema/PersonaMemory persistence checks
    ├── manual_test_bot_cycle.py    # Phase 7 orchestrator cycle checks (fake provider, temp db)
    ├── manual_test_generation_validation.py # RC-105 provider/handler nonempty-output checks
    ├── manual_test_state_selection.py # RC-106 tie-break/evidenced-Breakthrough/Convergence checks
    ├── manual_test_source_coverage.py # RC-107 recent-source-coverage deduplication checks
    ├── manual_test_prompt_grounding.py # RC-108 Convergence/callback/no-signal prompt-contract checks
    ├── manual_test_failure_isolation.py # RC-109 per-operation failure isolation + summarize_cycle() checks
    ├── manual_test_integrated_regression.py # RC-110 combined multi-cycle regression (migration + everything above, together)
    ├── manual_test_posts.py        # Model-backed original-post voice review harness
    ├── manual_test_replies.py      # Model-backed reply voice review harness
    ├── manual_test_browser.py      # Live-Chrome smoke test (no real account actions)
    └── review_database.py          # Temporary or explicitly selected voice-review storage
```

## Design notes

Review remediation is tracked in [REVIEW_CHECKLIST.md](REVIEW_CHECKLIST.md), with work IDs,
dependencies, acceptance checks, and verification evidence. [SCAFFOLDING.md](SCAFFOLDING.md)
remains the historical build-phase tracker.

- **`persona/` is the reusable core.** If TedKhao's domain ever changed again, this is the
  directory that should need the least rewriting — only `voice_bank.py`'s content and
  `state.py`'s taxonomy are domain-specific; the *mechanism* (score signals → pick
  register/phase → build prompt → sample voice bank → generate → remember) is not.
- **`signals/` is designed for growth by addition, not modification.** Each source implements
  the same interface (`src/signals/base.py`), so adding a fourth arts API or swapping Hacker
  News for something else never touches `persona/` or `bot.py`.
- **`bot.py` stays thin.** The reference repos' biggest structural weakness is that
  `bot.py`/`integrated_trading_bot.py` accumulated nearly all logic inline over time. TedKhao's
  `bot.py` should only ever coordinate calls into `persona/`, `signals/`, and `engagement/` —
  if it starts growing business logic, that logic belongs in one of those packages instead.
