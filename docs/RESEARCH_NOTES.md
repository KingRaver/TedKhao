# Research Notes — Source Architecture (defi / karma)

Detailed findings from reverse-engineering [KingRaver/defi](https://github.com/KingRaver/defi)
and [KingRaver/karma](https://github.com/KingRaver/karma) — the two repos TedKhao's
personality-engineering pattern is adapted from. `docs/SPEC.md` states the conclusions drawn
from this research; this file is the underlying evidence, so the "why" survives independent of
this conversation.

**Licensing note**: `defi`'s `LICENSE.md` is Proprietary; `karma`'s is a custom "Educational
and Research Use License." Both restrict commercial use and neither's phrase-bank/prompt text
should be reused verbatim in TedKhao — only the architectural *pattern* is being reused, per
`CLAUDE.md`'s framing. Line numbers below reflect a `git clone --depth 1` taken during this
research session; re-verify against the live repos if this matters again later, since both are
described in their own READMEs as under active development.

## What the two repos actually are

Not two different bots — the same author's project ("Tokenetics") at two points in its
evolution, near-identical file structure and module names in both:

`bot.py`, `config.py`, `database.py`, `llm_provider.py`, `mood_config.py`, `meme_phrases.py`,
`content_analyzer.py`, `reply_handler.py`, `timeline_scraper.py`, `coingecko_handler.py`,
`multi_chain_manager.py`, `prediction_engine.py`, the `technical_*.py` stack, and a shared
`utils/` (`browser.py`, `logger.py`, `sheets_handler.py`).

Line-count comparison (via `wc -l`, both repos' `src/`):

| File | `defi` | `karma` |
|---|---|---|
| `mood_config.py` | 142 | 2,346 |
| `meme_phrases.py` | 2,136 | 10,934 |
| `content_analyzer.py` | 2,401 | 2,401 (unchanged) |
| `reply_handler.py` | 2,252 | 2,902 |
| `llm_provider.py` | 906 | 1,065 |
| `timeline_scraper.py` | 2,596 | 5,106 |
| `bot.py` | 9,546 | 10,545 |

`karma` is `defi` after a major expansion of the mood/psychology and phrase-bank layers
specifically — the reply-generation prompt itself is byte-identical between the two (see
below), which is the clearest signal that voice engineering and mood/content engineering are
separable concerns in this architecture.

## Layer 1 — Mood engine

- `defi/src/mood_config.py:7-12` — `Mood` enum, 5 values (`BULLISH`, `BEARISH`, `NEUTRAL`,
  `VOLATILE`, `RECOVERING`).
- `defi/src/mood_config.py:26-90` — `determine_advanced_mood()`: weighted point-scoring across
  price change, volatility, volume, optional social sentiment/funding-rate/liquidation-volume
  inputs; returns the highest-scoring `Mood`.
- `karma/src/mood_config.py:5` — module docstring literally: "Enhanced Billionaire Algorithmic
  Trading Guru Mood Configuration System."
- `karma/src/mood_config.py:39-52` — `Mood` enum expanded to 10 values (adds `EUPHORIC`,
  `CAPITULATION`, `ACCUMULATION`, `DISTRIBUTION`, `MANIPULATION`).
- `karma/src/mood_config.py:55-72` — `MarketPsychologyPhase` enum, 12 values
  (`STEALTH_ACCUMULATION`, `INSTITUTIONAL_FOMO`, `RETAIL_EUPHORIA`, `SMART_MONEY_EXIT`,
  `PANIC_SELLING`, `DESPAIR_CAPITULATION`, `DIAMOND_HANDS_FORMATION`, `WHALE_MANIPULATION`,
  `ALGORITHM_WARS`, `MARKET_MAKER_GAMES`, `LIQUIDITY_CRISIS`, `GAMMA_SQUEEZE`) — this is the
  direct ancestor of TedKhao's Phase taxonomy (`docs/SPEC.md`'s Convergence/Breakthrough/
  Contested/Anniversary/Excavation/Quiet).
- `karma/src/mood_config.py:398-1365` (approx.) — real quant math backing the mood engine:
  `calculate_fear_greed_index`, `calculate_sharpe_ratio`, `calculate_market_regime`,
  `calculate_volatility_surface`, `calculate_risk_parity_weights`,
  `calculate_maximum_drawdown`, `calculate_kelly_criterion`, `detect_algorithmic_signals`,
  `analyze_whale_behavior`, `detect_market_manipulation`. The math exists largely to *earn* an
  institutional-grade authoritative voice, not only to trade — worth remembering since TedKhao
  has no equivalent domain-authority signal yet (no analog to "the Sharpe ratio backs up this
  post's confidence").
- `karma/src/mood_config.py:1373` — `determine_advanced_mood()` in karma returns
  `Tuple[Mood, float]` (mood + confidence score), vs. defi's bare `Mood` return — confidence
  scoring was added between versions.

## Layer 2 — Static voice bank (`meme_phrases.py`)

`defi/src/meme_phrases.py:55-229` — `MEME_PHRASES` dict keyed by mood
(bullish/bearish/neutral/volatile/recovering/euphoric/capitulation/uncertain/fomo/fear), each
a flat list of hand-written phrases, randomly sampled and `.format()`-interpolated with a
token/chain name.

Beyond the core `MEME_PHRASES` dict, `defi/src/meme_phrases.py` defines ~20 more topic-keyed
phrase dicts in sequence (line numbers approximate, same file): `TIME_CONTEXT_PHRASES` (232),
`MARKET_CYCLE_PHRASES` (292), `MARKET_PSYCHOLOGY_PHRASES` (352), `TOKEN_MEME_PHRASES` (465),
`VOLUME_PHRASES` (559), `MARKET_COMPARISON_PHRASES` (623), `SMART_MONEY_PHRASES` (675),
`TECHNICAL_ANALYSIS_PHRASES` (727), `DEFI_PHRASES` (787), `NFT_PHRASES` (839),
`MEME_CULTURE_PHRASES` (931), `REGULATORY_NEWS_PHRASES` (983), `SENTIMENT_AMPLIFIERS` (1035),
`AUDIENCE_TEMPLATES` (1064), `REPLY_TEMPLATES` (1103), `TOKEN_COMPARISON_PHRASES` (1143),
`AI_PHRASES` (1213), `QUANTUM_PHRASES` (1277), `BLOCKCHAIN_TECH_PHRASES` (1341), `ML_PHRASES`
(1405), `AR_VR_PHRASES` (1469), `TECH_INTEGRATION_PHRASES` (1533).

`karma/src/meme_phrases.py` follows the identical pattern at ~5x the length (10,934 lines) —
same structure, far more coverage per category, no new architectural idea.

**TedKhao's equivalent**: `src/persona/voice_bank.py`. Currently a few dozen fragments across
8 registers (see `VOICE_GUIDE.md`) — a meaningful start per the "models need concrete material,
not just rules" lesson below, nowhere near this scale, and shouldn't need to be — TedKhao
leans more on the prompt engine (Layer 3) generating fresh text than defi/karma do.

## Layer 3 — LLM prompt engineering

**The core reply prompt is identical in both repos, unchanged across the entire expansion
described above:**

- `defi/src/reply_handler.py:321-337`
- `karma/src/reply_handler.py:459-484`

Both read (verbatim): *"You are an intelligent, witty crypto/market commentator replying to
posts on social media... sound like a real person, not an automated bot... not appear overly
promotional or financial-advice-like... vary your response style to avoid sounding
repetitive."* This is the strongest evidence in the whole codebase that voice/prompt
engineering and mood/content engineering are genuinely separable layers — one didn't change
at all while the other grew 5x.

- `defi/src/reply_handler.py:707-779` — `_select_reply_tone()`: a 10-item tone pool
  (`humorous, analytical, enthusiastic, skeptical, educational, playful, contrarian, curious,
  impressed, neutral`), contextually biased by detected market topic (bearish topic →
  skeptical/contrarian; bullish → enthusiastic/playful), with anti-repetition via excluding
  `self.recent_tones[-3:]`. **This is the direct model for
  `src/persona/state.py`'s `select_register_for_reply()` and its `_TOPIC_REGISTER_AFFINITY`
  table in TedKhao.**
- `defi/src/bot.py:~2150-2260` — the original-post content-generation prompt builder: crosses
  `content_type` (opinion / news_analysis / future_prediction) × `tone` × `structure` ×
  `personalization` (`personal_experience`, `question`, `comparison`, `anecdote`,
  `disagreement`, `surprise`, `recent_insight`) × `audience_level`, closing with explicit
  humanization instructions (paraphrased, same section): *vary sentence structure; avoid
  formulaic or repetitive phrasing; sound like a genuine human perspective, not corporate or
  academic content; include subtle indicators of authentic writing (slight tangents, specific
  examples).* TedKhao has no equivalent yet — `docs/SCAFFOLDING.md` Phase 4 (Original Post
  Generation) is exactly this, still unbuilt.

## Layer 4 — Perception / reply targeting

- `defi/src/content_analyzer.py` (2,401 lines, unchanged in karma) — sentiment classification,
  tech-topic detection, question/opinion detection, conversation threading, an engagement/
  context score used to prioritize which posts are worth replying to
  (`prioritize_posts()`), and duplicate-reply prevention (`filter_already_replied_posts()`
  against a `replied_posts` DB table).
- `defi/src/timeline_scraper.py` — Selenium-based timeline scraping this feeds on; grew from
  2,596 to 5,106 lines in karma, mostly broader token/topic coverage rather than new mechanism.

**TedKhao's equivalent**: `src/engagement/content_analyzer.py` + `reply_handler.py` — currently
much lighter (regex/keyword-based topic tagging only), matching the "start smaller, expand as
real output reveals gaps" approach rather than porting the reference implementation's full
scope up front.

## Database schema (for reference — TedKhao's is in `docs/SPEC.md`, adapted from this)

From `defi/ARCHITECTURE.md`'s documented schema: `market_data`, `predictions`,
`technical_indicators`, `replied_posts`, `trades`, `positions` tables. TedKhao's
`docs/SPEC.md` schema (`signals`, `state_history`, `posts`, `replied_posts`) is a direct
adaptation — `replied_posts` in particular is structurally almost identical, just without the
crypto-specific `sentiment` field's market framing.

## Why this matters for TedKhao specifically

The single most load-bearing finding from this research: **the four layers are independently
variable.** karma proves you can hold the prompt/voice layer completely fixed while radically
expanding the mood-taxonomy and phrase-bank layers underneath it, and vice versa is equally
true. That's the justification for TedKhao's own module boundaries in `docs/STRUCTURE.md` —
`persona/state.py`, `voice_bank.py`, and `prompts.py` are deliberately separate files, not
because it's tidy, but because the reference architecture demonstrated each one can evolve on
its own schedule without the others needing to change.
