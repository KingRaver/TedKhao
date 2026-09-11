# TedKhao — Technical Specification

## Overview & Purpose

TedKhao is an AI-driven social media personality: a "curious polymath" account on X/Twitter
that posts about technology, history, and the arts, and replies to others in the same voice.
It is a reimagining of a proven bot-personality architecture (researched from
[KingRaver/defi](https://github.com/KingRaver/defi) and [KingRaver/karma](https://github.com/KingRaver/karma),
two iterations of a crypto-trading Twitter bot) — the personality *engineering pattern* is
reused, the crypto domain and content are not.

TedKhao's defining trait is genuine curiosity that moves freely across domains rather than a
fixed analytical angle. It doesn't "cover" technology, history, and the arts as beats — it
follows whatever is genuinely interesting right now, and its signature move is noticing when
two of those domains rhyme with each other.

## Goals & Non-Goals

**Goals**
- Post original content driven by real external signal (new papers, historical anniversaries,
  art/museum content, tech news) — not randomly generated musing.
- Reply to others' posts in a consistent, recognizably human voice.
- Maintain a wide, genuine emotional register (delight, awe, wistfulness, irritation, giddy
  excitement) rather than a flat "helpful assistant" tone.
- Be LLM-provider-agnostic from day one, so the backing model can move from a hosted API
  (Claude) to a locally-hosted model without touching the persona logic.
- Grow a real audience — this is a public-facing account, not a private experiment.

**Non-Goals (v1)**
- No trading, financial content, or crypto/DeFi material of any kind.
- No official paid X API integration (Selenium-based scraping/posting, matching the reference
  architecture) — revisit only if this graduates past prototype scale.
- No multi-tenant / multi-persona support — this spec is for one persona, one account.
- No Docker/Kubernetes or cloud infrastructure — the deployment target is a single
  always-on Mac (see Deployment).
- No cross-machine networking beyond a local network — VPN/remote connectivity between the
  orchestrator and the inference machine is explicitly deferred.

## User Stories / Use Cases

- As a follower, I see 3-6 original TedKhao posts a day that feel like they come from one
  consistent, curious person, not a content mill.
- As someone TedKhao replies to, the reply reads like an engaged, knowledgeable person joined
  the conversation — not a bot bolting on a keyword-triggered response.
- As the operator, I can swap the backing LLM (Claude today, a locally-hosted model later)
  by changing configuration, not code.
- As the operator, I can see why TedKhao posted what it posted — which signal, which register,
  which phase — for debugging and tuning.

## Personality Architecture

TedKhao reuses a four-layer pattern identified in the reference codebases, redesigned for the
tech/history/arts domain:

```
┌─────────────────────────────────────────────────────────────────┐
│  1. STATE ENGINE (src/persona/state.py)                         │
│     Scores the current signal pool into a Register (moment-to-  │
│     moment tone) and a Phase (macro shape of today's content)   │
└───────────────────────────┬───────────────────────────────────────┘
                            │
┌───────────────────────────▼───────────────────────────────────────┐
│  2. VOICE BANK (src/persona/voice_bank.py)                       │
│     Hand-written phrase/reference fragments keyed by Register,   │
│     sampled for cheap, reliable in-character flavor              │
└───────────────────────────┬───────────────────────────────────────┘
                            │
┌───────────────────────────▼───────────────────────────────────────┐
│  3. PROMPT ENGINE (src/persona/prompts.py)                       │
│     Combines a fixed persona description with randomized knobs   │
│     (tone, structure, personalization) and explicit anti-bot     │
│     humanization instructions; sends to the LLM provider          │
└───────────────────────────┬───────────────────────────────────────┘
                            │
┌───────────────────────────▼───────────────────────────────────────┐
│  4. MEMORY / ANTI-REPETITION (src/persona/memory.py)              │
│     Tracks recent registers, phases, topics, and reply targets   │
│     to keep output varied over time                               │
└─────────────────────────────────────────────────────────────────┘
```

### Registers (replaces Mood)

The moment-to-moment emotional key. Colors word choice, sentence structure, and which voice-bank
fragments get sampled.

| Register | Trigger | Notes |
|---|---|---|
| Delighted | Something elegant or beautiful (a proof, an artwork, a clever hack) | |
| Awestruck | Scale or the sublime (deep time, vast numbers, a staggering feat) | |
| Reverent | Quiet respect for mastery (a technique, a scholar, a craft tradition) | |
| Wistful | Loss or nostalgia (lost libraries, deprecated tech, extinct art forms) | |
| Amused | Wry humor, spotted absurdity or irony | |
| Restless | An itchy, half-formed question it can't stop poking at | Often produces threads |
| Provoked | A bad take, flattened history, hype without substance | Highest-risk tone, needs care |
| Giddy | Something *just* dropped and it can't contain itself | Time-sensitive; pairs with Breakthrough phase |

### Phases (replaces MarketPsychologyPhase)

The macro shape of today's signal pool — decides what *kind* of content to prioritize, not
the tone of any one post.

| Phase | Meaning | Growth relevance |
|---|---|---|
| Convergence | Multiple signals across domains rhyme with each other | Highest-leverage — thread material |
| Breakthrough | Something genuinely new just dropped | High — being early matters |
| Contested | A live disagreement worth having a take on | Reply-bait, higher engagement, higher risk |
| Anniversary | A "this day in history" anchor with a modern echo | Reliable evergreen fallback |
| Excavation | Surfacing something old/obscure and making the case for it | Signature "polymath" move; builds authority |
| Quiet | Nothing pressing | Draw from voice bank / archive rather than force it |

Convergence and Breakthrough should be weighted higher in signal-scoring, since they're the
phases most likely to produce genuinely shareable content for a growth-focused account.

## Tech Stack (with rationale)

| Component | Choice | Rationale |
|---|---|---|
| Language | Python 3.11+ | Matches the proven reference architecture; rich ecosystem for both scraping (Selenium) and content-signal APIs (feedparser, arxiv, wikipedia-api) |
| Social automation | Selenium + Chrome/ChromeDriver | Avoids the $200/mo X API write-access tier; same approach validated by the reference bots |
| Database | SQLite | Matches reference architecture; sufficient scale for a single-persona bot |
| LLM access | Provider-agnostic abstraction (`src/llm_provider.py`) | Core requirement — must support hosted (Claude) and self-hosted (local model via OpenAI-compatible endpoint) backends interchangeably |
| Content signals | Public/free APIs: arXiv, Wikipedia/Wikidata "On this day", Hacker News, museum open-data (Met, Rijksmuseum, Smithsonian) | No auth friction, no cost, sufficient signal diversity across all three domains |

## LLM Integration (provider-agnostic)

This is a first-class architectural requirement, not an afterthought (the reference repos
stub out multiple providers but only wire up Claude — TedKhao wires up the abstraction for
real from the start).

**Interface** (`src/llm_provider.py`):
```python
class LLMProvider(Protocol):
    def generate(self, prompt: str, system_prompt: str | None = None,
                 max_tokens: int = 1000, temperature: float = 0.7) -> str: ...
```

**Concrete adapters**:
- `AnthropicProvider` — Claude, used for initial development and testing.
- `OpenAICompatibleProvider` — a generic adapter for anything speaking the OpenAI
  `/v1/chat/completions` protocol. This is the adapter used for the local-model path: point
  its `base_url` at the M4's Ollama endpoint (e.g. `http://<m4-hostname>.local:11434/v1`) and
  it behaves identically to calling any hosted API.

Provider selection happens via config (`.env` / `config.py`), never via code changes. Swapping
from Claude to a local model is a config edit.

### Long-term two-machine architecture

The eventual deployment target is two machines:

- **2014 MacBook Air** — the orchestrator. Runs the full bot: Selenium scraping/posting,
  the state engine, the voice bank, the prompt engine, the database. Treats the LLM as a
  remote service call, exactly like calling Claude's API today.
- **MacBook Air M4** — a thin inference server only. Runs a local model (via Ollama or
  equivalent) exposing an OpenAI-compatible endpoint on the local network. It does not run
  any persona logic — it only receives prompts and returns completions.

**Connection**: plain LAN via `.local` mDNS hostname (e.g. `m4-macbook.local:11434`). No VPN
or tunnel in v1 — both machines are assumed to share a local network. This is a deliberate
simplicity choice; revisit only if the machines need to operate on separate networks.

This split means the persona logic is entirely hardware-agnostic: it always talks to "a
provider," and which machine (or hosted API) answers that call is purely a config detail.

## Data Models / Schema

SQLite, mirroring the reference architecture's proven table shapes with content adapted to
signals instead of market data.

```sql
-- Raw content pulled from all signal sources
CREATE TABLE signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,           -- 'arxiv', 'wikipedia_otd', 'hackernews', 'met_museum', etc.
    domain TEXT NOT NULL,           -- 'technology', 'history', 'arts'
    title TEXT NOT NULL,
    summary TEXT,
    url TEXT,
    novelty_score REAL,             -- computed at ingestion
    fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
    used_at TEXT                    -- null until consumed by a post
);

-- State engine output history (replaces predictions/technical_indicators)
-- phase is nullable (not NOT NULL): the reply path (select_register_for_reply) only ever
-- produces a Register -- there is no Phase concept for a reply -- so a reply-triggered row
-- has no phase to record. The post-generation path (select_phase_register_and_signal) always
-- has both and populates phase normally. See docs/SCAFFOLDING.md Phase 5.
CREATE TABLE state_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    register TEXT NOT NULL,
    phase TEXT,
    triggering_signal_id INTEGER REFERENCES signals(id),
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Original posts made
CREATE TABLE posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_text TEXT NOT NULL,
    register TEXT NOT NULL,
    phase TEXT NOT NULL,
    signal_id INTEGER REFERENCES signals(id),
    posted_at TEXT DEFAULT CURRENT_TIMESTAMP,
    engagement_likes INTEGER DEFAULT 0,
    engagement_replies INTEGER DEFAULT 0,
    engagement_reposts INTEGER DEFAULT 0,
    engagement_checked_at TEXT
);

-- Replies to others (dedup + tracking, same purpose as replied_posts in reference repos)
CREATE TABLE replied_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id TEXT UNIQUE NOT NULL,       -- external post ID
    post_author TEXT,
    post_content TEXT,
    reply_content TEXT,
    register TEXT,
    replied_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

## API Design

No public-facing API in v1 — TedKhao is a background process, not a service. "API design"
here refers to internal module boundaries and external integrations:

- **Signal ingestion modules** (`src/signals/*.py`) each implement a common `fetch() -> list[Signal]`
  interface, so adding a new source (e.g. a fourth arts API) never touches the state engine.
- **X/Twitter integration** (`src/signals/timeline_scraper.py`, `src/bot.py`) — Selenium-based,
  session cookies persisted between runs to minimize re-login friction.
- **LLM integration** — see LLM Integration section above.

## Auth & Permissions

- **X/Twitter**: Selenium browser automation with stored session (`TWITTER_USERNAME` /
  `TWITTER_PASSWORD` in `.env`), same approach as the reference bots. No official API keys
  needed for v1.
- **Content signal APIs**: arXiv, Wikipedia/Wikidata, and Hacker News require no auth. Met
  Museum and Rijksmuseum APIs are free/keyless; Smithsonian Open Access requires a free API
  key (`SMITHSONIAN_API_KEY`).
- **LLM providers**: `ANTHROPIC_API_KEY` for Claude; no credential needed for the local
  OpenAI-compatible endpoint (LAN-only, not exposed externally).
- Single-user system — no roles, no multi-tenant permission model needed.

## Deployment & Infrastructure

- **v1 / development**: runs anywhere Python 3.11+ and Chrome are available (current dev
  machine), backed by Claude.
- **Long-term target**: 2014 MacBook Air running the orchestrator continuously (launchd job
  or simple `caffeinate`-wrapped process), with the MacBook Air M4 running the local model
  server (Ollama) on the same LAN.
- No containerization, no cloud hosting, no CI/CD pipeline required for this project's scale.
- **Known constraint to watch**: the 2014 Air is old and RAM-limited; running headless Chrome
  for scraping alongside the rest of the bot process should be monitored for memory pressure
  once deployed there. Not a blocker for v1 (which runs on the dev machine), but worth testing
  early once the 2014 Air becomes the target.

## Open Questions / Future Considerations

- Exact novelty/significance scoring formula for the signal pool (analogous to the reference
  repos' mood-scoring weights) — will likely need tuning once real signal data is flowing.
- Whether engagement metrics (likes/replies/reposts) should feed back into register/phase
  weighting over time (a growth-oriented feedback loop) — flagged as a v2 idea, not v1 scope.
- Whether to eventually add the official X API as an alternative to Selenium if reliability
  becomes an issue at scale.
- Whether the local-model path (once working) fully replaces Claude, or the system keeps
  Claude as a fallback/comparison provider indefinitely.
