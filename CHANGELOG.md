# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- RC-110 (partial -- offline portion only): new `tests/manual_test_integrated_regression.py`
  exercises resident multi-cycle driver reuse, a real version-0-to-2 database migration,
  publication-state transitions, repeat-source exclusion (RC-107), and per-operation failure
  isolation (RC-109) together in one continuous scenario against a single shared fake-driver
  `BrowserSession` and `PersonaMemory`, rather than in each earlier phase's own isolated
  fixture: a legacy-schema database is seeded and migrated for real via `PersonaMemory`
  construction (not a throwaway copy); three `bot.run_post_cycle()`/`run_reply_cycle()` cycles
  then confirm an original post and two replies, skip a repeat post source and two
  already-held replies, retry a cleanly-failed reply, isolate one candidate's ordinary publish
  failure from an unrelated candidate's success, and recover from one diagnosed
  `InvalidSessionIdException` (evidence-of-expiry re-check, one bounded relaunch, immediate
  reuse of the relaunched driver for the very next action) -- with every publication-state
  transition and the original legacy row confirmed to survive a simulated process restart
  (a fresh `PersonaMemory` against the same database). Wired into `tests/run_offline.py`.
  `docs/STRUCTURE.md` updated for this file and the previously-undocumented
  `tests/manual_test_failure_isolation.py` (RC-109); `README.md`'s Verification section
  extended to cover RC-105 through RC-110. Remaining RC-110 checklist items (documentation
  parity already covered by this entry; the live-validation procedure, its explicit
  authorization, and the authorized live check itself) are tracked separately in
  `docs/REVIEW_CHECKLIST.md`'s Phase 10 -- not implied done by this entry.
- RC-109: `bot.run_post_cycle()`/`run_reply_cycle()` now isolate a single operation's failure
  instead of letting it abort the rest of the cycle -- a `generate_post()`/`generate_reply()`
  `GenerationError` (RC-105) is caught and turned into an `outcome: "generation_failed"` result,
  and a `publish()` (RC-102/RC-104) exception other than `SessionPaused` is caught and turned
  into `outcome: "publish_failed"` with a sanitized (type-name-only, never raw exception text)
  detail; either way the durable `failed`/`uncertain` publication state `publish()` already
  writes before re-raising is unaffected, so isolating the exception in `bot.py` loses no
  outcome state. `SessionPaused` is deliberately excluded from this isolation in both functions
  -- a shared-session authentication challenge or account restriction still stops every
  subsequent X action this cycle, exactly as RC-103 established, verified directly: a third,
  otherwise-eligible reply candidate is never attempted once a second candidate's re-checked
  auth raises `SessionPaused`. New `bot.summarize_cycle()` buckets a completed cycle's post +
  reply results into confirmed/draft/failed/skipped/uncertain, each entry carrying a target/
  source identifier and an outcome/detail with no possible credential or cookie field;
  `run_cycle()` logs a one-line sanitized summary count. No new retry loop was added -- existing
  bounded-recovery mechanisms (RC-103's crash relaunch, RC-105's generation attempts) are
  unchanged. New `tests/manual_test_failure_isolation.py` covers a failed post generation/publish
  not blocking independent replies, a failed reply generation/publish followed by a successful
  candidate, a mid-cycle session-paused challenge stopping every subsequent reply, and
  `summarize_cycle()`'s bucketing/sanitization; wired into `tests/run_offline.py`. Two
  `tests/manual_test_publication.py` cases that asserted the pre-RC-109 propagate-the-exception
  contract were updated to assert the new isolated-outcome contract instead -- the durable state
  they verify (publication row status, held/unheld target, driver lifecycle) is unchanged, only
  the observation mechanism.
- RC-108: `persona.state.select_phase_register_and_signal()` now returns a `convergence_partner`
  signal (the other half of the rhyming pair) instead of silently dropping it, and
  `persona.prompts.build_post_prompt()` grounds a Convergence prompt in both signals -- raising
  if the partner is missing rather than emitting a half-grounded prompt, which
  `engagement.post_handler.generate_post()` now catches one layer up and turns into an explicit
  `"skipped": "convergence_missing_supporting_signal"` result instead of crashing the post
  cycle. New `database.get_last_confirmed_post()`/`PersonaMemory.last_confirmed_post()` supply
  the most recently *confirmed* original post's text, which gates a new "callback to an earlier
  post" structure -- only offered, and only ever grounded in real (never fabricated) content,
  when that post exists; `POST_STRUCTURE_POOL`'s comparison/quiet-fact options are likewise
  excluded whenever there's no signal to supply the fact they'd need. Thread-opening ("a short
  thread (2-4 posts)...") was removed from `POST_STRUCTURE_POOL` outright -- the single-post
  pipeline has no way to publish the follow-up posts it would set up; full thread publishing is
  deferred to its own tracked scope. New `tests/manual_test_prompt_grounding.py` covers
  Convergence grounding/contract-violation handling, callback reachability with and without a
  confirmed post, no-signal structure restriction, and an end-to-end confirmed-history case;
  wired into `tests/run_offline.py`. `VOICE_GUIDE.md`'s structure-pool section updated to match.
  New `docs/VOICE_TRIALS.md` records a model-backed trial (`deepseek-coder-v2:16b`, real Ollama
  calls): Convergence and callback grounding both worked as designed, but the no-signal path
  still fabricated a specific historical claim despite its explicit anti-fabrication
  instruction -- `CLAUDE.md`'s existing open voice-quality item is reconfirmed, not resolved.
- RC-107: `signals.base` gained `source_key()` (canonical URL, falling back to
  `"<source>:<title>"` for a source that doesn't set one) and `content_fingerprint()`
  (normalized title). Schema version 2 adds `publications.source_url`/`source_fingerprint`,
  populated only for original posts by `PersonaMemory.save_draft()` and migrated via
  `ALTER TABLE` against an existing version-1 database (legacy rows keep both NULL rather than
  a guessed backfill, matching RC-102's own legacy-migration precedent).
  `database.get_covered_sources()`/`PersonaMemory.covered_source_keys()` (queried fresh each
  call, since the window is time-relative) report sources confirmed within the new
  `config.SOURCE_COVERAGE_WINDOW_HOURS` (default 72h) or held by an unresolved
  attempted/uncertain attempt regardless of window -- draft and failed sources are never held,
  so a dry run or a source-row insertion alone never counts as coverage, mirroring
  `reply_is_held()`'s held-status reasoning. `engagement.post_handler.generate_post()` filters
  the incoming pool against this before `select_phase_register_and_signal()` runs, and returns
  an explicit `"skipped": "all_candidate_sources_recently_covered"` result -- generating and
  persisting nothing -- when every candidate is covered, instead of silently reselecting an
  already-posted source; `bot.run_post_cycle()` handles the skip. A signal whose title changes
  since it was last covered gets a new `content_fingerprint` and becomes eligible again even
  inside the window, distinguishing a materially updated item from a repeat. New
  `tests/manual_test_source_coverage.py` covers repeated fetches, a process restart, dry runs,
  uncertain holds, failed non-holds, an expired window, missing-URL fallback keys, and a
  materially updated same-URL item; wired into `tests/run_offline.py`.
  `tests/manual_test_publication.py`'s copied-legacy-migration case was updated for the new
  `PRAGMA user_version == 2` and to assert legacy rows have no source identity.
- RC-106: `signals.base.Signal` gained `novelty_evidenced: bool = False`, set `True` only by
  `arxiv_feed.py`/`hackernews_feed.py` (whose fetch order is real freshness/trending evidence)
  and left `False` by `history_today.py`/`arts_feed.py`/`timeline_scraper.py` (whose order
  isn't a significance ranking). `persona.state.select_phase_register_and_signal()` now: (1)
  breaks ties on `novelty_score` with a seeded random choice over the tied signals
  (`_select_top_signal()`) instead of list order, so arxiv no longer wins every tie just for
  being fetched first; (2) requires `novelty_evidenced` for Breakthrough, so a first-ranked
  historical event or museum object can't become a breakthrough solely because rank 0 scores
  1.0 -- fixes the review's "history-only pool incorrectly selected Breakthrough" finding; (3)
  requires two different-domain high-novelty signals to share significant vocabulary
  (`_signals_rhyme()`/`_find_convergent_pair()`) for Convergence, instead of firing on domain
  count alone -- unrelated high-novelty signals now fall through to a supported single-signal
  phase. Contested remains explicitly unreachable, unchanged. New
  `tests/manual_test_state_selection.py` covers tied top scores (order-independence and
  cross-seed fairness), history-only and arts-only top-rank pools, evidenced-vs-unevidenced
  Breakthrough eligibility, unrelated vs. related cross-domain Convergence candidates, and the
  empty pool; wired into `tests/run_offline.py`. `tests/manual_test_posts.py`'s scenario
  fixtures were updated to keep demonstrating the phase each is named for under the new rules.
- RC-105: `llm_provider.py` gained `GenerationError`, raised by `AnthropicProvider.generate()`
  and `OpenAICompatibleProvider.generate()` when a response is missing/null/malformed (empty
  `content`, null `text`/`content`, missing `choices`, a non-JSON body) instead of leaking a
  bare `IndexError`/`KeyError`/`AttributeError`/`ValueError`. `engagement.reply_handler`'s new
  `_generate_nonempty()` (shared with `post_handler.py` the same way `_sentence_aware_truncate`
  already is) retries initial generation up to the new `config.REPLY_GENERATION_ATTEMPTS`/
  `POST_GENERATION_ATTEMPTS` (2 each) on empty-after-strip text or a caught `GenerationError`,
  and raises rather than returning empty text once attempts are exhausted --
  `generate_post()`/`generate_reply()` call this before `memory.save_draft()`, so a failure
  never persists a draft or holds a reply target. Fixed both `_ensure_length()` shortening
  loops (reply and post) to stop accepting an empty/malformed shorten attempt as valid output
  (`len("") <= max_chars` previously let that through, matching the review's "empty post
  accepted and persisted" finding) -- a wasted attempt now leaves the last known-valid
  candidate in place for the existing `_sentence_aware_truncate()` fallback instead. New
  `tests/manual_test_generation_validation.py` covers both providers' malformed-response
  handling plus whitespace-only, provider-error, bounded-recovery, empty-shorten, and the
  pre-existing overlength-truncation cases; wired into `tests/run_offline.py`.
- RC-104: `utils.browser.post_tweet()`/`post_reply()` now observe X's actual response after
  the submit click instead of treating a completed click as success --
  `_await_submission_outcome()` waits (bounded) for either a "sent" toast carrying the new
  post's status permalink (`confirmed`, with `external_id`/`external_url` parsed from it) or
  an error/confirmation dialog (`failed`, with its message as `detail`); a toast with no
  permalink or no evidence at all within the bound resolves to `uncertain`, never `confirmed`
  or `failed`, and an exception during/after the click propagates untouched rather than being
  reported as any outcome -- `driver.quit()` is never called, so the shared `BrowserSession`
  (RC-103) stays open. `PublicationOutcome` moved from `engagement/publication.py` into
  `utils/browser.py` (the layer that now determines it) and is re-exported from
  `engagement.publication` for existing callers. New `tests/manual_test_browser_confirmation.py`
  (fake-driver, no real Chrome) covers success, rejection, timeout, and crash-after-click;
  wired into `tests/run_offline.py`. Real X selectors/confirmation behavior against the live
  DOM remain unverified pending RC-110's explicitly authorized live check.
- RC-103: `utils.browser.BrowserSession`, the single ownership boundary for one Chrome
  WebDriver across a whole `bot.py` process -- launched once, reused by timeline scraping,
  posting, and replies, and closed only on deliberate shutdown or a diagnosed crash
  (`InvalidSessionIdException`, bounded to one relaunch-and-retry per call via
  `bot._with_crash_recovery()`). A file lock on `data/browser_profile/` refuses a second
  concurrent process. Authentication is checked at session startup and after
  `flag_possibly_expired()`, never before every action; a headless session with no valid
  login raises `SessionPaused` instead of retrying `log_in()` automatically --
  `resume_manual_login()` opens a visible Chrome window for a human to clear a login/
  verification challenge, rate limit, or account warning, then hands back to the resident
  loop. `timeline_scraper.fetch()` and `engagement.publication.publish()` now take an
  injected session instead of creating and quitting their own driver per call; `bot.py`'s
  resident loop shares one session across every cycle and `--once` closes it with the
  process. New `tests/manual_test_browser_session.py` (fake-driver, no real Chrome) covers
  one launch across multiple cycles, shared driver identity, no per-action `quit()`, bounded
  crash recovery, and clean shutdown on interruption; wired into `tests/run_offline.py`.
- RC-102: transactional publication drafts, durable attempts/outcomes and event history,
  confirmed-reply deduplication, restart-safe uncertainty/legacy holds, and schema-version-1
  migration preserving historical rows. Click-only browser returns remain uncertain pending
  RC-104 confirmation. Added offline lifecycle/migration regressions and backup/rollback docs.
- RC-101: isolated voice-review databases with explicit `--review-db` retention, production
  `generate_post()` reuse, and `tests/run_offline.py` covering persistence, cycles, and
  database isolation without credentials, network access, or browser launches.
- `docs/REVIEW_CHECKLIST.md`: actionable review remediation tracker RC-101–RC-110 covering
  all eight review findings, persistent browser/authentication handling, dependencies,
  acceptance criteria, baseline evidence, and separate offline/live verification. Linked
  from the scaffolding and structure docs; current remediation status lives in its work register.
  Numbered Phases 1–10 map to the stable RC IDs, with explicit dependencies and a
  file-specific `/phase-runner` invocation.
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

- Phase 6 (X/Twitter Integration): `src/utils/browser.py` -- Selenium WebDriver setup
  (`get_driver()`), a persistent Chrome profile (`data/browser_profile/`, gitignored) so a
  session survives between runs, `is_logged_in()`/`log_in()`/`ensure_logged_in()` reading
  `config.TWITTER_USERNAME`/`TWITTER_PASSWORD`, and `post_tweet()`/`post_reply()`.
  `src/signals/timeline_scraper.py`: `fetch() -> list[Signal]`, the same interface every
  other `signals/*.py` module implements -- scrapes the home timeline and reuses
  `engagement.content_analyzer.analyze_post()`'s `domain_guess` for domain classification
  instead of duplicating keyword logic, dropping posts that guess `'general'`. New
  `tests/manual_test_browser.py` -- deliberately calls only the read-only `is_logged_in()`,
  never `log_in()`/`post_tweet()`/`post_reply()`, since those touch a real account. Added
  `selenium` to `requirements.txt`. Project dependencies now install into an isolated `venv/`
  (gitignored) instead of the global Python environment. The `chromedriver` (139.x) vs.
  installed Chrome (152.x) mismatch that previously blocked `manual_test_browser.py` at
  driver launch is resolved: the stale `/usr/local/bin/chromedriver` symlink (shadowing
  Selenium Manager's own version-matched download) was renamed aside, letting Selenium
  Manager auto-download and cache a matching driver. `get_driver()`/`is_logged_in()` are now
  verified against live Chrome and live `x.com/home`. **Still unverified**:
  `TWITTER_USERNAME`/`TWITTER_PASSWORD` remain unset in `.env`, so `log_in()`, the
  authenticated timeline scrape, and posting have no live verification yet. See
  `docs/SCAFFOLDING.md` Phase 6 for what's left to actually confirm working.

- Phase 7 (Orchestration): `src/bot.py` -- thin orchestrator tying signals -> state engine ->
  persona -> engagement -> database -> posting into one cycle, plus a CLI (`--once`, `--live`,
  `--interval-minutes`, `--max-replies`). `fetch_all_signals()` fetches the four domain
  sources and one timeline fetch shared between post-generation and reply-target discovery.
  `run_reply_cycle()` extracts author handle + post id from `timeline_scraper.py`'s
  `x.com/<handle>/status/<id>` permalinks (`_parse_x_post_url()`) and skips already-replied
  candidates via `PersonaMemory.has_replied()`. New `src/engagement/post_handler.py`
  (`generate_post()`) -- the original-post equivalent of `reply_handler.generate_reply()`,
  the module `tests/manual_test_posts.py` and prior phases' notes already pointed at as
  deferred here. New `config.CYCLE_INTERVAL_MINUTES` (default 240, ~6 cycles/day) and
  `REPLY_MAX_PER_CYCLE` (default 3). New `config.LIVE_POSTING_ENABLED` (default `false`) --
  live publishing requires an explicit opt-in and is refused (falls back to dry-run with a
  logged warning) if `TWITTER_USERNAME`/`TWITTER_PASSWORD` aren't set. New
  `tests/manual_test_bot_cycle.py`: plain-assert harness against a fake, no-network
  `LLMProvider` and a temp database, covering URL parsing, post/reply generation +
  persistence, `max_replies` capping, and already-replied dedup. Verified both by that
  harness and by a live `bot.py --once` run against `deepseek-coder-v2:16b` and the real
  `arxiv`/`history_today`/`hackernews`/`arts_feed` sources, inspecting the resulting SQLite
  rows directly. **Still unverified**: the reply cycle's live-posting path and
  reply-candidate discovery against a real timeline, for the same reason as Phase 6 --
  `TWITTER_USERNAME`/`TWITTER_PASSWORD` remain unset in `.env`.

### Changed
- Doc freshness pass after RC-101-104 merged to `main`: `README.md`, `docs/PUBLICATION_MIGRATION.md`,
  and `docs/SPEC.md` still described RC-104's confirmation behavior as future work; corrected
  to describe what `utils.browser.post_tweet()`/`post_reply()` actually do now. `docs/STRUCTURE.md`'s
  file tree was missing several real `docs/`/`tests/` files (including the new RC-104 test) and
  listed Phase 9 test files that were never created; brought in line with the actual repo.
  `CLAUDE.md` never mentioned `docs/REVIEW_CHECKLIST.md` -- the active post-launch remediation
  tracker -- in its doc-reading order or re-entry checklist; added it to both, and clarified
  that its "Current Status" section covers only the original build, not remediation.
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
- `PersonaMemory`'s `db_path` wasn't threaded through to the direct `database.insert_signal()`/
  `insert_post()` calls in the new `engagement/post_handler.py` (Phase 7) -- a
  `PersonaMemory(db_path=...)` instance's generated posts/signals would have silently landed
  in `config.DATABASE_PATH`'s default database instead of the one `memory` was actually
  constructed against. Fixed by adding a `PersonaMemory.db_path` property and threading it
  through; caught by `tests/manual_test_bot_cycle.py` before this ever ran against the real
  database.

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
