# TedKhao — Phased Build Checklist

Verified against the actual repo state (file inventory + test runs), not against what
`docs/SPEC.md` describes on paper. Checked items have been built *and* observed working;
unchecked items may be designed in SPEC.md/STRUCTURE.md but have no code yet.

Use with `/phase-runner` to implement one phase at a time, verified against real commands.

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

## Phase 4 — Original Post Generation ⬜ not started

- [ ] `persona/prompts.py` — `build_post_prompt()` equivalent to `build_reply_prompt()`,
      driven by a Phase + selected Signal instead of an incoming post
- [ ] Few-shot examples for original posts per Register (currently only reply examples exist)
- [ ] Manual test harness for original posts (`tests/manual_test_posts.py`), same spirit as
      the existing reply harness — fake signals in, read the output before automating

## Phase 5 — Persistence ⬜ not started

- [ ] `src/database.py` — SQLite schema from `docs/SPEC.md` (`signals`, `state_history`,
      `posts`, `replied_posts` tables)
- [ ] Wire `PersonaMemory` to persist across restarts instead of in-process-only
- [ ] Wire `reply_handler`/post-generation to log to `posts` / `replied_posts`

## Phase 6 — X/Twitter Integration ⬜ not started

- [ ] `src/utils/browser.py` — Selenium WebDriver setup
- [ ] `src/signals/timeline_scraper.py` — X timeline scraping (conversation-driven signal)
- [ ] Login/session handling (`TWITTER_USERNAME`/`TWITTER_PASSWORD` already in `.env.example`,
      unused so far)
- [ ] Actual posting (original posts + replies) — currently everything only prints to stdout

## Phase 7 — Orchestration ⬜ not started

- [ ] `src/bot.py` — thin orchestrator per `docs/STRUCTURE.md`'s design; ties signals →
      state engine → persona → engagement → database → posting into one cycle
- [ ] Scheduling/cadence (timer loop, or launchd job per the deployment target)

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
