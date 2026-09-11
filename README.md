# TedKhao

A curious polymath, live on X/Twitter — posting and replying about technology, history, and
the arts, driven by real signal and a genuine, wide-ranging emotional register rather than a
flat "helpful assistant" voice.

## What it does

TedKhao pulls signal from live sources (new papers, historical anniversaries, museum
collections, tech discussion) and its own timeline, decides what's actually worth talking
about and in what mood, then writes original posts and replies in a consistent, recognizably
human voice — powered by an LLM behind a provider-agnostic abstraction, so the backing model
can move from a hosted API to a local one without touching the personality logic.

This project reimagines a proven bot-personality architecture researched from
[KingRaver/defi](https://github.com/KingRaver/defi) and [KingRaver/karma](https://github.com/KingRaver/karma)
(two iterations of a crypto-trading Twitter bot) — the four-layer personality engineering
pattern is reused; the crypto domain and all content are not.

## Tech stack

- Python 3.11+
- Selenium (Chrome/ChromeDriver) for X/Twitter automation
- SQLite for persistence
- Provider-agnostic LLM layer — Anthropic Claude for development, with a local
  OpenAI-compatible endpoint (e.g. Ollama) supported for self-hosted inference
- Public/free content APIs: arXiv, Wikipedia/Wikidata, Hacker News, Met Museum, Rijksmuseum,
  Smithsonian Open Access

## Prerequisites

- Python 3.11+
- Chrome browser + matching ChromeDriver
- An Anthropic API key (for development) — see `.env.example`
- An X/Twitter account for the persona to operate as

## Getting started

```bash
# Clone and enter the project
cd tedkhao

# Create and activate a virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# edit .env with your credentials

# Initialize the database
python src/database.py

# Run the bot
python src/bot.py
```

## Usage

Running `src/bot.py` starts the full analysis/post cycle: fetch signals → classify
register/phase → generate content or scan the timeline for reply opportunities → post →
log. Cadence and behavior are controlled via `src/config.py` and `.env`.

Generation saves drafts; dry runs do not consume reply targets. Live publication attempts
are recorded before browser access. Confirmed replies suppress duplicates, while uncertain
and legacy outcomes are held for reconciliation. Browser methods now observe X's actual
response to a submission -- a toast with a status permalink, or an error dialog -- before
reporting confirmed, failed, or uncertain (RC-104); a bare click is never read as success,
and a timeout or crash after submission stays uncertain rather than being retried
automatically. Real X selectors and confirmation behavior remain unverified against a live
account pending RC-110's authorized live check.
Before the first startup with an existing database, follow the
[RC-102 backup and migration procedure](docs/PUBLICATION_MIGRATION.md).

**Browser lifecycle (RC-103):** one `BrowserSession` (`src/utils/browser.py`) owns the Chrome
WebDriver for the life of the process -- `python bot.py` (the resident timer loop) launches it
once and reuses it across every cycle instead of relaunching Chrome per action; `python bot.py
--once` uses it for a single cycle and closes it with the process, so use the resident loop
rather than an external `--once` cron schedule when you want the browser to stay open between
cycles. A lock on `data/browser_profile/` refuses a second process sharing the same profile at
the same time. If X asks for something a script can't clear -- an expired login, a
verification challenge, a rate limit, an account warning -- the resident loop pauses X actions
(logged clearly) rather than retrying login automatically; stop the process and run:

```bash
venv/bin/python -c "from utils.browser import resume_manual_login as r; r()"
```

to clear it by hand in a visible Chrome window, then restart the resident loop.

## Verification

Run deterministic persistence, bot-cycle, and review-database isolation checks with:

```bash
venv/bin/python tests/run_offline.py
```

No credentials are required: the runner disables `.env` loading, uses fake providers and
removed-after-run temporary databases, and blocks network connections, browser launches,
subprocesses, and SQLite access outside its temporary directory. RC-102 checks also cover
publication outcomes, restart holds, transaction rollback, and migration/restore against
copied legacy fixtures. RC-103 checks cover `BrowserSession` lifecycle against a fake driver:
one launch across multiple cycles, shared driver identity, no per-action `quit()`, bounded
crash recovery, and clean shutdown on interruption. RC-104 checks cover submission
confirmation against a fake driver: a toast with a status permalink resolves to confirmed
(with the external ID/URL captured), an error dialog resolves to failed, a bounded timeout
with no evidence resolves to uncertain rather than either, and a crash after the click
propagates without touching the shared driver. RC-105 checks cover generation validation
(malformed/missing/null provider output never reaches a persisted draft or a held reply
target); RC-106 covers source-selection tie-breaking and evidence-gated Breakthrough/
Convergence; RC-107 covers recent-source-coverage deduplication and re-eligibility; RC-108
covers Convergence/callback/no-signal prompt grounding; RC-109 covers per-operation failure
isolation and `summarize_cycle()`. RC-110's `tests/manual_test_integrated_regression.py` runs
several of `bot.py`'s cycles against one shared fake-driver `BrowserSession` and a database
that starts as a real (in-test) legacy migration fixture, verifying driver reuse, a bounded
crash-and-relaunch, repeat-source exclusion, and per-operation failure isolation together
rather than in separate fixtures, plus publication-state persistence across a simulated
process restart. The operational database is not migrated by these tests.

Model-backed voice review is separate:

```bash
venv/bin/python tests/manual_test_posts.py
venv/bin/python tests/manual_test_replies.py
# Optional retention, explicitly separate from the operational database:
venv/bin/python tests/manual_test_posts.py --review-db data/review-posts.db
```

These two harnesses call production generation handlers with fixture inputs and the configured
model; their databases are temporary by default. `--review-db` rejects the configured
operational database and `data/tedkhao.db`, including symlink/hard-link aliases.
Model quality, live feeds, and `tests/manual_test_browser.py` are integration checks and
are excluded from the offline command. Live X behavior remains unverified.

## Project structure

See [docs/STRUCTURE.md](docs/STRUCTURE.md) for the full annotated layout. Briefly:

- `src/persona/` — the personality engine (state classification, voice bank, prompt
  construction, anti-repetition memory)
- `src/signals/` — content-signal ingestion (arXiv, history, arts, Hacker News, X timeline)
- `src/engagement/` — incoming-post analysis and reply targeting
- `docs/SPEC.md` — full technical specification
- `VOICE_GUIDE.md` — TedKhao's voice and character reference

## Contributing

This is currently a single-persona, single-operator project. If that changes, contribution
guidelines will move here — for now, see `CLAUDE.md` for conventions when working in this
codebase.

## License

MIT (default — revisit if this account's content or code needs different terms later).
