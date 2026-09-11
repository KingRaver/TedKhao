"""RC-101: explicit storage ownership for model-backed voice reviews."""
import argparse
from contextlib import contextmanager
from pathlib import Path
import tempfile


@contextmanager
def review_database(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review-db', help='Retain output in this dedicated review database')
    args = parser.parse_args(argv)
    if args.review_db:
        import config
        selected = Path(args.review_db).resolve()
        operational = {Path(config.DATABASE_PATH).resolve(),
                       (Path(__file__).resolve().parents[1] / 'data/tedkhao.db').resolve()}
        if selected in operational or any(
            selected.exists() and path.exists() and selected.samefile(path)
            for path in operational
        ):
            parser.error('--review-db must not be the operational database')
        yield str(selected)
    else:
        with tempfile.TemporaryDirectory(prefix='tedkhao-review-') as directory:
            yield str(Path(directory) / 'review.db')
