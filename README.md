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
