"""RC-109 fake-driver/fake-provider checks for per-operation failure isolation in bot.py: a
failed post generation must not stop the reply cycle, a failed individual reply must not stop
later independent candidates, and a shared-session authentication challenge must stop every
subsequent X action instead of being treated as one more isolated failure. Also covers
summarize_cycle()'s outcome bucketing, which is what a cycle's sanitized status log is built
from. Never launches real Chrome -- browser.get_driver is always patched, matching
tests/manual_test_browser_session.py's convention.

Included in `venv/bin/python tests/run_offline.py` (RC-101 isolation). Uses plain asserts. Run
standalone with:

    python tests/manual_test_failure_isolation.py
"""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from selenium.common.exceptions import WebDriverException  # noqa: E402

import bot  # noqa: E402
import database  # noqa: E402
from llm_provider import GenerationError, LLMProvider  # noqa: E402
from manual_test_bot_cycle import FakeProvider, _FAKE_DOMAIN_SIGNALS, _FAKE_TIMELINE_SIGNALS  # noqa: E402
from persona.memory import PersonaMemory  # noqa: E402
from signals.base import Signal  # noqa: E402
from utils import browser  # noqa: E402
from utils.browser import BrowserSession, PublicationOutcome, SessionPaused  # noqa: E402


def expect_error(call, error=Exception):
    try:
        call()
    except error:
        return
    raise AssertionError(f'expected {error.__name__}')


def no_profile_lock():
    """This offline harness must never touch the real data/browser_profile/ lock file."""
    return (patch.object(browser, '_acquire_profile_lock', return_value=None),
            patch.object(browser, '_release_profile_lock'))


class _MarkerFailingProvider(LLMProvider):
    """Raises GenerationError whenever a prompt contains any of `fail_markers`; otherwise
    returns fixed valid text. Lets one fake provider script "this specific operation's
    generation fails, an independent one succeeds" -- build_post_prompt()'s "Write an original
    post" line and build_reply_prompt()'s embedded post text are distinct enough to target
    either a whole post generation or one specific reply candidate."""

    def __init__(self, fail_markers):
        self._fail_markers = fail_markers

    def generate(self, prompt: str, system_prompt: str | None = None,
                 max_tokens: int = 300, temperature: float = 0.8) -> str:
        if any(marker in prompt for marker in self._fail_markers):
            raise GenerationError('scripted failure for RC-109 isolation test')
        return "A genuinely specific detail about something curious, worth its own post."


# A third valid reply target, alongside manual_test_bot_cycle's two -- needed only by
# test_session_challenge_stops_subsequent_replies to prove a candidate *after* the one that
# trips SessionPaused is never attempted at all.
_THIRD_REPLY_TARGET = Signal(
    source="x_timeline", domain="arts",
    title="a fake timeline post about a third target",
    summary="a fake timeline post about a third target, worth replying to",
    url="https://x.com/third_handle/status/3333333333", novelty_score=0.2,
)


# --- generation failures: isolated per operation, independent work still proceeds -----------

def test_post_generation_failure_does_not_block_independent_replies(db_path: str) -> None:
    memory = PersonaMemory(db_path=db_path)
    provider = _MarkerFailingProvider(fail_markers=["Write an original post"])

    post_result = bot.run_post_cycle(
        provider, memory, _FAKE_DOMAIN_SIGNALS, [], live_posting=False,
    )
    assert post_result["outcome"] == "generation_failed"
    assert post_result["post_id"] is None and post_result["publication_id"] is None

    reply_results = bot.run_reply_cycle(
        provider, memory, _FAKE_TIMELINE_SIGNALS, live_posting=False, max_replies=3,
    )
    assert len(reply_results) == 2, (
        "a post-generation failure must not prevent independent reply candidates from running"
    )
    assert all(r["outcome"] == "draft" and r["reply_text"] for r in reply_results)

    summary = bot.summarize_cycle(post_result, reply_results)
    assert len(summary["failed"]) == 1 and summary["failed"][0]["kind"] == "post"
    assert len(summary["draft"]) == 2
    print('  a failed post generation does not discard independent reply candidates: PASS')


def test_reply_generation_failure_does_not_block_later_candidates(db_path: str) -> None:
    memory = PersonaMemory(db_path=db_path)
    failing_target_text = _FAKE_TIMELINE_SIGNALS[0].summary
    provider = _MarkerFailingProvider(fail_markers=[failing_target_text])

    results = bot.run_reply_cycle(
        provider, memory, _FAKE_TIMELINE_SIGNALS, live_posting=False, max_replies=3,
    )

    assert len(results) == 2
    assert results[0]["outcome"] == "generation_failed" and results[0]["reply_text"] is None
    assert results[1]["outcome"] == "draft" and results[1]["reply_text"], (
        "a failed reply must not stop a later, independent candidate from succeeding"
    )
    print('  a failed reply generation is followed by a successful candidate: PASS')


# --- publish failures (not SessionPaused): isolated per operation, independent work proceeds -

def test_post_publish_failure_does_not_block_reply_cycle(db_path: str) -> None:
    memory = PersonaMemory(db_path=db_path)
    session = BrowserSession()

    lock_a, lock_b = no_profile_lock()
    with lock_a, lock_b, \
         patch.object(browser, 'get_driver', return_value=Mock()), \
         patch.object(browser, 'is_logged_in', return_value=True), \
         patch.object(browser, 'post_tweet', side_effect=WebDriverException('renderer crashed')):
        post_result = bot.run_post_cycle(
            FakeProvider(), memory, _FAKE_DOMAIN_SIGNALS, [], live_posting=True, session=session,
        )
    assert post_result["outcome"] == "publish_failed"
    assert database.get_publication(post_result["publication_id"], db_path)["status"] in (
        "failed", "uncertain"
    )

    lock_a, lock_b = no_profile_lock()
    with lock_a, lock_b, \
         patch.object(browser, 'get_driver', return_value=Mock()), \
         patch.object(browser, 'is_logged_in', return_value=True), \
         patch.object(browser, 'post_reply', return_value=PublicationOutcome(
             'confirmed', external_id='ok', external_url='https://x.com/ted/status/ok')):
        reply_results = bot.run_reply_cycle(
            FakeProvider(), memory, _FAKE_TIMELINE_SIGNALS, live_posting=True, max_replies=3,
            session=session,
        )
    session.close()

    assert len(reply_results) == 2, (
        "a failed post publish must not prevent independent reply candidates from being attempted"
    )
    assert all(r["outcome"] == "confirmed" for r in reply_results)
    print('  a failed post publish does not discard independent reply candidates: PASS')


def test_reply_publish_failure_does_not_block_later_candidates(db_path: str) -> None:
    memory = PersonaMemory(db_path=db_path)
    session = BrowserSession()
    lock_a, lock_b = no_profile_lock()

    call_count = [0]

    def post_reply_side_effect(driver, url, text):
        call_count[0] += 1
        if call_count[0] == 1:
            raise WebDriverException('renderer crashed')
        return PublicationOutcome('confirmed', external_id='ok',
                                   external_url='https://x.com/ted/status/ok')

    with lock_a, lock_b, \
         patch.object(browser, 'get_driver', return_value=Mock()), \
         patch.object(browser, 'is_logged_in', return_value=True), \
         patch.object(browser, 'post_reply', side_effect=post_reply_side_effect):
        results = bot.run_reply_cycle(
            FakeProvider(), memory, _FAKE_TIMELINE_SIGNALS, live_posting=True, max_replies=3,
            session=session,
        )
    session.close()

    assert len(results) == 2
    assert results[0]["outcome"] == "publish_failed"
    assert results[1]["outcome"] == "confirmed", (
        "a failed reply publish must not stop a later, independent candidate from succeeding"
    )
    print('  a failed reply publish is followed by a successfully confirmed candidate: PASS')


# --- SessionPaused: must stop every subsequent X action, never isolated like an ordinary -----
# --- failure -----------------------------------------------------------------------------------

def test_session_challenge_stops_subsequent_replies(db_path: str) -> None:
    memory = PersonaMemory(db_path=db_path)
    session = BrowserSession(headless=True)
    lock_a, lock_b = no_profile_lock()

    # First auth check (target 1) succeeds; target 1's publish then fails and flags the session
    # for re-verification (BrowserSession.flag_possibly_expired(), called by publish() on any
    # exception) -- the second auth check (target 2) simulates the session having gone bad in
    # between (an account restriction, a rate limit, a logged-out cookie) and must pause rather
    # than retry login automatically.
    login_calls = [0]

    def is_logged_in_side_effect(driver):
        login_calls[0] += 1
        return login_calls[0] == 1

    targets = _FAKE_TIMELINE_SIGNALS[:2] + [_THIRD_REPLY_TARGET]
    with lock_a, lock_b, \
         patch.object(browser, 'get_driver', return_value=Mock()), \
         patch.object(browser, 'is_logged_in', side_effect=is_logged_in_side_effect), \
         patch.object(browser, 'post_reply', side_effect=WebDriverException('renderer crashed')), \
         patch.object(browser, 'log_in') as auto_login:
        expect_error(lambda: bot.run_reply_cycle(
            FakeProvider(), memory, targets, live_posting=True, max_replies=3, session=session,
        ), SessionPaused)
        assert auto_login.call_count == 0, 'a paused session must never retry login automatically'
    session.close()

    with database._connect(db_path) as conn:
        count = conn.execute('SELECT COUNT(*) FROM publications').fetchone()[0]
    assert count == 2, (
        'target 1 (failed publish) and target 2 (session paused) each leave one publication '
        'row; target 3 must never be attempted once the session pauses, so no third row exists'
    )
    assert not database.reply_is_held('3333333333', db_path), (
        'the third candidate, after the paused one, must never even be generated'
    )
    print('  a session challenge mid-cycle stops every subsequent reply, never retries login: PASS')


# --- summarize_cycle(): outcome bucketing for a sanitized cycle status line ------------------

def test_summarize_cycle_buckets_and_identifiers() -> None:
    post_result = {"outcome": "confirmed", "signal": _FAKE_DOMAIN_SIGNALS[0]}
    reply_confirmed = {"outcome": "confirmed",
                        "post": {"id": "1", "url": "https://x.com/a/status/1", "author_handle": "@a"}}
    reply_draft = {"outcome": "draft",
                   "post": {"id": "2", "url": "https://x.com/b/status/2", "author_handle": "@b"}}
    reply_failed = {"outcome": "generation_failed", "detail": "GenerationError: scripted failure",
                    "post": {"id": "3", "url": "https://x.com/c/status/3", "author_handle": "@c"}}
    reply_skipped = {"outcome": "skipped",
                     "post": {"id": "4", "url": "https://x.com/d/status/4", "author_handle": "@d"}}
    reply_uncertain = {"outcome": "uncertain",
                       "post": {"id": "5", "url": "https://x.com/e/status/5", "author_handle": "@e"}}

    summary = bot.summarize_cycle(
        post_result, [reply_confirmed, reply_draft, reply_failed, reply_skipped, reply_uncertain]
    )

    assert {e["kind"] for e in summary["confirmed"]} == {"post", "reply"}
    assert len(summary["draft"]) == 1 and summary["draft"][0]["target_id"] == "2"
    assert len(summary["failed"]) == 1 and summary["failed"][0]["target_id"] == "3"
    assert summary["failed"][0]["detail"] == "GenerationError: scripted failure"
    assert len(summary["skipped"]) == 1 and summary["skipped"][0]["target_id"] == "4"
    assert len(summary["uncertain"]) == 1 and summary["uncertain"][0]["target_id"] == "5"

    # Sanitized: only source/target identifiers, outcome, and detail ever appear -- never a
    # credential or cookie, since run_post_cycle()/run_reply_cycle() never put either into a
    # result dict in the first place (see their 'publish_failed' detail -- an exception type
    # name only, not raw exception text).
    every_key = {key for bucket in summary.values() for entry in bucket for key in entry}
    assert every_key <= {"kind", "source", "url", "target_id", "target_url", "author_handle",
                          "outcome", "detail"}
    print('  summarize_cycle buckets confirmed/draft/failed/skipped/uncertain with '
          'target/source identifiers, sanitized: PASS')


def main() -> None:
    print('RC-109 per-operation failure isolation smoke test (fake driver, no real Chrome)')
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_post_generation_failure_does_not_block_independent_replies(
            os.path.join(tmp_dir, 'post_gen_failure.db'))
        test_reply_generation_failure_does_not_block_later_candidates(
            os.path.join(tmp_dir, 'reply_gen_failure.db'))
        test_post_publish_failure_does_not_block_reply_cycle(
            os.path.join(tmp_dir, 'post_publish_failure.db'))
        test_reply_publish_failure_does_not_block_later_candidates(
            os.path.join(tmp_dir, 'reply_publish_failure.db'))
        test_session_challenge_stops_subsequent_replies(
            os.path.join(tmp_dir, 'session_challenge.db'))
    test_summarize_cycle_buckets_and_identifiers()
    print('\nAll failure-isolation checks passed.')


if __name__ == '__main__':
    main()
