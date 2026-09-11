# Code Review Remediation Checklist

Created: 2026-09-11. Current status is maintained in the work register below.

This is the working tracker for the eight code-review findings and the subsequent
persistent-browser requirement. Historical build completion in SCAFFOLDING.md does not
mean these findings are resolved. Scope is the existing single-operator bot.

## Workflow

The work register is the single source of current remediation status. On session re-entry,
read it and the linked evidence before selecting work. Update the relevant row as work
progresses; do not duplicate current status in introductory prose or other documents.
Dated evidence and change-history entries describe events at that time, not current status.

1. Take the next dependency-ready work item and record its owner and status below.
2. Implement the item and its regression checks together, referencing its ID in the change.
3. Record the exact validation command, outcome, and commit or PR in the evidence log.
4. Check acceptance boxes only when verified. Mark an item verified only when every box is
   checked; track live validation separately from offline validation.
5. Update affected specification, scaffolding, and change records with the implementation.
   Record a reverted change as reverted rather than retaining its verified status.

Statuses: planned → in progress → implemented → verified. Use blocked with a concrete
dependency/reason, or reverted with the related change reference. Deployment is recorded
separately; verified does not mean deployed.

Use `/phase-runner` with an explicit file and phase, for example:

```text
/phase-runner implement Phase 1 in docs/REVIEW_CHECKLIST.md
```

Phase numbers are local to this document; RC IDs remain the stable work identifiers.

## Work register and order

| Phase | ID | Priority | Work | Dependencies | Status | Owner | Change / evidence |
|---|---|---|---|---|---|---|---|
| 1 | RC-101 | High | Isolate tests and use production handlers (finding 8) | None | Verified | Codex | Phase 1 evidence below; `feat/phase-1-isolated-test-harnesses` |
| 2 | RC-102 | High | Model generation and publication separately (finding 1) | RC-101 | Verified | Codex | Phase 2 evidence below; `feat/phase-2-publication-lifecycle` |
| 3 | RC-103 | High | Share a persistent browser and handle authentication | RC-101 | Verified | Claude | Phase 3 evidence below; `feat/phase-3-persistent-browser` |
| 4 | RC-104 | High | Confirm publication and reconcile uncertain attempts (finding 2) | RC-102, RC-103 | Planned | Unassigned | Pending |
| 5 | RC-105 | Medium | Reject empty generation (finding 6) | RC-101, RC-102 | Planned | Unassigned | Pending |
| 6 | RC-106 | High | Correct feed selection and phase classification (finding 3) | RC-101 | Planned | Unassigned | Pending |
| 7 | RC-107 | Medium | Prevent repeated source coverage (finding 4) | RC-102, RC-106 | Planned | Unassigned | Pending |
| 8 | RC-108 | Medium | Ground prompt structures in available context (finding 5) | RC-106, RC-107 | Planned | Unassigned | Pending |
| 9 | RC-109 | Medium | Isolate engagement failures (finding 7) | RC-104, RC-105 | Planned | Unassigned | Pending |
| 10 | RC-110 | High | Run integrated regression and controlled live validation | RC-101–RC-109 | Planned | Unassigned | Pending |

Recommended sequence: RC-101 → RC-102 → RC-103 → RC-104 → RC-105 → RC-106 →
RC-107 → RC-108 → RC-109 → RC-110. Dependencies, rather than priority alone, govern order.

## Phase 1: RC-101 — Isolated, repeatable test harnesses

**Depends on:** None.

Files: `tests/manual_test_posts.py`, `tests/manual_test_replies.py`,
`tests/manual_test_persistence.py`, `tests/manual_test_bot_cycle.py`.

- [x] Give voice-review harnesses temporary databases by default; any retained review data
      must use an explicitly selected review database.
- [x] Replace the post harness's duplicated pipeline with `generate_post()`.
- [x] Establish one documented offline test command covering persistence and cycle behavior;
      separate model/browser integration harnesses from that command.
- [x] Verify offline tests require no credentials, make no network/browser calls, and leave
      the operational database untouched.

Evidence required: offline command and result, plus database-isolation regression results.

RC-101 verification (2026-09-11, working tree based on `316d655`):
`venv/bin/python tests/run_offline.py` passed persistence, cycle, and both voice-harness
isolation checks. Fake-provider runs verified temporary cleanup, explicitly retained row
counts, and operational-path rejection. The runner disables dotenv/credentials and rejects
network, browser, subprocess, and SQLite access outside its temporary directory.
`venv/bin/python -m compileall -q src tests` and `git diff --check` passed.
No model or live-browser validation was performed; existing publication semantics remain
for RC-102. No repository lint/typecheck/build command is configured. Not deployed.

## Phase 2: RC-102 — Publication lifecycle and migration

**Depends on:** Phase 1 (RC-101).

Files: `src/database.py`, `src/persona/memory.py`, engagement handlers, `src/bot.py`.

- [x] Define and persist draft, attempted, confirmed, failed, and uncertain outcomes, including
      timestamps, target identity, and external publication ID/URL when known.
- [x] Generation saves a draft; it does not set publication timestamps or mark a target
      successfully replied to. Dry runs remain distinguishable from live attempts.
- [x] Confirmed replies suppress new replies across restarts. Uncertain attempts are held
      for reconciliation, not blindly retried; failed attempts remain eligible for controlled retry.
- [x] Commit related database changes atomically and update in-memory publication state only
      after successful persistence.
- [x] Provide a versioned migration preserving existing rows. Existing rows lack proof of
      publication: retain them as legacy/unknown and exclude them from automatic retries until
      reconciled. Validate migration against a copied fixture, with backup/rollback instructions.
- [x] Regression checks cover dry-run then live eligibility, browser failure before submission,
      successful confirmation, restart recovery, and database failure without false success.

Evidence required: lifecycle tests and migration results; no migration of the operational
database is needed to verify the implementation against fixtures.

RC-102 verification (2026-09-11, working tree based on `aa5e459`):
`venv/bin/python tests/run_offline.py` passed lifecycle, copied legacy migration and restore,
transaction rollback, persistence, cycle, and voice-review isolation checks. Regression
fixtures exercise dry-run then live eligibility, pre-submission failure, confirmed reply
suppression after restart, click-only/exception uncertainty, interrupted attempt holds,
explicit reconciliation, duplicate-attempt rejection, and database failure without false
in-memory success. Original-post timestamps/source use are set only on confirmation.
Migration version 1 preserves all prior table rows and marks their publications legacy_unknown;
idempotence and failed-migration rollback were verified on copies. Backup/rollback and
reconciliation procedure: [PUBLICATION_MIGRATION.md](PUBLICATION_MIGRATION.md).
`venv/bin/python -m compileall -q src tests` and `git diff --check` passed.
No lint/typecheck/build command is configured. No operational database was migrated and
no real browser/model call was made. Existing click-only browser results remain uncertain;
real confirmation is RC-104, browser ownership is RC-103. Not deployed.

## Phase 3: RC-103 — Persistent browser ownership and authentication

**Depends on:** Phase 1 (RC-101).

Files: `src/bot.py`, `src/utils/browser.py`, `src/signals/timeline_scraper.py`, configuration.

- [x] The orchestrator owns one driver across timer-loop cycles and passes it to timeline
      scraping, posting, and replies. Preserve the common source interface through an adapter
      or injected callable rather than adding browser ownership back to each operation.
- [x] Remove per-action driver creation and `quit()` calls. Close once on deliberate process
      shutdown; replace a driver only after a diagnosed browser failure.
- [x] Reuse a stable authenticated profile and prevent concurrent processes from sharing it.
- [x] Check authentication at startup and on evidence of expiry; avoid repeating login and
      home-page navigation before every action.
- [x] Provide a visible-browser/manual-authentication path. Pause X actions for login changes,
      verification challenges, rate limits, and account warnings, with an explicit resume path
      that verifies session health before continuing. Do not run repeated automatic login loops.
- [x] Document that `--once` ends the process and its browser; use the resident loop for a
      browser that stays open between scheduled cycles.
- [x] Fake-driver tests prove one launch across multiple cycles, shared driver identity,
      no per-action quits, bounded crash recovery, and clean shutdown on interruption.

Evidence required: driver lifecycle/authentication-state tests. Persistent sessions reduce
session churn; this work does not establish or promise avoidance of platform detection.

RC-103 verification (2026-09-11, working tree based on `2401469`):
`venv/bin/python tests/run_offline.py` passed lifecycle, publication, migration, cycle,
voice-review isolation, and the new `tests/manual_test_browser_session.py` fake-driver checks:
one Chrome launch across five simulated cycles (`browser.get_driver` call count == 1), shared
`session.driver` identity, an auth check performed once at startup and again only after
`flag_possibly_expired()` (not on every action), a headless session with no valid login
raising `SessionPaused` without calling `log_in()`, `publish()`/`timeline_scraper.fetch()`
never calling `driver.quit()`, one diagnosed crash (`InvalidSessionIdException`) triggering
exactly one relaunch-and-retry with a second crash in the same call propagating, and a
try/finally shutdown (standing in for `KeyboardInterrupt`) closing the driver exactly once
with `close()` idempotent on a second call. `tests/manual_test_publication.py`'s RC-102 cases
were updated for the new `publish(result, memory, session, target_url=None)` signature and
additionally assert `driver.quit.call_count == 0` until `session.close()`, and that
`live_posting=True` without a session raises `ValueError`.
`venv/bin/python -m compileall -q src tests` and `git diff --check` passed.
Live-Chrome verification (no offline mocks, no TWITTER_PASSWORD in `.env`):
`venv/bin/python tests/manual_test_browser.py` launched real headless Chrome and confirmed
`BrowserSession.ensure_ready()` raises `SessionPaused` cleanly against an unauthenticated
persisted profile rather than looping login. A separate manual check started one live
`BrowserSession`, confirmed a second concurrent session is refused with `RuntimeError` while
the first is open, and confirmed a third session can acquire the profile lock immediately
after `close()`. `venv/bin/python src/bot.py --once` (dry run, real Chrome, real
`ANTHROPIC_API_KEY`, no `TWITTER_PASSWORD`) confirmed the end-to-end regression this phase
had to avoid: the unauthenticated timeline fetch now logs a clear warning and degrades to an
empty timeline instead of raising, and post generation still completes from domain signals
alone (`phase=convergence register=awestruck signal=arxiv`) -- an earlier draft of this work
let `SessionPaused` propagate out of `fetch_all_signals()` and would have blocked all dry-run
post generation whenever no X session exists, which is this repo's actual current state. No
login, posting, or reply was attempted against a real account; the profile lock released
cleanly on process exit in every live run.
No repository lint/typecheck/build command is configured. Not deployed. Real X selector
behavior under `post_tweet()`/`post_reply()` and RC-104's confirmation contract remain
unverified live per RC-104/RC-110.

## Phase 4: RC-104 — Confirm submission and reconcile ambiguity

**Depends on:** Phase 2 (RC-102), Phase 3 (RC-103).

Files: `src/utils/browser.py`, `src/bot.py`, `src/database.py`.

- [ ] Publishing returns a structured outcome after observing confirmation or rejection;
      a button click alone never produces a success log or confirmed database state.
- [ ] Capture the published post/reply ID or URL and associate it with the intended target.
- [ ] Use bounded waits and distinguish confirmed rejection from a timeout after submission.
- [ ] A timeout/crash after submission remains uncertain until reconciliation finds the
      publication or establishes a safe retry decision. Do not automatically resubmit it.
- [ ] Test success, rejection, timeout, and crash after clicking with controlled browser
      fixtures; ensure confirmation occurs while the shared browser remains open.

Evidence required: deterministic outcome tests. Real X selectors and confirmation behavior
remain unverified until RC-110's explicitly authorized live check.

## Phase 5: RC-105 — Validate generated output before state changes

**Depends on:** Phase 1 (RC-101), Phase 2 (RC-102).

Files: engagement handlers and `src/llm_provider.py`.

- [ ] Validate nonempty text on initial generation and every shortening response.
- [ ] Handle missing/null/malformed provider output with an explicit generation failure;
      do not produce an empty publishable draft or consume a reply target.
- [ ] Keep regeneration attempts bounded and report a failed/skipped outcome when exhausted.
- [ ] Test whitespace, null/missing output, empty shortening output, valid output, and the
      existing overlength shortening/truncation paths.

Evidence required: provider/handler regression results showing invalid output cannot reach
browser submission or confirmed publication history.

## Phase 6: RC-106 — Source selection and phase correctness

**Depends on:** Phase 1 (RC-101).

Files: `src/signals/base.py`, signal fetchers, `src/persona/state.py`.

- [ ] Replace first-in-pool tie bias with an explicit, testable selection policy that does
      not systematically favor arXiv because it is fetched first.
- [ ] Distinguish source rank from evidence of novelty; a first-ranked historical event or
      museum object must not become a breakthrough solely because its score is 1.0.
- [ ] Require evidence of a relationship for Convergence. Multiple available domains alone
      do not qualify; use a supported single-signal phase when no relationship is established.
- [ ] Keep unsupported Contested detection explicitly deferred rather than inventing a proxy.
- [ ] Test actual fetcher-shaped pools with tied top scores, history-only and arts-only pools,
      unrelated cross-domain items, and the empty pool using deterministic fixtures/seeds.

Evidence required: expected/actual phase and selection cases, plus the selected policy's
decision record. Preserve the existing taxonomy unless a documented change is necessary.

## Phase 7: RC-107 — Remember previously covered sources

**Depends on:** Phase 2 (RC-102), Phase 6 (RC-106).

Files: `src/database.py`, `src/persona/memory.py`, state selection and post handler.

- [ ] Persist stable source identity (source ID or canonical URL, with a documented fallback
      for missing URLs) and define a configurable recent-coverage window.
- [ ] Filter recently confirmed coverage before choosing a signal; source-row insertion alone
      and dry runs must not count as published coverage.
- [ ] Hold signals associated with uncertain submissions until RC-104 reconciliation resolves
      them, preventing accidental duplicate publication.
- [ ] If all candidates were covered, return an explicit no-post result rather than silently
      reusing the same source. Define how materially updated source items become eligible.
- [ ] Test repeated fetches, process restarts, dry runs, uncertainty, expired coverage windows,
      missing URLs, and two sources referring to the same canonical URL.

Evidence required: deduplication and re-eligibility regressions.

## Phase 8: RC-108 — Evidence-backed prompt options

**Depends on:** Phase 6 (RC-106), Phase 7 (RC-107).

Files: `src/persona/prompts.py`, state selection, memory queries, post handler, `VOICE_GUIDE.md`.

- [ ] Pass both supporting signals for a Convergence prompt, or disable that phase until its
      selection/context contract supports them.
- [ ] Offer a specific callback only when a confirmed earlier post is supplied as context.
- [ ] Remove thread-opening generation from the single-post workflow; full thread publishing
      is deferred and requires its own tracked scope.
- [ ] Ensure no-signal prompts cannot select structures that require unavailable facts or
      earlier posts; support an explicit skip when there is nothing grounded to publish.
- [ ] Test prompt assembly for single-signal, convergence, callback, and empty-context cases.
- [ ] Record model-backed voice trials separately from deterministic tests, identifying model,
      scenario, and factual/continuity issues. Prompt tests alone do not establish factual accuracy.

Evidence required: prompt contract tests and a trial record. Existing voice-quality concerns
remain open unless the recorded trials justify closing them.

## Phase 9: RC-109 — Per-operation failure handling

**Depends on:** Phase 4 (RC-104), Phase 5 (RC-105).

Files: `src/bot.py`, engagement handlers, browser outcome handling.

- [ ] A post-generation or individual reply failure does not discard independent candidates.
- [ ] Return/log a cycle summary separating confirmed, draft, failed, skipped, and uncertain
      operations with their target/source identifiers; never log credentials or cookies.
- [ ] Pause all X actions on shared-session authentication challenges or account restrictions;
      failure isolation must not continue submitting through an unhealthy session.
- [ ] Keep recovery attempts bounded and retain sufficient outcome state across restarts.
- [ ] Test a failed post followed by eligible replies, a failed reply followed by a successful
      candidate, and a session challenge that stops subsequent X actions.

Evidence required: cycle failure-path tests and example sanitized summaries.

## Phase 10: RC-110 — Integrated completion check

**Depends on:** Phase 1 (RC-101), Phase 2 (RC-102), Phase 3 (RC-103), Phase 4 (RC-104), Phase 5 (RC-105), Phase 6 (RC-106), Phase 7 (RC-107), Phase 8 (RC-108), Phase 9 (RC-109).

- [ ] Run the complete offline regression command against temporary databases and fake
      providers/browser fixtures; record results and the exact revision tested.
- [ ] Verify resident multi-cycle driver reuse, crash recovery, migration, publication-state
      transitions, repeat-source exclusion, and failure isolation together.
- [ ] Update SPEC.md, SCAFFOLDING.md, STRUCTURE.md, README.md, and CHANGELOG.md as applicable
      so documented behavior matches implementation; preserve unresolved voice-quality items.
- [ ] Prepare a concrete live-validation procedure: account/profile, intended post and reply,
      confirmation checks, stop conditions, and expected database records.
- [ ] Obtain explicit user authorization for that specific real-account validation before
      login/posting, as required by CLAUDE.md's current-status and Phase 6 guidance.
- [ ] After authorization, verify session reuse, actual publication IDs, and confirmation
      persistence. Record evidence without credentials, cookies, or unnecessary account data.
- [ ] Record deployment separately, including revision and environment. Until live validation
      happens, label the browser integration offline-verified/live-unverified.

## Baseline evidence

Review performed 2026-09-11, before remediation:

| Check | Outcome |
|---|---|
| `venv/bin/python tests/manual_test_persistence.py` | Passed |
| `venv/bin/python tests/manual_test_bot_cycle.py` | Passed; current assertions count dry-run replies as replied and must change in RC-102 |
| Isolated fake-provider/temp-DB reproduction: browser startup raises | Target still marked replied after restart |
| Isolated representative pool with tied source scores | Convergence selected; arXiv wins |
| Isolated history-only pool, top rank 1.0 | Incorrectly selected Breakthrough |
| Two generations from the same pool | Same source URL selected again |
| Whitespace provider output | Empty post accepted and persisted |

The isolated reproductions were ad hoc review checks, not committed regression tests.
Live X, feed availability, and model quality were not validated by this review.

## Evidence log

Append one row per implementation/verification/reversion; link lengthy output or trial records
from `docs/` rather than embedding secrets or operational database dumps.

| Date | Work ID | Revision / PR | Command or procedure | Result / limitations | Deployment |
|---|---|---|---|---|---|
| 2026-09-11 | Planning | Working tree | Review findings mapped to RC-101–RC-110 | Checklist created | None |
| 2026-09-11 | RC-103 | `feat/phase-3-persistent-browser` | `venv/bin/python tests/run_offline.py`; `venv/bin/python tests/manual_test_browser.py` (live Chrome, no credentials) | Offline fake-driver session/crash/shutdown checks and RC-102 lifecycle regressions passed; live headless Chrome confirmed SessionPaused on no login and profile-lock exclusion | Not deployed |

## Decisions and change history

| Date | Decision / change | Reason |
|---|---|---|
| 2026-09-11 | Added eight findings plus persistent browser/authentication work | User requested an actionable, trackable workflow under `docs/` |
| 2026-09-11 | Browser owned by resident orchestrator; shutdown and diagnosed failure are lifecycle boundaries | User requires Chrome to remain open between posts/replies and identifies login as a friction point |
| 2026-09-11 | Preserve uncertain and legacy publication outcomes for reconciliation | Existing records do not prove delivery; automatic retries can duplicate real posts |
| 2026-09-11 | Defer full threads; gate callbacks/convergence on supplied context | Single-post pipeline cannot fulfill thread openings or unsupported continuity |

| 2026-09-11 | Mapped RC-101–RC-110 to Phases 1–10 with explicit phase dependencies | Make the checklist directly addressable by `/phase-runner` while preserving work IDs |
