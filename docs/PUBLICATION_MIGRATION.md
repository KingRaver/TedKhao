# RC-102/RC-107 publication storage and migration

Schema version 2 uses `PRAGMA user_version`. On the first `PersonaMemory` startup,
`init_db()` migrates version 0 (and, separately, version 1) to the current version in one
transaction; subsequent startups are idempotent. A newer schema version is rejected. This
change has only been run against test fixtures.

Version 2 (RC-107) adds `publications.source_url`/`source_fingerprint`, populated only for
original posts (`kind = 'post'`), via `ALTER TABLE` against an existing version-1 database.
Pre-existing rows -- including the version-0-to-1 migration's own `legacy_unknown` rows --
keep both columns NULL rather than a guessed value backfilled from a posts/signals join,
matching the version-0-to-1 migration's own "retain as legacy/unknown, don't invent proof"
stance; a NULL `source_url` never matches `get_covered_sources()`'s lookup, so legacy rows
are simply excluded from source-coverage matching rather than incorrectly blocking (or
failing to block) a real source.

`publications` stores draft content, kind, target ID/author/content/URL, generation and
attempt/confirmation/update timestamps, current outcome, and external publication ID/URL.
`publication_events` retains each transition, timestamp, detail, and external identity,
including repeated attempts. `posts` remains the original-post content table;
`replied_posts` contains confirmed replies plus preserved historical rows. Use publications,
not presence in replied_posts, to determine success or retry eligibility.

Generation commits its draft, source snapshot, and persona history together. New originals
have NULL `posted_at`; sources have NULL `used_at` until confirmation. Replies are added to
replied_posts only on confirmation. Persona history tracks generation, not publication.
Dry runs produce drafts and no attempted timestamp. A live action first persists attempted;
only then may the browser run. An interrupted attempted row stays held after restart.

Confirmed replies suppress further replies. Attempted, uncertain, and legacy_unknown reply
targets also block new attempts, without being reported as successful. Failed and draft
targets remain eligible in a later explicitly live cycle, bounded by its reply limit.
A failed publication can also transition to attempted through the lifecycle API; every
transition is retained. Confirmation requires external identity supplied by a trusted
publication adapter. RC-104 implements real confirmation: `utils.browser.post_tweet()`/
`post_reply()` observe X's response to a submission (a toast with a status permalink, or an
error dialog) and return a structured outcome; a click with no such evidence, or a bounded
wait that times out, still becomes uncertain rather than confirmed. Failures during browser
startup/authentication are failed; exceptions once the posting method begins are
conservatively uncertain. Driver ownership remains RC-103's.

## Backup and rollback

1. Stop the bot and all other writers. Locate the configured `DATABASE_PATH` locally.
2. Use SQLite's backup facility to an unused backup path before running the new code:
   `sqlite3 /absolute/path/tedkhao.db ".backup '/absolute/path/tedkhao.pre-rc102.db'"`.
   Keep this backup with the pre-migration code revision. Verify the backup with
   `sqlite3 /absolute/path/tedkhao.pre-rc102.db 'PRAGMA integrity_check;'` (expect `ok`).
3. Copy that backup to a separate rehearsal path and call `database.init_db()` on the
   rehearsal path first. Check `PRAGMA user_version` is 1, original rows are unchanged,
   and every historical posts/replied_posts row has one legacy_unknown publication.
4. Start the new code only after preserving the backup. Migration does not assert that
   historical timestamps prove publication: all historical rows are retained unchanged
   and mapped to legacy_unknown. No automatic retry of these publications is allowed.
5. To roll back, stop all writers, preserve the upgraded database separately, and restore
   the backup to the configured path using SQLite's `.restore` with no open connections.
   Restore the matching prior code before restarting. Do not just lower user_version.
   A backup restore discards writes made after the backup; reconcile any external actions
   recorded in the upgraded copy before resuming publishing.

## Reconciliation

There is no automatic reconciliation or bulk release. Inspect a publication and establish
whether it was actually published. A trusted caller may invoke
`memory.transition_publication(id, 'confirmed', reconcile=True, detail='evidence reference',
external_id='observed ID', external_url='observed URL')`, or use `failed` with an explicit
evidence detail once non-publication is established. These transitions release or confirm
uncertain/legacy holds atomically. For an interrupted attempted row, record uncertain first.
A confirmed row cannot be automatically reset. Legacy original posts are never selected
for automatic retry; source-coverage deduplication is separate RC-107 work.

## Source coverage (RC-107)

`persona.memory.PersonaMemory.covered_source_keys()` returns the `(source_url,
content_fingerprint)` pairs `engagement.post_handler.generate_post()` must not draw an
original post from right now: a source confirmed within `config.SOURCE_COVERAGE_WINDOW_HOURS`
(default 72h), or a source with an unresolved `attempted`/`uncertain` attempt regardless of
window -- an unresolved attempt must not be duplicated before reconciliation (see above)
resolves it. `failed` and `draft` sources (including every dry run) are never held. A source
whose title changes since it was last covered gets a new `content_fingerprint` and becomes
eligible again even inside the window -- a materially updated item, not a repeat. When every
signal in the current pool is covered, `generate_post()` returns an explicit skipped result
(`"skipped": "all_candidate_sources_recently_covered"`, everything else `None`) rather than
silently reselecting an already-posted source; `bot.run_post_cycle()` logs and returns this
without generating, persisting a draft, or attempting to publish. See
`tests/manual_test_source_coverage.py` for the regression cases.

## Verification

`venv/bin/python tests/run_offline.py` runs lifecycle, copied-fixture migration,
transaction rollback, backup restore, persistence, cycle, and review-isolation checks.
No operational migration, real browser submission, or live confirmation is part of this test.
