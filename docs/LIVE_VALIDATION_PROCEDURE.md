# RC-110 Live Validation Procedure

This is a one-time, minimal, explicitly-authorized check that real X posting and RC-104's
submission confirmation actually work against a live account -- not a switch to unattended
live operation. Every other RC-10x item has been verified offline only (fake driver, fake
provider); this procedure is the only place real credentials, a real browser session, and a
real X account are involved. Do not run any step below without the specific authorization
described in "Authorization gate."

## Authorization gate

- This procedure requires the user's explicit, specific go-ahead for *this* live-account
  validation, given after reading this document -- a general "sounds good" or a confirming
  question about the plan does not count as that go-ahead.
- `TWITTER_USERNAME`/`TWITTER_PASSWORD` must already be set directly in `.env` by the user
  (never pasted into chat, per `CLAUDE.md`). Confirm both are non-empty before starting; do
  not ask the user to paste either value to verify this -- check `.env` directly.
- Record the authorization (who, when, which account/profile) in
  `docs/REVIEW_CHECKLIST.md`'s evidence log before running anything live.

## Account/profile

- Use the X account the persona is actually meant to operate as -- not a personal or
  unrelated test account, since the post/reply will be real, public, and (by X's own nature)
  effectively permanent.
- The persistent Chrome profile lives at `data/browser_profile/` (gitignored) and is
  protected by a file lock (`utils.browser.BrowserSession`, RC-103) that refuses a second
  concurrent session against the same profile. Confirm no other `bot.py`/manual browser test
  process is running before starting.
- Back up the operational database first, per
  [docs/PUBLICATION_MIGRATION.md](PUBLICATION_MIGRATION.md)'s backup/rollback procedure --
  this validation writes real `publications`/`posts` rows to it.
- Record the exact git revision under test (`git rev-parse HEAD`) alongside the
  authorization.

## Procedure

1. **Clear authentication first, visibly.** A dry run's `fetch_all_signals()` degrades a
   `SessionPaused`/login-challenge to an empty timeline and keeps going (RC-103's designed
   graceful-degradation path for read-only work), so `--once --visible` alone is not a
   reliable way to get a lasting window for a human to act in -- the process (and its
   browser) can close again before anyone looks at it. Use the module's actual documented
   recovery path instead, which opens a visible window and waits up to 10 minutes for a
   human to clear whatever X is asking for:
   ```bash
   venv/bin/python -c "from utils.browser import resume_manual_login as r; r()"
   ```
   Complete login/verification in the opened Chrome window. This prints a confirmation once
   the session verifies as authenticated and closes the window itself; do not attempt an
   automated retry loop.
2. **Preview one dry run.** With a working session, run one more dry-run cycle and read the
   logged post text (and any reply text) before deciding to publish it:
   ```bash
   venv/bin/python src/bot.py --once --max-replies 1
   ```
   Generated text is not deterministic between calls, so this preview's exact wording may
   differ slightly from what the live run below actually posts -- it establishes that
   generation is producing sane, on-voice, non-embarrassing output right now, not an exact
   script. A draft from this step is never counted as coverage (RC-107 only counts real
   publish attempts), so it does not block the live run below from using the same source.
3. **Run exactly one live cycle, capped.** Do not use the resident loop for this validation:
   ```bash
   venv/bin/python src/bot.py --once --live --max-replies 1
   ```
   `--max-replies 1` bounds this to at most one original post and one reply -- the minimum
   needed to exercise both `post_tweet()` and `post_reply()` confirmation paths in a single,
   reviewable run.
4. **Do not repeat step 3.** One authorized live cycle is what this procedure covers. Re-running
   it (including after a failure) needs a fresh, explicit go-ahead, not an automatic retry --
   see "Stop conditions" below.

## Confirmation checks

For each publication attempted in step 3:

- The logged line `publication %s: confirmed` (`engagement/publication.py`) appears, not
  `failed` or `uncertain`.
- The corresponding `publications` row reaches `status = 'confirmed'` with `external_id` and/or
  `external_url` populated (query directly, e.g.
  `sqlite3 data/tedkhao.db "SELECT id, kind, status, external_id, external_url, source_url FROM publications ORDER BY id DESC LIMIT 5;"`).
- The post row's `posted_at` (for a post) is set, matching RC-102's "only on confirmation"
  contract.
- The `external_url` recorded actually resolves to the real post/reply on X -- open it and
  visually confirm the text and target match what was logged. This is the step that actually
  validates RC-104's selector-based confirmation against the live DOM, which nothing offline
  can prove.
- No publication beyond the one post and one reply this run was capped to exists with a
  `created_at`/`attempted_at` timestamp from this run.

## Stop conditions

Stop immediately -- do not retry, do not re-run step 3, do not attempt to fix and continue --
if any of the following happens. Report it and wait for explicit direction before any further
live action:

- Any publication from this run lands at `status = 'uncertain'` or `'failed'` instead of
  `'confirmed'`. Do not resubmit it automatically -- follow
  [docs/PUBLICATION_MIGRATION.md](PUBLICATION_MIGRATION.md)'s explicit reconciliation
  procedure once the real state on X is known.
- `SessionPaused` is raised or logged during step 3 (an authentication challenge, rate limit,
  or account restriction surfaced mid-run).
- X shows a rate-limit notice, an account warning/restriction banner, or any verification
  challenge at any point.
- More than one post or more than one reply is attempted, or a publication targets something
  other than the intended candidate.
- The process crashes or is interrupted before step 3 finishes.
- Anything about the account looks different from what was expected going in (unexpected
  existing posts, suspended/locked state, unfamiliar login prompt).

## Expected database records

A clean run of step 3 leaves exactly:

- One new `publications` row, `kind = 'post'`, `status = 'confirmed'`, non-NULL `external_id`
  or `external_url`, `source_url`/`source_fingerprint` matching the signal actually used
  (RC-107), and a matching `posts` row with `posted_at` set.
- At most one new `publications` row, `kind = 'reply'`, `status = 'confirmed'`, non-NULL
  `external_id`/`external_url`, and `target_id`/`target_url` matching the real X post replied
  to.
- No other new rows in `publications`, `posts`, or `signals` beyond what generating and
  confirming those two items requires.

## After the run

- Add a dated entry to `docs/REVIEW_CHECKLIST.md`'s evidence log recording: the revision
  tested, that this procedure was followed, the confirmation checks performed, and the
  outcome -- link the real `external_url`s (they are already public) but never paste
  credentials, cookies, session tokens, or any `.env` contents into the record.
- Update RC-110's checklist boxes for the items this run actually covers (session reuse,
  actual publication IDs, confirmation persistence) and record deployment status separately,
  per RC-110's own acceptance criteria -- a successful validation run is not itself a
  deployment.
- Until this procedure has actually been run and confirmed, RC-103/RC-104's browser
  integration remains labeled offline-verified/live-unverified, per RC-110's own requirement.
