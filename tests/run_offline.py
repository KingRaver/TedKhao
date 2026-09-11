"""RC-101 offline regression entry point; never imports live harnesses implicitly."""
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


def forbidden(*args, **kwargs):
    raise AssertionError('Offline checks attempted network, browser, or process access')


def main():
    if not __debug__:
        raise RuntimeError('Run without -O: regression checks use assertions')
    # Disable dotenv before importing any application module. No credentials are needed.
    import dotenv
    with tempfile.TemporaryDirectory(prefix='tedkhao-offline-') as directory:
        root = Path(directory).resolve()
        connect = sqlite3.connect

        def isolated_connect(path, *args, **kwargs):
            assert Path(path).resolve().is_relative_to(root), 'Database escaped test directory'
            return connect(path, *args, **kwargs)

        with patch.dict(os.environ, {'DATABASE_PATH': str(root / 'operational.db')}, clear=True), \
             patch.object(dotenv, 'load_dotenv', return_value=False), \
             patch('socket.socket.connect', forbidden), \
             patch('socket.socket.connect_ex', forbidden), \
             patch('socket.create_connection', forbidden), \
             patch('subprocess.Popen', forbidden), \
             patch('sqlite3.connect', isolated_connect), \
             patch.object(tempfile, 'tempdir', directory):
            import config
            import manual_test_persistence as persistence
            import manual_test_bot_cycle as cycle
            import manual_test_posts as posts
            import manual_test_replies as replies
            import llm_provider
            from utils import browser
            assert not config.ANTHROPIC_API_KEY and not config.TWITTER_PASSWORD
            with patch.object(browser, 'get_driver', forbidden), \
                 patch.object(llm_provider, 'get_provider', forbidden):
                persistence.main()
                cycle.main()
                for harness, table, expected in ((posts, 'posts', len(posts.SCENARIOS)),
                                                  (replies, 'replied_posts', len(replies.FAKE_POSTS))):
                    paths = []
                    real_memory = harness.PersonaMemory

                    def memory(**kwargs):
                        paths.append(kwargs['db_path'])
                        return real_memory(**kwargs)

                    with patch.object(harness, 'get_provider', return_value=persistence.FakeProvider()), \
                         patch.object(harness, 'PersonaMemory', side_effect=memory):
                        harness.main([])
                        assert not Path(paths[-1]).exists(), 'Temporary review DB was retained'
                        retained = root / (table + '.db')
                        harness.main(['--review-db', str(retained)])
                        with connect(retained) as conn:
                            assert conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == expected
                        try:
                            harness.main(['--review-db', config.DATABASE_PATH])
                        except SystemExit as error:
                            assert error.code == 2
                        else:
                            raise AssertionError('Operational review path was accepted')
                    print(f'{harness.__name__}: temporary cleanup, retained rows, operational rejection PASS')
                assert not Path(config.DATABASE_PATH).exists()
    print('PASS: persistence, cycle, and review isolation; credentials/network/browser blocked')


if __name__ == '__main__':
    main()
