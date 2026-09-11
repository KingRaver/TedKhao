"""RC-102 deterministic lifecycle, transaction, and copied legacy migration checks.

RC-103: publish() takes a shared utils.browser.BrowserSession instead of managing its own
driver, and never quits it -- these tests patch browser.get_driver/is_logged_in the way they
previously patched a per-call driver, and stub out the real profile-lock file (a filesystem
side effect this offline harness must not perform) the same way run_offline.py already blocks
network/subprocess access.
"""
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

import database
import bot
from engagement.publication import PublicationOutcome, publish
from persona.memory import PersonaMemory
from persona.state import Register
from manual_test_bot_cycle import FakeProvider, _FAKE_TIMELINE_SIGNALS, _FAKE_DOMAIN_SIGNALS
from utils import browser
from utils.browser import BrowserSession


def expect_error(call, error=Exception):
    try:
        call()
    except error:
        return
    raise AssertionError('Expected failure')


def no_profile_lock():
    """This offline harness must never touch the real data/browser_profile/ lock file."""
    return (patch.object(browser, '_acquire_profile_lock', return_value=None),
            patch.object(browser, '_release_profile_lock'))


def test_lifecycle(path):
    memory = PersonaMemory(db_path=path)
    signals = _FAKE_TIMELINE_SIGNALS[:1]
    target = '1111111111'
    dry = bot.run_reply_cycle(FakeProvider(), memory, signals, False, 1)[0]
    row = database.get_publication(dry['publication_id'], path)
    assert row['status'] == 'draft' and row['attempted_at'] is None
    assert row['confirmed_at'] is None and row['target_url'] == signals[0].url
    assert not memory.reply_is_held(target)

    # One session, reused for the rest of this test, matching how bot.main() owns exactly one
    # BrowserSession across every cycle rather than relaunching a driver per publish() call.
    session = BrowserSession()
    lock_a, lock_b = no_profile_lock()
    # RC-109: an individual candidate's publish exception is now isolated (outcome=
    # 'publish_failed') rather than raised out of run_reply_cycle -- the durable DB state and
    # driver lifecycle this test actually verifies are unaffected, only how the failure
    # surfaces to the caller changed.
    with lock_a, lock_b, patch.object(browser, 'get_driver', side_effect=RuntimeError('launch failed')):
        failed = bot.run_reply_cycle(FakeProvider(), memory, signals, True, 1, session)[0]
    assert failed['outcome'] == 'publish_failed'
    assert not PersonaMemory(db_path=path).reply_is_held(target)
    with database._connect(path) as conn:
        assert conn.execute('SELECT status FROM publications ORDER BY id DESC').fetchone()[0] == 'failed'
    assert session.driver is None, 'a failed launch must not leave a half-open driver on the session'

    driver = Mock()
    lock_a, lock_b = no_profile_lock()
    with lock_a, lock_b, \
         patch.object(browser, 'get_driver', return_value=driver), \
         patch.object(browser, 'is_logged_in', return_value=True), \
         patch.object(browser, 'post_reply', return_value=PublicationOutcome(
             'confirmed', external_id='external-1', external_url='https://x.com/ted/status/external-1')):
        live = bot.run_reply_cycle(FakeProvider(), memory, signals, True, 1, session)[0]
    row = database.get_publication(live['publication_id'], path)
    assert row['attempted_at'] and row['confirmed_at'] and row['external_id'] == 'external-1'
    assert memory.has_replied(target) and database.has_replied(target, path)
    restarted = PersonaMemory(db_path=path)
    assert restarted.has_replied(target)
    # Already-held target: the loop skips before touching the browser, so this runs outside
    # any browser patch -- proving a covered target never triggers a session/driver call.
    assert bot.run_reply_cycle(FakeProvider(), restarted, signals, True, 1, session) == []
    # An older draft cannot bypass the target-level hold.
    expect_error(lambda: memory.transition_publication(dry['publication_id'], 'attempted'), ValueError)
    assert session.driver is driver, 'the session must keep reusing the same driver, not relaunch'
    assert driver.quit.call_count == 0, 'publish() must never quit a driver it does not own'
    session.close()
    assert driver.quit.call_count == 1, 'close() must quit the shared driver exactly once'
    print('  dry-run -> live, pre-submission failure, confirmation, restart, duplicate hold, '
          'shared driver identity, no per-action quit: PASS')


def test_uncertainty(path):
    memory = PersonaMemory(db_path=path)
    signals = _FAKE_TIMELINE_SIGNALS[:1]
    session = BrowserSession()
    lock_a, lock_b = no_profile_lock()
    with lock_a, lock_b, \
         patch.object(browser, 'get_driver', return_value=Mock()), \
         patch.object(browser, 'is_logged_in', return_value=True), \
         patch.object(browser, 'post_reply', return_value=None):
        result = bot.run_reply_cycle(FakeProvider(), memory, signals, True, 1, session)[0]
    pid = result['publication_id']
    assert database.get_publication(pid, path)['status'] == 'uncertain'
    assert not memory.has_replied('1111111111')
    assert PersonaMemory(db_path=path).reply_is_held('1111111111')
    expect_error(lambda: memory.transition_publication(pid, 'attempted'), ValueError)
    memory.transition_publication(pid, 'failed', reconcile=True, detail='Fixture confirms no submission')
    assert not memory.reply_is_held('1111111111')
    memory.transition_publication(pid, 'attempted')
    assert PersonaMemory(db_path=path).reply_is_held('1111111111')
    memory.transition_publication(pid, 'uncertain', detail='Simulated crash after submission')
    memory.transition_publication(pid, 'confirmed', reconcile=True, detail='Found fixture publication',
                                  external_id='found')
    assert memory.has_replied('1111111111')
    # Exception inside submission is also ambiguous. The session already has a driver and a
    # verified auth check from above, so only post_reply needs patching here -- proving
    # ensure_ready() does not repeat the login check on every action. RC-109: this failure is
    # now isolated (outcome='publish_failed') rather than raised out of run_reply_cycle -- what
    # this test actually verifies is publish()'s own durable 'uncertain' state (row status,
    # held target), not whether the exception propagates.
    with patch.object(browser, 'post_reply', side_effect=TimeoutError):
        uncertain = bot.run_reply_cycle(
            FakeProvider(), memory, _FAKE_TIMELINE_SIGNALS[1:2], True, 1, session)[0]
    assert uncertain['outcome'] == 'publish_failed'
    assert database.get_publication(uncertain['publication_id'], path)['status'] == 'uncertain'
    assert PersonaMemory(db_path=path).reply_is_held('2222222222')
    session.close()
    print('  click-only result, submission exception, crash hold, explicit reconciliation, '
          'no repeated auth check: PASS')


def test_atomicity(path):
    memory = PersonaMemory(db_path=path)
    with database._connect(path) as conn:
        conn.execute("CREATE TRIGGER fail_draft BEFORE INSERT ON publications "
                     "BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
    expect_error(lambda: bot.run_post_cycle(FakeProvider(), memory, _FAKE_DOMAIN_SIGNALS, [], False),
                 sqlite3.IntegrityError)
    assert memory.recent_registers == [] and memory.recent_phases == []
    with database._connect(path) as conn:
        for table in ('signals','posts','state_history','publications'):
            assert conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == 0
        conn.execute('DROP TRIGGER fail_draft')
    pid, _ = memory.save_draft('reply', Register.AMUSED, target={'id': 'atomic'})
    memory.transition_publication(pid, 'attempted')
    with database._connect(path) as conn:
        conn.execute("CREATE TRIGGER fail_confirmation BEFORE INSERT ON replied_posts "
                     "BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
    expect_error(lambda: memory.transition_publication(pid, 'confirmed', external_id='proof'),
                 sqlite3.IntegrityError)
    assert not memory.has_replied('atomic')
    assert database.get_publication(pid, path)['status'] == 'attempted'
    with database._connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM publication_events WHERE status='confirmed'").fetchone()[0] == 0
    assert PersonaMemory(db_path=path).reply_is_held('atomic')
    # Persistence failure before an attempt must prevent browser access.
    pid, _ = memory.save_draft('reply', Register.AMUSED, target={'id': 'other'})
    session = BrowserSession()
    with patch.object(database, 'transition_publication', side_effect=sqlite3.OperationalError), \
         patch.object(browser, 'get_driver') as launch:
        expect_error(lambda: publish({'publication_id': pid}, memory, session), sqlite3.OperationalError)
        launch.assert_not_called()
    print('  generation rollback, confirmation rollback, memory ordering, pre-browser durability: PASS')


def test_post(path):
    memory = PersonaMemory(db_path=path)
    draft = bot.run_post_cycle(FakeProvider(), memory, _FAKE_DOMAIN_SIGNALS, [], False)
    with database._connect(path) as conn:
        assert conn.execute('SELECT posted_at FROM posts').fetchone()[0] is None
        assert conn.execute('SELECT used_at FROM signals').fetchone()[0] is None
    memory.transition_publication(draft['publication_id'], 'attempted')
    memory.transition_publication(draft['publication_id'], 'confirmed', external_url='https://x.com/ted/status/1')
    with database._connect(path) as conn:
        assert conn.execute('SELECT posted_at FROM posts').fetchone()[0]
        assert conn.execute('SELECT used_at FROM signals').fetchone()[0]
    print('  original-post timestamps and signal use only on confirmation: PASS')


def test_live_posting_requires_session(path):
    memory = PersonaMemory(db_path=path)
    expect_error(lambda: bot.run_post_cycle(
        FakeProvider(), memory, _FAKE_DOMAIN_SIGNALS, [], True), ValueError)
    expect_error(lambda: bot.run_reply_cycle(
        FakeProvider(), memory, _FAKE_TIMELINE_SIGNALS[:1], True, 1), ValueError)
    print('  live_posting without a BrowserSession is rejected: PASS')


def test_migration(root):
    legacy = str(root / 'legacy.db')
    with sqlite3.connect(legacy) as conn:
        conn.executescript(database._SCHEMA)
        conn.execute("INSERT INTO posts (post_text,register,phase) VALUES ('old','amused','quiet')")
        conn.execute("INSERT INTO replied_posts (post_id,reply_content) VALUES ('old-target','old reply')")
    before = Path(legacy).read_bytes()
    copied = str(root / 'copy.db')
    shutil.copy2(legacy, copied)
    database.init_db(copied)
    database.init_db(copied)
    with sqlite3.connect(copied) as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0] == 2
        assert conn.execute('SELECT COUNT(*) FROM publications').fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM publications WHERE status='legacy_unknown'").fetchone()[0] == 2
        # RC-107: legacy rows get no guessed source identity (see docs/PUBLICATION_MIGRATION.md).
        assert conn.execute("SELECT COUNT(*) FROM publications WHERE source_url IS NOT NULL").fetchone()[0] == 0
        assert conn.execute('SELECT post_text FROM posts').fetchone()[0] == 'old'
        assert conn.execute('SELECT reply_content FROM replied_posts').fetchone()[0] == 'old reply'
    memory = PersonaMemory(db_path=copied)
    assert memory.reply_is_held('old-target') and not memory.has_replied('old-target')
    with sqlite3.connect(legacy) as old, sqlite3.connect(copied) as new:
        for table in ('signals', 'state_history', 'posts', 'replied_posts'):
            assert old.execute(f'SELECT * FROM {table}').fetchall() == new.execute(f'SELECT * FROM {table}').fetchall()
    assert Path(legacy).read_bytes() == before
    # Restore the backup to a different fixture path and verify old schema/data.
    restored = str(root / 'restored.db')
    shutil.copy2(legacy, restored)
    with sqlite3.connect(restored) as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0] == 0
        assert conn.execute('SELECT post_id FROM replied_posts').fetchone()[0] == 'old-target'
    # Failed migration is transactional, including DDL and version.
    broken = str(root / 'broken.db')
    shutil.copy2(legacy, broken)
    with patch.object(database, '_PUBLICATION_SCHEMA', database._PUBLICATION_SCHEMA + '; INVALID SQL'):
        expect_error(lambda: database.init_db(broken), sqlite3.OperationalError)
    with sqlite3.connect(broken) as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0] == 0
        assert not conn.execute("SELECT name FROM sqlite_master WHERE name='publications'").fetchone()
    print('  copied legacy migration, idempotence, preservation, rollback and restore: PASS')


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for test in (test_lifecycle, test_uncertainty, test_atomicity, test_post,
                     test_live_posting_requires_session):
            test(str(root / (test.__name__ + '.db')))
        test_migration(root)
    print('RC-102/RC-103 publication lifecycle and browser session ownership: PASS')


if __name__ == '__main__':
    main()
