"""RC-103 fake-driver checks for utils.browser.BrowserSession and its callers: one launch
across multiple cycles, shared driver identity, no per-action quit() calls, bounded crash
recovery, and clean shutdown on interruption. Never launches real Chrome -- browser.get_driver
is always patched.

Included in `venv/bin/python tests/run_offline.py` (RC-101 isolation). Uses plain asserts.
Run standalone with:

    python tests/manual_test_browser_session.py
"""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from selenium.common.exceptions import InvalidSessionIdException  # noqa: E402

import bot  # noqa: E402
from engagement.publication import publish  # noqa: E402
from persona.memory import PersonaMemory  # noqa: E402
from persona.state import Phase, Register  # noqa: E402
from signals import timeline_scraper  # noqa: E402
from utils import browser  # noqa: E402
from utils.browser import BrowserSession, SessionPaused  # noqa: E402


def no_profile_lock():
    """This offline harness must never touch the real data/browser_profile/ lock file."""
    return (patch.object(browser, '_acquire_profile_lock', return_value=None),
            patch.object(browser, '_release_profile_lock'))


def fake_driver():
    return Mock()


def test_one_launch_across_multiple_cycles():
    session = BrowserSession()
    driver = fake_driver()
    lock_a, lock_b = no_profile_lock()
    with lock_a, lock_b, \
         patch.object(browser, 'get_driver', return_value=driver) as launch, \
         patch.object(browser, 'is_logged_in', return_value=True):
        for _ in range(5):
            session.ensure_ready()
    assert launch.call_count == 1, 'ensure_ready() must not relaunch an already-open driver'
    assert session.driver is driver
    session.close()
    assert driver.quit.call_count == 1
    print('  one launch across 5 cycles, shared driver identity: PASS')


def test_auth_checked_once_until_flagged():
    session = BrowserSession()
    lock_a, lock_b = no_profile_lock()
    with lock_a, lock_b, \
         patch.object(browser, 'get_driver', return_value=fake_driver()), \
         patch.object(browser, 'is_logged_in', return_value=True) as check:
        session.ensure_ready()
        session.ensure_ready()
        session.ensure_ready()
        assert check.call_count == 1, 'ensure_ready() must not repeat the login check every action'
        session.flag_possibly_expired()
        session.ensure_ready()
        assert check.call_count == 2, 'flag_possibly_expired() must force the next check'
    session.close()
    print('  auth checked at startup and only after flag_possibly_expired(), not every action: PASS')


def test_headless_session_pauses_instead_of_auto_login():
    session = BrowserSession(headless=True)
    lock_a, lock_b = no_profile_lock()
    with lock_a, lock_b, \
         patch.object(browser, 'get_driver', return_value=fake_driver()), \
         patch.object(browser, 'is_logged_in', return_value=False), \
         patch.object(browser, 'log_in') as auto_login:
        try:
            session.ensure_ready()
            raise AssertionError('expected SessionPaused')
        except SessionPaused:
            pass
        assert auto_login.call_count == 0, 'a headless session must never retry login automatically'
    session.close()
    print('  headless session with no valid login raises SessionPaused, never auto-retries login: PASS')


def test_publish_never_quits_the_shared_driver():
    session = BrowserSession()
    driver = fake_driver()
    lock_a, lock_b = no_profile_lock()
    with tempfile.TemporaryDirectory() as tmp:
        memory = PersonaMemory(db_path=os.path.join(tmp, 'session.db'))
        pid, _ = memory.save_draft('a fake post for session testing', Register.AMUSED, phase=Phase.QUIET)
        with lock_a, lock_b, \
             patch.object(browser, 'get_driver', return_value=driver), \
             patch.object(browser, 'is_logged_in', return_value=True), \
             patch.object(browser, 'post_tweet', return_value=None):
            publish({'publication_id': pid, 'post_text': 'a fake post for session testing'}, memory, session)
    assert driver.quit.call_count == 0, 'publish() must never call quit() on a driver it does not own'
    session.close()
    assert driver.quit.call_count == 1
    print('  publish() reuses the session driver and never quits it: PASS')


def test_bounded_crash_recovery():
    session = BrowserSession()
    lock_a, lock_b = no_profile_lock()
    crashed_once = [False]

    def action():
        if not crashed_once[0]:
            crashed_once[0] = True
            raise InvalidSessionIdException('session gone')
        return 'ok'

    with lock_a, lock_b, \
         patch.object(browser, 'get_driver', return_value=fake_driver()), \
         patch.object(browser, 'is_logged_in', return_value=True):
        session.ensure_ready()
        assert bot._with_crash_recovery(session, action) == 'ok'
    session.close()
    print('  one diagnosed crash triggers exactly one relaunch-and-retry: PASS')

    session2 = BrowserSession()
    lock_a, lock_b = no_profile_lock()

    def always_crashes():
        raise InvalidSessionIdException('still gone')

    with lock_a, lock_b, \
         patch.object(browser, 'get_driver', return_value=fake_driver()), \
         patch.object(browser, 'is_logged_in', return_value=True):
        session2.ensure_ready()
        try:
            bot._with_crash_recovery(session2, always_crashes)
            raise AssertionError('expected InvalidSessionIdException to propagate')
        except InvalidSessionIdException:
            pass
    session2.close()
    print('  a second crash in the same call propagates rather than looping indefinitely: PASS')


def test_clean_shutdown_on_interruption():
    """Stands in for bot.main()'s outer try/finally around KeyboardInterrupt: the driver must
    close exactly once even when the loop body is interrupted rather than returning normally."""
    session = BrowserSession()
    driver = fake_driver()
    lock_a, lock_b = no_profile_lock()
    with lock_a, lock_b, \
         patch.object(browser, 'get_driver', return_value=driver), \
         patch.object(browser, 'is_logged_in', return_value=True):
        session.ensure_ready()
        try:
            try:
                raise KeyboardInterrupt()
            finally:
                session.close()
        except KeyboardInterrupt:
            pass
    assert driver.quit.call_count == 1
    assert session.driver is None
    session.close()  # idempotent -- a second close() must not error or re-quit
    assert driver.quit.call_count == 1
    print('  interruption still closes the driver exactly once, close() is idempotent: PASS')


def test_timeline_fetch_reuses_injected_session():
    session = BrowserSession()
    driver = fake_driver()
    driver.find_elements.return_value = []
    lock_a, lock_b = no_profile_lock()
    with lock_a, lock_b, \
         patch.object(browser, 'get_driver', return_value=driver), \
         patch.object(browser, 'is_logged_in', return_value=True):
        signals = timeline_scraper.fetch(session)
    assert signals == []
    assert driver.quit.call_count == 0, 'timeline fetch must not quit the shared driver'
    session.close()
    print('  timeline_scraper.fetch() reuses the injected session driver, never quits it: PASS')


def test_fetch_all_signals_degrades_on_paused_session():
    """A paused/unauthenticated session must not kill dry-run post generation, which is the
    default state whenever TWITTER_USERNAME/TWITTER_PASSWORD are unset -- the timeline fetch
    degrades to an empty result instead of raising. Live posting's own pause behavior is
    covered separately by test_publish_session_paused_propagates_to_run_cycle()."""
    session = BrowserSession(headless=True)
    lock_a, lock_b = no_profile_lock()
    with lock_a, lock_b, \
         patch.object(browser, 'get_driver', return_value=fake_driver()), \
         patch.object(browser, 'is_logged_in', return_value=False), \
         patch.object(bot, '_DOMAIN_SIGNAL_SOURCES', []):
        domain_signals, timeline_signals = bot.fetch_all_signals(session)
    assert domain_signals == [] and timeline_signals == []
    session.close()
    print('  fetch_all_signals() degrades to an empty timeline on a paused session instead of '
          'raising: PASS')


def test_publish_session_paused_propagates_to_run_cycle():
    """Live posting is where a paused session must actually stop X actions: publish() calling
    session.ensure_ready() on a headless session with no valid login raises SessionPaused,
    and that propagates out of run_post_cycle() rather than being swallowed."""
    from manual_test_bot_cycle import FakeProvider, _FAKE_DOMAIN_SIGNALS
    from persona.memory import PersonaMemory

    session = BrowserSession(headless=True)
    lock_a, lock_b = no_profile_lock()
    with tempfile.TemporaryDirectory() as tmp:
        memory = PersonaMemory(db_path=os.path.join(tmp, 'paused.db'))
        with lock_a, lock_b, \
             patch.object(browser, 'get_driver', return_value=fake_driver()), \
             patch.object(browser, 'is_logged_in', return_value=False), \
             patch.object(browser, 'log_in') as auto_login:
            try:
                bot.run_post_cycle(FakeProvider(), memory, _FAKE_DOMAIN_SIGNALS, [],
                                    live_posting=True, session=session)
                raise AssertionError('expected SessionPaused to propagate out of run_post_cycle')
            except SessionPaused:
                pass
            assert auto_login.call_count == 0
    session.close()
    print('  a paused session propagates out of run_post_cycle() and never auto-retries login: PASS')


def main():
    print('RC-103 browser session ownership smoke test (fake driver, no real Chrome)')
    test_one_launch_across_multiple_cycles()
    test_auth_checked_once_until_flagged()
    test_headless_session_pauses_instead_of_auto_login()
    test_publish_never_quits_the_shared_driver()
    test_bounded_crash_recovery()
    test_clean_shutdown_on_interruption()
    test_timeline_fetch_reuses_injected_session()
    test_fetch_all_signals_degrades_on_paused_session()
    test_publish_session_paused_propagates_to_run_cycle()
    print('\nAll browser session checks passed.')


if __name__ == '__main__':
    main()
