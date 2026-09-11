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
│   └── STRUCTURE.md            # This file
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
│   │   └── reply_handler.py       # Scores reply opportunities, generates replies via prompt engine
│   │
│   └── utils/
│       ├── __init__.py
│       ├── browser.py             # Selenium WebDriver setup
│       └── logger.py              # Centralized logging
│
├── data/
│   ├── tedkhao.db                 # Main SQLite database (gitignored)
│   └── backup/                    # Automated backups (gitignored)
│
├── logs/                          # Application logs (gitignored)
│
└── tests/
    ├── test_state.py              # Register/Phase classification tests
    ├── test_voice_bank.py
    ├── test_prompts.py
    └── test_signals/               # One test module per signal source
```

## Design notes

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
