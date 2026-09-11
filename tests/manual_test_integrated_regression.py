"""RC-110 integrated regression: resident multi-cycle driver reuse, a real version-0-to-2
migration, publication-state transitions, repeat-source exclusion, and per-operation failure
isolation, all exercised together against one shared BrowserSession/PersonaMemory across
several bot.py cycles -- as opposed to each earlier RC-10x phase's own isolated fake-driver
fixture. Never launches real Chrome -- browser.get_driver is always patched, matching every
other manual_test_*.py harness's convention.

Included in `venv/bin/python tests/run_offline.py` (RC-101 isolation). Uses plain asserts. Run
standalone with:

    python tests/manual_test_integrated_regression.py
"""
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from selenium.common.exceptions import InvalidSessionIdException, WebDriverException  # noqa: E402

import bot  # noqa: E402
import database  # noqa: E402
from manual_test_bot_cycle import FakeProvider, _FAKE_TIMELINE_SIGNALS  # noqa: E402
from persona.memory import PersonaMemory  # noqa: E402
from persona.state import Register  # noqa: E402
from signals.base import Signal, content_fingerprint, source_key  # noqa: E402
from utils import browser  # noqa: E402
from utils.browser import BrowserSession, PublicationOutcome  # noqa: E402


def no_profile_lock():
    """This offline harness must never touch the real data/browser_profile/ lock file."""
    return (patch.object(browser, '_acquire_profile_lock', return_value=None),
            patch.object(browser, '_release_profile_lock'))


# Two distinct original-post sources (different URLs -> different source_key()), high enough
# novelty_score to always be picked over the low-score reply-candidate signals mixed into the
# same call's pool, so which signal becomes the post stays deterministic.
_DOMAIN_1 = Signal(source="arxiv", domain="technology", title="Integrated regression paper one",
                    summary="A fake abstract for RC-110's combined regression, source one.",
                    url="https://arxiv.org/abs/rc110-fixture-1", novelty_score=0.9,
                    novelty_evidenced=True)
_DOMAIN_2 = Signal(source="arxiv", domain="technology", title="Integrated regression paper two",
                    summary="A fake abstract for RC-110's combined regression, source two.",
                    url="https://arxiv.org/abs/rc110-fixture-2", novelty_score=0.9,
                    novelty_evidenced=True)

_TARGET_A = _FAKE_TIMELINE_SIGNALS[0]  # .../status/1111111111
_TARGET_B = _FAKE_TIMELINE_SIGNALS[1]  # .../status/2222222222


def _reply_target(post_id: str, handle: str) -> Signal:
    return Signal(source="x_timeline", domain="arts", title=f"a fake timeline post ({post_id})",
                  summary=f"a fake timeline post worth replying to ({post_id})",
                  url=f"https://x.com/{handle}/status/{post_id}", novelty_score=0.3)


_TARGET_C = _reply_target("3333333333", "handle_c")  # seeded as a plain, cleanly-failed attempt
_TARGET_E = _reply_target("4444444444", "handle_e")  # publish raises mid-cycle (ordinary failure)
_TARGET_F = _reply_target("5555555555", "handle_f")  # attempted right after E, must still succeed
_TARGET_D = _reply_target("6666666666", "handle_d")  # attempted right after the crash recovery


def test_integrated_multi_cycle_regression() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, 'operational.db')

        # A real pre-migration operational database, exactly the shape a first startup against
        # an old install would see -- not a throwaway copy, since this is the database every
        # cycle below actually runs against.
        with sqlite3.connect(db_path) as conn:
            conn.executescript(database._SCHEMA)
            conn.execute("INSERT INTO posts (post_text,register,phase) VALUES "
                         "('legacy post','amused','quiet')")
            conn.execute("INSERT INTO replied_posts (post_id,reply_content) VALUES "
                         "('old-target','legacy reply')")

        memory = PersonaMemory(db_path=db_path)  # migrates version 0 -> 2 as a side effect
        with sqlite3.connect(db_path) as conn:
            assert conn.execute('PRAGMA user_version').fetchone()[0] == 2
        assert memory.reply_is_held('old-target') and not memory.has_replied('old-target'), (
            'the pre-existing legacy row must survive migration as held-but-unproven'
        )

        session = BrowserSession()
        drivers = []

        def get_driver_side_effect(headless=True):
            driver = Mock()
            drivers.append(driver)
            return driver

        crash_pending = {'active': False}

        def is_logged_in_side_effect(driver):
            if crash_pending['active']:
                crash_pending['active'] = False
                raise InvalidSessionIdException('session gone')
            return True

        post_calls = [0]

        def post_tweet_side_effect(driver, text):
            post_calls[0] += 1
            return PublicationOutcome('confirmed', external_id=f'post-{post_calls[0]}',
                                       external_url=f'https://x.com/tedkhao/status/post{post_calls[0]}')

        def post_reply_side_effect(driver, url, text):
            if url.endswith('4444444444'):
                raise WebDriverException('renderer crashed')
            return PublicationOutcome('confirmed', external_id=f'reply-{url[-4:]}', external_url=url)

        lock_a, lock_b = no_profile_lock()
        provider = FakeProvider()
        with lock_a, lock_b, \
             patch.object(browser, 'get_driver', side_effect=get_driver_side_effect) as get_driver, \
             patch.object(browser, 'is_logged_in', side_effect=is_logged_in_side_effect), \
             patch.object(browser, 'post_tweet', side_effect=post_tweet_side_effect), \
             patch.object(browser, 'post_reply', side_effect=post_reply_side_effect):

            # --- Cycle 1: healthy session, first launch, baseline confirmations -------------
            post1 = bot.run_post_cycle(provider, memory, [_DOMAIN_1], [], live_posting=True,
                                        session=session)
            assert post1['outcome'] == 'confirmed'
            assert get_driver.call_count == 1
            assert session.driver is drivers[0]

            replies1 = bot.run_reply_cycle(provider, memory, [_TARGET_A, _TARGET_B],
                                            live_posting=True, max_replies=10, session=session)
            assert len(replies1) == 2 and all(r['outcome'] == 'confirmed' for r in replies1)
            assert get_driver.call_count == 1, 'no relaunch needed across healthy cycle-1 work'

            # Seed target C as a plain, cleanly-failed earlier attempt (draft -> attempted ->
            # failed, no reconcile needed -- RC-102's ordinary failure path) rather than driving
            # this through mocked exception timing: 'failed' (unlike 'uncertain') stays
            # retry-eligible, which cycle 2 below exercises with a real run_reply_cycle() call.
            pid_c, _ = memory.save_draft('a fake reply for target C', Register.AMUSED,
                                          target={'id': '3333333333', 'author_handle': '@handle_c',
                                                   'text': 'target c text'})
            memory.transition_publication(pid_c, 'attempted')
            memory.transition_publication(pid_c, 'failed')
            assert not memory.reply_is_held('3333333333'), (
                'a cleanly failed attempt must remain retry-eligible, unlike an uncertain one'
            )

            # --- Cycle 2: same session; repeat-source exclusion + retry + failure isolation -
            post2 = bot.run_post_cycle(provider, memory, [_DOMAIN_1], [], live_posting=True,
                                        session=session)
            assert post2['outcome'] == 'skipped'
            assert post2['skipped'] == 'all_candidate_sources_recently_covered'
            assert get_driver.call_count == 1, 'a skipped post must never touch the browser'

            replies2 = bot.run_reply_cycle(
                provider, memory, [_TARGET_A, _TARGET_B, _TARGET_C, _TARGET_E, _TARGET_F],
                live_posting=True, max_replies=10, session=session,
            )
            # A and B are already confirmed/held -> skipped before any browser call; C retries
            # and succeeds; E fails (ordinary, non-crash publish exception); F -- attempted right
            # after E -- still succeeds, proving E's failure did not block it (RC-109).
            by_id = {r['post']['id']: r for r in replies2}
            assert set(by_id) == {'3333333333', '4444444444', '5555555555'}
            assert by_id['3333333333']['outcome'] == 'confirmed'
            assert by_id['4444444444']['outcome'] == 'publish_failed'
            assert by_id['5555555555']['outcome'] == 'confirmed', (
                "target F's success must not be blocked by target E's earlier failure"
            )
            assert get_driver.call_count == 1, (
                "target E's ordinary WebDriverException is not a diagnosed crash -- no relaunch"
            )
            assert database.get_publication(by_id['4444444444']['publication_id'], db_path)['status'] == 'uncertain'

            # --- Cycle 3: evidence of expiry + a diagnosed crash during the re-check; bounded -
            # --- relaunch-and-retry, then immediate reuse of the new driver -------------------
            session.flag_possibly_expired()
            crash_pending['active'] = True
            post3 = bot.run_post_cycle(provider, memory, [_DOMAIN_2], [], live_posting=True,
                                        session=session)
            assert post3['outcome'] == 'confirmed'
            assert get_driver.call_count == 2, 'exactly one relaunch after the diagnosed crash'
            assert session.driver is drivers[1], 'the session must now be using the relaunched driver'
            assert not crash_pending['active'], 'the crash must actually have been triggered'

            replies3 = bot.run_reply_cycle(provider, memory, [_TARGET_D], live_posting=True,
                                            max_replies=10, session=session)
            assert replies3[0]['outcome'] == 'confirmed'
            assert get_driver.call_count == 2, 'the relaunched driver is reused, not relaunched again'

        session.close()
        assert drivers[0].quit.call_count == 1 and drivers[1].quit.call_count == 1, (
            'close() must quit exactly the driver the session currently owns, once'
        )

        row1 = database.get_publication(post1['publication_id'], db_path)
        assert row1['status'] == 'confirmed' and row1['source_url'] == _DOMAIN_1.url
        row3 = database.get_publication(post3['publication_id'], db_path)
        assert row3['status'] == 'confirmed' and row3['source_url'] == _DOMAIN_2.url

        # --- Restart: a fresh PersonaMemory against the same already-migrated database must see
        # --- every publication-state transition above without redoing any cycle logic ---------
        restarted = PersonaMemory(db_path=db_path)
        assert restarted.reply_is_held('old-target') and not restarted.has_replied('old-target')
        for target_id, confirmed in (
            ('1111111111', True), ('2222222222', True), ('3333333333', True),
            ('4444444444', False), ('5555555555', True), ('6666666666', True),
        ):
            assert restarted.reply_is_held(target_id), f'{target_id} must remain held after restart'
            assert restarted.has_replied(target_id) is confirmed, (
                f'{target_id} confirmed status must survive restart exactly as it was'
            )

        covered = restarted.covered_source_keys()
        assert (source_key(_DOMAIN_1), content_fingerprint(_DOMAIN_1)) in covered
        assert (source_key(_DOMAIN_2), content_fingerprint(_DOMAIN_2)) in covered

        print('  legacy migration, resident multi-cycle driver reuse, bounded crash recovery, '
              'publication-state transitions, repeat-source exclusion, and per-operation '
              'failure isolation, all verified together across restart: PASS')


def main() -> None:
    print('RC-110 integrated multi-cycle regression (fake driver, no real Chrome)')
    test_integrated_multi_cycle_regression()
    print('\nAll integrated regression checks passed.')


if __name__ == '__main__':
    main()
