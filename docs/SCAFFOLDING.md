# TedKhao — Phased Build Checklist

Verified against the actual repo state (file inventory + test runs), not against what
`docs/SPEC.md` describes on paper. Checked items have been built *and* observed working;
unchecked items may be designed in SPEC.md/STRUCTURE.md but have no code yet.

Use with `/phase-runner` to implement one phase at a time, verified against real commands.

## Active review remediation

The [Code Review Remediation Checklist](REVIEW_CHECKLIST.md) tracks findings RC-101–RC-110,
including publication confirmation, persistent browser sessions, source selection, and test
isolation. Consult its work register for current remediation status. The historical phase checks below describe
build progress, not closure of these review findings or readiness for unattended publishing.

---

## Phase 1 — Persona Engine ✅ done

- [x] `src/config.py` — env loading, provider selection, length constants
- [x] `src/llm_provider.py` — provider-agnostic abstraction (`AnthropicProvider`,
      `OpenAICompatibleProvider` for local/Ollama)
- [x] `src/persona/state.py` — Register (8) + Phase (6) enums, `select_register_for_reply()`
- [x] `src/persona/voice_bank.py` — expanded phrase bank, ~18 fragments per register
- [x] `src/persona/prompts.py` — persona description, few-shot examples per register,
      structure/personalization knobs, soft length target
- [x] `src/persona/memory.py` — anti-repetition tracking (in-memory)

## Phase 2 — Reply Pipeline ✅ done, ⚠️ voice quality still open

- [x] `src/engagement/content_analyzer.py` — keyword/pattern topic tagging
- [x] `src/engagement/reply_handler.py` — full pipeline: analyze → select register →
      build prompt → generate → enforce length
- [x] `tests/manual_test_replies.py` — fake-post harness for human review
- [x] Reply length correction — generation-based shorten loop (`_ensure_length`),
      truncation demoted to last-resort-only (PR #1, merged)
- [ ] **Voice quality validated across enough trials to trust it** — open per the
      "don't overgeneralize from one test" rule. Known issues seen in testing so far, not yet
      resolved: generic-assistant phrases still recur occasionally ("Absolutely
      breathtaking!"), register selection is unreliable on posts with no clear topic signal,
      and the "personal reaction" personalization knob has produced fabricated
      (non-factual) anecdotes on at least one local model. Needs more trials, possibly across
      more than one model, before calling this phase actually done.

## Phase 3 — Signal Ingestion ✅ done

- [x] `src/signals/base.py` — common `Signal` dataclass + `fetch()` interface
- [x] `src/signals/arxiv_feed.py` — technology domain (cs.AI/cs.CL/cs.LG, arXiv Atom API)
- [x] `src/signals/history_today.py` — Wikipedia "On this day" (REST API, history domain)
- [x] `src/signals/hackernews_feed.py` — technology domain (trending discussion, Firebase API)
- [x] `src/signals/arts_feed.py` — arts domain, Met Museum Open Access API only for now.
      Rijksmuseum and Smithsonian (also named in `docs/SPEC.md` for this domain) both need a
      registered API key that isn't in `.env` yet — add a sibling module following the same
      `fetch()` shape once those keys land, per CLAUDE.md's rule against asking for
      credentials in chat.
- [x] Signal-pool scoring — `select_phase_register_and_signal()` in `src/persona/state.py`,
      the original-post equivalent of `select_register_for_reply()`. First-pass heuristic
      over structural pool properties (novelty-score spread across domains, top signal's
      source), not semantic content. Contested phase is intentionally unreachable from this
      heuristic — detecting a live disagreement needs real topic/sentiment analysis the pool
      doesn't carry yet; the exact scoring formula remains the open question tracked in
      `docs/SPEC.md`.

All four sources verified live (real API calls, not mocked) plus the pool-scoring function,
including its empty-pool edge case — see smoke test run during this phase. No automated
`pytest` suite exists yet (that's Phase 9); this phase's own verification was a manual live
run, same spirit as Phase 2's `tests/manual_test_replies.py`.

## Phase 4 — Original Post Generation ✅ done, ⚠️ voice quality still open (same as Phase 2)

- [x] `persona/prompts.py` — `build_post_prompt()` equivalent to `build_reply_prompt()`,
      driven by a Phase + selected Signal instead of an incoming post. Also adds
      `POST_STRUCTURE_POOL`/`POST_PERSONALIZATION_POOL`/`POST_PHASE_NOTE` (post-specific
      knobs from VOICE_GUIDE.md, distinct from the reply pools since a post has no other
      person's message to react to). `POST_MAX_CHARS`/`POST_TARGET_CHARS` added to
      `config.py`, mirroring the reply constants (same platform limit).
- [x] Few-shot examples for original posts per Register — `FEW_SHOT_POST_EXAMPLES` in
      `prompts.py`, two per Register (16 total); three reuse VOICE_GUIDE.md's own canonical
      examples verbatim, the rest newly written to the same standard.
- [x] Manual test harness for original posts (`tests/manual_test_posts.py`), same spirit as
      the existing reply harness — six fake signal pools in (one per reachable Phase, plus an
      empty-pool case), read the output before automating. No `engagement/post_handler.py`
      exists yet (not planned until bot.py wires the full cycle together in Phase 7), so the
      harness does the analyze → select → build prompt → generate → enforce-length steps
      inline itself, reusing `engagement.reply_handler._sentence_aware_truncate` (already
      generic) rather than duplicating it.

Verified with a live run against the locally-configured `deepseek-coder-v2:16b` (`.env`'s
`LLM_PROVIDER=local`, confirmed reachable via `ollama list` + a live request first). All six
scenarios produced output; Phase selection matched `state.py`'s heuristic for each
(Convergence/Breakthrough/Anniversary/Excavation/Quiet/Quiet-via-empty-pool); every generated
post honored the `POST_MAX_CHARS` hard cap (171–275 chars observed); anti-repetition memory
(`recent_phases`/`recent_registers`) updated correctly across the run.

**New finding, not yet resolved**: `build_post_prompt()`'s no-signal branch explicitly
instructs the model not to invent a fact when there's no Signal to anchor to (guarding against
the fabrication risk already flagged in Phase 2). In this run, on the empty-pool scenario, the
local coding model did it anyway — fabricated a specific claim about Leonardo da Vinci's
notebooks. Per `qwen2.5-coder`/`deepseek-coder-v2` both being code-specialized and already
flagged as not representative of general-purpose voice quality (see "Local Model Testing
Notes" below), and per the standing "don't treat any single test run as a verdict" rule, this
one run doesn't settle whether the instruction is ineffective — but it's the same class of
issue Phase 2 already tracks as open, now confirmed to reach the no-signal post path too.
Rolls into Phase 2's open item rather than blocking Phase 4: the prompt-construction mechanism
itself is built and verified working; whether it reliably produces voice-quality, non-fabricated
output is the pre-existing cross-cutting open question, not something introduced by this phase.

## Phase 5 — Persistence ✅ done

- [x] `src/database.py` — SQLite schema from `docs/SPEC.md` (`signals`, `state_history`,
      `posts`, `replied_posts` tables). One deliberate deviation from the SPEC.md snippet:
      `state_history.phase` is nullable, not `NOT NULL` — the reply path
      (`select_register_for_reply`) only ever produces a Register, with no Phase concept for a
      reply, so a reply-triggered row has no phase to record. The post-generation path
      (`select_phase_register_and_signal`) always has both and populates phase normally. See
      `docs/SPEC.md`'s Data Models section, updated to match.
- [x] Wire `PersonaMemory` to persist across restarts instead of in-process-only —
      `persona/memory.py` now loads `recent_registers`/`recent_phases`/`replied_post_ids` from
      the database on construction. New `record_state()`/`record_reply()` methods update the
      in-memory anti-repetition lists *and* write through to `state_history`/`replied_posts` in
      one call; the old `record_register()`/`record_phase()`/`mark_replied()` primitives remain
      for in-memory-only use.
- [x] Wire `reply_handler`/post-generation to log to `posts` / `replied_posts` —
      `engagement/reply_handler.py`'s `generate_reply()` now calls `memory.record_state()` +
      `memory.record_reply()`. No `engagement/post_handler.py` exists yet (still deferred to
      Phase 7's `bot.py` orchestration, per Phase 4's notes above), so
      `tests/manual_test_posts.py` — the harness that already inlines the post-generation
      pipeline for the same reason — was extended to persist the triggering `Signal` and the
      generated `Post` via `database.py` directly.

Verified with a live run against the locally-configured `deepseek-coder-v2:16b` (same setup as
Phase 4): `tests/manual_test_replies.py`'s 6 fake posts and `tests/manual_test_posts.py`'s 6
scenarios both ran end-to-end and were inspected directly in the resulting SQLite file —
`signals` rows got `used_at` set, `posts.signal_id` correctly referenced the triggering signal,
`state_history` correctly left `phase` NULL for reply-path rows and populated it for
post-path rows, and a freshly-constructed `PersonaMemory()` (simulating a process restart)
loaded the prior run's `recent_registers`/`replied_post_ids` correctly. A separate
`tests/manual_test_persistence.py` harness (plain asserts, no pytest suite yet — that's Phase
9) exercises the same claims deterministically against a fake, no-network `LLMProvider` and a
temp database, so this wiring can be re-checked without a live model.

## Phase 6 — X/Twitter Integration ⚠️ partially verified, blocked on credentials

- [x] `src/utils/browser.py` — Selenium WebDriver setup: `get_driver()` (headless Chrome with
      a persistent profile at `data/browser_profile/`, gitignored, so session cookies survive
      between runs per `docs/SPEC.md`'s Auth & Permissions), `is_logged_in()`. The
      `SessionNotCreatedException` blocker (`/usr/local/bin/chromedriver` 139.x vs. installed
      Chrome 152.x) is resolved: project dependencies now install into an isolated
      `venv/` (gitignored, matching the repo's existing convention) instead of the global
      Python environment — a prior ad hoc global `pip install` had bumped `urllib3` in a way
      that conflicted with an unrelated globally-installed `kubernetes` package; that's been
      reverted and the global environment is back to its original state. The stale
      `/usr/local/bin/chromedriver` symlink (which was shadowing Selenium Manager's own
      version-matched download — Selenium Manager detects a PATH mismatch but won't override
      it) was renamed aside to `chromedriver.bak-139` with Jeff's explicit go-ahead; the
      underlying Homebrew cask install is untouched, so this is trivially reversible. Selenium
      Manager now auto-downloads and caches a matching driver
      (`~/.cache/selenium/chromedriver/mac-arm64/152.0.7977.82/`). Verified:
      `venv/bin/python tests/manual_test_browser.py` passes (headless launch + navigate +
      quit), and a direct manual call to `is_logged_in()` against live `x.com/home` (no
      credentials configured) correctly returns `False` with no crash.
- [ ] `src/signals/timeline_scraper.py` — `fetch() -> list[Signal]`, the same interface every
      other `signals/*.py` module implements. Scrapes the home timeline; reuses
      `engagement.content_analyzer.analyze_post()`'s `domain_guess` for domain classification
      rather than duplicating keyword logic, dropping posts that guess `'general'` (Signal's
      domain is only ever `'technology'`/`'history'`/`'arts'` elsewhere in the codebase).
      Import-clean and wired to the confirmed `domain_guess` interface, but scraping a real
      timeline needs an authenticated session, which needs real credentials (next item) —
      still unverified end-to-end.
- [ ] Login/session handling — `utils/browser.py`'s `log_in()`/`ensure_logged_in()`, reading
      `config.TWITTER_USERNAME`/`TWITTER_PASSWORD` (`TWITTER_USERNAME`/`TWITTER_PASSWORD`
      still empty in this repo's `.env`). Genuinely unverified: needs real credentials added
      directly to `.env` (never pasted into chat, per `CLAUDE.md`) plus a deliberate,
      explicit go-ahead before running live against a real X account — a failed or
      flagged automated login has real consequences for that account.
- [ ] Actual posting (original posts + replies) — `utils/browser.py`'s `post_tweet()`/
      `post_reply()`. Implemented; deliberately never invoked by this phase's own test
      harness (`tests/manual_test_browser.py` only calls the read-only `is_logged_in()`) —
      posting is public and effectively irreversible, so it should run only when explicitly
      requested, never as part of an automated check. Unverified.

**Selector caveat**: `utils/browser.py`'s `data-testid`/CSS selectors are best-effort against
X's current web app DOM, not a public API contract — they can silently break if X changes its
DOM. `docs/SPEC.md`'s Non-Goals already accepts this risk in exchange for avoiding paid X API
access.

## Phase 7 — Orchestration ✅ done, ⚠️ reply-path live posting still blocked on credentials (same as Phase 6)

- [x] `src/bot.py` — thin orchestrator per `docs/STRUCTURE.md`'s design; ties signals →
      state engine → persona → engagement → database → posting into one cycle.
      `fetch_all_signals()` pulls the four domain sources plus one timeline fetch (shared
      between the post cycle's signal pool and the reply cycle's candidate discovery, so a
      cycle never launches Selenium twice); `run_post_cycle()` and `run_reply_cycle()` call
      the new `engagement/post_handler.generate_post()` /
      `engagement/reply_handler.generate_reply()` respectively, then optionally publish via
      `utils/browser.py`. Added `engagement/post_handler.py` (`generate_post()`) as the
      original-post equivalent of `reply_handler.generate_reply()` — this is the module
      `tests/manual_test_posts.py`'s docstring (Phase 4) and `docs/SCAFFOLDING.md`'s Phase
      4/5/6 notes already pointed at as deferred here, so `bot.py` itself stays thin instead
      of absorbing that logic inline. Reply-target discovery reads the author handle + post
      id back out of `timeline_scraper.py`'s `x.com/<handle>/status/<id>` permalinks
      (`bot._parse_x_post_url()`) rather than widening `signals.base.Signal` with an
      X-specific author field for one caller; malformed/non-status URLs are skipped.
      Already-replied signals are skipped via `PersonaMemory.has_replied()`.
      **Bug found and fixed during this phase**: `engagement/post_handler.py`'s direct
      `database.insert_signal()`/`insert_post()` calls weren't threading the owning
      `PersonaMemory`'s `db_path` through, so a `PersonaMemory(db_path=...)` instance's posts
      would silently land in `config.DATABASE_PATH`'s default database instead of the one
      `memory` was actually constructed against — same class of bug
      `reply_handler.generate_reply()` never had, since it only ever touches the database
      through `memory`'s own methods. Fixed by adding a `PersonaMemory.db_path` property and
      threading it through `post_handler.generate_post()`'s direct calls; covered by
      `tests/manual_test_bot_cycle.py`'s `test_run_post_cycle`, which asserts against a temp
      db rather than the real one.
- [x] Scheduling/cadence (timer loop, or launchd job per the deployment target) — `bot.py`
      supports both shapes the checklist item names: `--once` runs a single cycle and exits
      (the shape an external launchd job would invoke on a schedule), and the default with no
      flag runs an internal `time.sleep`-based timer loop. New `config.CYCLE_INTERVAL_MINUTES`
      (default 240 = 4h, landing on 6 cycles/day at the upper end of `docs/SPEC.md`'s "3-6
      original posts a day" user story) and `config.REPLY_MAX_PER_CYCLE` (default 3) control
      cadence/volume; both are env-overridable and also exposed as `--interval-minutes`/
      `--max-replies` CLI flags for a single run. Live publishing defaults off
      (`config.LIVE_POSTING_ENABLED=false`) since posting is public and effectively
      irreversible (`docs/SCAFFOLDING.md` Phase 6) — `--live` (or the env var) is required to
      publish, and `bot.py` refuses to go live and falls back to dry-run with a logged warning
      if `TWITTER_USERNAME`/`TWITTER_PASSWORD` aren't set, rather than failing partway through
      a cycle.

Verified two ways, same standard as Phase 4/5/6:
- `tests/manual_test_bot_cycle.py` (new, plain asserts, no pytest suite yet — Phase 9)
  exercises `_parse_x_post_url()`, `run_post_cycle()`, and `run_reply_cycle()` against a fake,
  non-network `LLMProvider` and a temp database: post generation + persistence, reply
  generation for well-formed timeline permalinks, malformed-permalink skipping, `max_replies`
  capping, and already-replied dedup across two passes over the same candidates. All pass
  (`venv/bin/python tests/manual_test_bot_cycle.py`). Re-ran `tests/manual_test_persistence.py`
  as a regression check after the `PersonaMemory.db_path` fix above — still passes.
- A live `venv/bin/python src/bot.py --once` run (`.env`'s `LLM_PROVIDER=local`, same
  `deepseek-coder-v2:16b` setup as Phase 4/5) against the real `arxiv`/`history_today`/
  `hackernews`/`arts_feed` sources: all four fetched successfully, phase/register selection
  ran (`convergence`/`delighted`), the generated post and its triggering signal were written
  to `data/tedkhao.db` (`posts`, `signals` with `used_at` set, `state_history`) exactly as
  Phase 5 verified for `tests/manual_test_posts.py`, and no browser call was made (dry run).
  `--live` was also exercised once to confirm the credential guard: it logged a warning and
  fell back to dry-run rather than attempting a live post, since `.env`'s
  `TWITTER_USERNAME`/`TWITTER_PASSWORD` are still empty.
  `timeline_scraper.fetch()` failed inside `fetch_all_signals()`'s try/except exactly as
  expected — the same "needs real credentials" blocker Phase 6 already documented, not a new
  issue — and the cycle correctly continued using the other three sources rather than
  aborting. Reply-cycle live posting and the reply-candidate-discovery path against a real
  timeline remain genuinely unverified end-to-end for the same reason: no `TWITTER_USERNAME`/
  `TWITTER_PASSWORD` in this repo's `.env` yet. **This is the one item this phase leaves
  unverified** — everything else (orchestration wiring, dry-run generation/persistence for
  both posts and replies, cadence/CLI, the live-posting safety guard) is done and proven.

**Voice-quality note, not new**: the live run's generated post text mixed the triggering
arxiv signal (a GPU-accelerated counterfactual-regret-minimization paper) with an unrelated
"medieval color notation systems" comparison that has no basis in the signal — another
instance of the cross-cutting voice-quality open item tracked since Phase 2/4 (generic/
confused phrasing, occasional fabricated detail), now also observed via the orchestrator path
on the same code-specialized local model already flagged as non-representative of
general-purpose voice quality. Doesn't block this phase (the orchestration mechanism is what
Phase 7 is responsible for) and isn't being treated as a new verdict on voice quality, per the
standing "don't overgeneralize from one test" rule.

## Phase 8 — Local-Model Deployment ⚠️ partially validated

- [x] Local Ollama inference confirmed working end-to-end on the M4 (same-machine test,
      via `OpenAICompatibleProvider` against `deepseek-coder-v2:16b`)
- [ ] Cross-machine test — 2014 MacBook Air calling the M4 over LAN via `.local` hostname
      has not actually been tried yet; only same-machine local calls tested so far
- [ ] 2014 Air hardware/memory check — Selenium + Chrome memory pressure on that machine,
      flagged as a risk in `docs/SPEC.md`, not yet tested

## Phase 9 — Automated Tests ⬜ not started

- [ ] Convert the manual fake-post review into real `pytest` assertions where sensible
      (e.g. `_ensure_length` never exceeds the limit, `select_register_for_reply` respects
      recent-register exclusion) — some of this exists only as ad hoc one-off shell checks
      run during development, not committed as a test suite
- [ ] `tests/test_state.py`, `test_voice_bank.py`, `test_prompts.py` per `docs/STRUCTURE.md`'s
      planned layout — none of these files exist yet
