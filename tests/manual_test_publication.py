"""RC-102 deterministic lifecycle, transaction, and copied legacy migration checks."""
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

import database
import bot
from engagement.publication import PublicationOutcome
from persona.memory import PersonaMemory
from persona.state import Register
from manual_test_bot_cycle import FakeProvider, _FAKE_TIMELINE_SIGNALS, _FAKE_DOMAIN_SIGNALS
from utils import browser


def expect_error(call, error=Exception):
    try:
        call()
    except error:
        return
    raise AssertionError('Expected failure')


def test_lifecycle(path):
    memory = PersonaMemory(db_path=path)
    signals = _FAKE_TIMELINE_SIGNALS[:1]
    target = '1111111111'
    dry = bot.run_reply_cycle(FakeProvider(), memory, signals, False, 1)[0]
    row = database.get_publication(dry['publication_id'], path)
    assert row['status'] == 'draft' and row['attempted_at'] is None
    assert row['confirmed_at'] is None and row['target_url'] == signals[0].url
    assert not memory.reply_is_held(target)
    with patch.object(browser, 'get_driver', side_effect=RuntimeError('launch failed')):
        expect_error(lambda: bot.run_reply_cycle(FakeProvider(), memory, signals, True, 1))
    assert not PersonaMemory(db_path=path).reply_is_held(target)
    with database._connect(path) as conn:
        assert conn.execute('SELECT status FROM publications ORDER BY id DESC').fetchone()[0] == 'failed'
    driver = Mock()
    with patch.object(browser, 'get_driver', return_value=driver), \
         patch.object(browser, 'ensure_logged_in'), \
         patch.object(browser, 'post_reply', return_value=PublicationOutcome(
             'confirmed', external_id='external-1', external_url='https://x.com/ted/status/external-1')):
        live = bot.run_reply_cycle(FakeProvider(), memory, signals, True, 1)[0]
    row = database.get_publication(live['publication_id'], path)
    assert row['attempted_at'] and row['confirmed_at'] and row['external_id'] == 'external-1'
    assert memory.has_replied(target) and database.has_replied(target, path)
    restarted = PersonaMemory(db_path=path)
    assert restarted.has_replied(target)
    assert bot.run_reply_cycle(FakeProvider(), restarted, signals, True, 1) == []
    # An older draft cannot bypass the target-level hold.
    expect_error(lambda: memory.transition_publication(dry['publication_id'], 'attempted'), ValueError)
    assert driver.quit.call_count == 1
    print('  dry-run -> live, pre-submission failure, confirmation, restart and duplicate hold: PASS')


def test_uncertainty(path):
    memory = PersonaMemory(db_path=path)
    signals = _FAKE_TIMELINE_SIGNALS[:1]
    with patch.object(browser, 'get_driver', return_value=Mock()), \
         patch.object(browser, 'ensure_logged_in'), \
         patch.object(browser, 'post_reply', return_value=None):
        result = bot.run_reply_cycle(FakeProvider(), memory, signals, True, 1)[0]
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
    # Exception inside submission is also ambiguous.
    with patch.object(browser, 'get_driver', return_value=Mock()), \
         patch.object(browser, 'ensure_logged_in'), \
         patch.object(browser, 'post_reply', side_effect=TimeoutError):
        expect_error(lambda: bot.run_reply_cycle(
            FakeProvider(), memory, _FAKE_TIMELINE_SIGNALS[1:2], True, 1))
    assert PersonaMemory(db_path=path).reply_is_held('2222222222')
    print('  click-only result, submission exception, crash hold and explicit reconciliation: PASS')


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
    from engagement.publication import publish
    with patch.object(database, 'transition_publication', side_effect=sqlite3.OperationalError), \
         patch.object(browser, 'get_driver') as launch:
        expect_error(lambda: publish({'publication_id': pid}, memory), sqlite3.OperationalError)
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
        assert conn.execute('PRAGMA user_version').fetchone()[0] == 1
        assert conn.execute('SELECT COUNT(*) FROM publications').fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM publications WHERE status='legacy_unknown'").fetchone()[0] == 2
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
        for test in (test_lifecycle, test_uncertainty, test_atomicity, test_post):
            test(str(root / (test.__name__ + '.db')))
        test_migration(root)
    print('RC-102 publication lifecycle: PASS')


if __name__ == '__main__':
    main()
