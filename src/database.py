"""SQLite schema + access layer -- docs/SPEC.md's Data Models section, table shapes mirrored
as closely as possible.

Every function opens its own short-lived connection rather than holding one open across the
process -- this matches the project's small, single-writer scale (one bot process) and avoids
cross-thread/connection-lifetime bookkeeping a long-lived pool would need. init_db() is
idempotent and applies the versioned RC-102 migration transactionally. PersonaMemory
calls it on construction; back up existing operational databases before first startup.

One deviation from docs/SPEC.md's schema snippet: `state_history.phase` is nullable here,
not NOT NULL. The reply path (persona.state.select_register_for_reply) only ever produces a
Register -- there is no Phase concept for a reply, so a reply-triggered state_history row has
no phase to record. The post-generation path (select_phase_register_and_signal) always has
both and populates phase normally.
"""
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    domain TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT,
    url TEXT,
    novelty_score REAL,
    fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
    used_at TEXT
);

CREATE TABLE IF NOT EXISTS state_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    register TEXT NOT NULL,
    phase TEXT,
    triggering_signal_id INTEGER REFERENCES signals(id),
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_text TEXT NOT NULL,
    register TEXT NOT NULL,
    phase TEXT NOT NULL,
    signal_id INTEGER REFERENCES signals(id),
    posted_at TEXT DEFAULT CURRENT_TIMESTAMP,
    engagement_likes INTEGER DEFAULT 0,
    engagement_replies INTEGER DEFAULT 0,
    engagement_reposts INTEGER DEFAULT 0,
    engagement_checked_at TEXT
);

CREATE TABLE IF NOT EXISTS replied_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id TEXT UNIQUE NOT NULL,
    post_author TEXT,
    post_content TEXT,
    reply_content TEXT,
    register TEXT,
    replied_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


@contextmanager
def _connect(db_path: Optional[str] = None):
    path = db_path or config.DATABASE_PATH
    dirname = os.path.dirname(path)
    if dirname:
        os.makedirs(dirname, exist_ok=True)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Optional[str] = None) -> None:
    with _connect(db_path) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version > 2:
            raise RuntimeError("Database schema is newer than this application")
        conn.execute("BEGIN IMMEDIATE")
        for statement in _SCHEMA.split(";"):
            if statement.strip():
                conn.execute(statement)
        for statement in _PUBLICATION_SCHEMA.split(";"):
            if statement.strip():
                conn.execute(statement)
        if version == 0:
            conn.execute("INSERT INTO publications (kind, content, register, phase, post_row_id, "
                         "status, created_at) SELECT 'post', post_text, register, phase, id, "
                         "'legacy_unknown', posted_at FROM posts")
            conn.execute("INSERT INTO publications (kind, content, register, target_id, "
                         "target_author, target_content, status, created_at) "
                         "SELECT 'reply', reply_content, register, post_id, post_author, "
                         "post_content, 'legacy_unknown', replied_at FROM replied_posts")
            version = 1
        if version == 1:
            # RC-107: add source_url/source_fingerprint to a publications table that may
            # already exist from schema version 1 (CREATE TABLE IF NOT EXISTS above is a
            # no-op there) -- ALTER TABLE only when the column isn't already present, so this
            # stays idempotent whether starting from version 0 or 1. Existing legacy_unknown
            # rows are left with NULL source_url/source_fingerprint rather than guessed at via
            # a posts/signals join: same "retain as legacy/unknown, don't invent proof" stance
            # RC-102's migration took, so they're simply excluded from coverage matching below
            # rather than incorrectly blocking (or failing to block) a real source.
            existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(publications)")}
            if "source_url" not in existing_columns:
                conn.execute("ALTER TABLE publications ADD COLUMN source_url TEXT")
            if "source_fingerprint" not in existing_columns:
                conn.execute("ALTER TABLE publications ADD COLUMN source_fingerprint TEXT")
            conn.execute("CREATE INDEX IF NOT EXISTS publication_source "
                         "ON publications(source_url, status)")
            version = 2
        conn.execute(f"PRAGMA user_version = {version}")


def insert_signal(signal, db_path: Optional[str] = None) -> int:
    """signal: a signals.base.Signal. Typed loosely here to avoid database.py depending on
    signals/ beyond this one call shape."""
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO signals (source, domain, title, summary, url, novelty_score, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (signal.source, signal.domain, signal.title, signal.summary, signal.url,
             signal.novelty_score, signal.fetched_at.isoformat()),
        )
        return cur.lastrowid


def mark_signal_used(signal_id: int, db_path: Optional[str] = None) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE signals SET used_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), signal_id),
        )


def insert_state_history(register: str, phase: Optional[str] = None,
                          triggering_signal_id: Optional[int] = None,
                          timestamp: Optional[str] = None,
                          db_path: Optional[str] = None) -> int:
    ts = timestamp or datetime.now(timezone.utc).isoformat()
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO state_history (timestamp, register, phase, triggering_signal_id) "
            "VALUES (?, ?, ?, ?)",
            (ts, register, phase, triggering_signal_id),
        )
        return cur.lastrowid


def insert_post(post_text: str, register: str, phase: str, signal_id: Optional[int] = None,
                 db_path: Optional[str] = None) -> int:
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO posts (post_text, register, phase, signal_id, posted_at) VALUES (?, ?, ?, ?, NULL)",
            (post_text, register, phase, signal_id),
        )
        return cur.lastrowid


def insert_replied_post(post_id: str, post_author: Optional[str], post_content: Optional[str],
                         reply_content: Optional[str], register: Optional[str] = None,
                         db_path: Optional[str] = None) -> int:
    """Compatibility writer: retain generated reply text as a draft, never as success."""
    return save_draft(reply_content, register, target={
        'id': post_id, 'author_handle': post_author, 'text': post_content},
        db_path=db_path)[0]


def has_replied(post_id: str, db_path: Optional[str] = None) -> bool:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM publications WHERE target_id = ? AND status = 'confirmed'", (post_id,)
        ).fetchone()
    return row is not None


def get_recent_registers(limit: int, db_path: Optional[str] = None) -> list[str]:
    """Oldest-first, matching how persona.memory.PersonaMemory builds its in-memory list by
    appending -- so callers can slice both the same way ([-N:] for "most recent N")."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT register FROM state_history ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [row["register"] for row in reversed(rows)]


def get_recent_phases(limit: int, db_path: Optional[str] = None) -> list[str]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT phase FROM state_history WHERE phase IS NOT NULL "
            "ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [row["phase"] for row in reversed(rows)]


def get_replied_post_ids(db_path: Optional[str] = None) -> set[str]:
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT target_id AS post_id FROM publications WHERE kind = 'reply' "
                            "AND status = 'confirmed'").fetchall()
    return {row["post_id"] for row in rows}


_PUBLICATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS publications (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('post', 'reply')),
    content TEXT,
    register TEXT,
    phase TEXT,
    post_row_id INTEGER REFERENCES posts(id),
    target_id TEXT,
    target_author TEXT,
    target_content TEXT,
    target_url TEXT,
    source_url TEXT,
    source_fingerprint TEXT,
    status TEXT NOT NULL CHECK (status IN
        ('draft', 'attempted', 'confirmed', 'failed', 'uncertain', 'legacy_unknown')),
    created_at TEXT,
    attempted_at TEXT,
    confirmed_at TEXT,
    updated_at TEXT,
    external_id TEXT,
    external_url TEXT,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS publication_events (
    id INTEGER PRIMARY KEY,
    publication_id INTEGER NOT NULL REFERENCES publications(id),
    status TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    detail TEXT,
    external_id TEXT,
    external_url TEXT
);
CREATE INDEX IF NOT EXISTS publication_target ON publications(target_id, status);
"""


def save_draft(content, register, phase=None, signal=None, target=None, db_path=None,
               source_key=None, source_fingerprint=None):
    """Persist generation and its persona/source history in one transaction.

    source_key/source_fingerprint (RC-107) are only meaningful for an original post (target
    is None) and only set when the caller supplies them -- callers.py (persona.memory) is the
    one that knows how to derive them from a Signal, so this layer just stores whatever it's
    given, matching insert_signal()'s "typed loosely" convention above."""
    if target is not None and not target.get("id"):
        raise ValueError("Reply drafts require a target identity")
    now = datetime.now(timezone.utc).isoformat()
    with _connect(db_path) as conn:
        signal_id = None
        post_id = None
        if signal is not None:
            signal_id = conn.execute(
                "INSERT INTO signals (source, domain, title, summary, url, novelty_score, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (signal.source, signal.domain, signal.title, signal.summary, signal.url,
                 signal.novelty_score, signal.fetched_at.isoformat())).lastrowid
        conn.execute("INSERT INTO state_history (timestamp, register, phase, triggering_signal_id) "
                     "VALUES (?, ?, ?, ?)", (now, register, phase, signal_id))
        if target is None:
            post_id = conn.execute(
                "INSERT INTO posts (post_text, register, phase, signal_id, posted_at) "
                "VALUES (?, ?, ?, ?, NULL)", (content, register, phase, signal_id)).lastrowid
        target = target or {}
        publication_id = conn.execute(
            "INSERT INTO publications (kind, content, register, phase, post_row_id, target_id, "
            "target_author, target_content, target_url, source_url, source_fingerprint, "
            "status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?)",
            ('post' if post_id else 'reply', content, register, phase, post_id,
             target.get('id'), target.get('author_handle'), target.get('text'),
             target.get('url'), post_id and source_key, post_id and source_fingerprint,
             now, now)).lastrowid
        conn.execute("INSERT INTO publication_events (publication_id, status, timestamp) "
                     "VALUES (?, 'draft', ?)", (publication_id, now))
    return publication_id, post_id


def get_publication(publication_id, db_path=None):
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM publications WHERE id = ?", (publication_id,)).fetchone()
    if row is None:
        raise ValueError("Unknown publication")
    return dict(row)


def get_covered_sources(window_start: str, db_path: Optional[str] = None) -> set[tuple[str, str]]:
    """(source_url, source_fingerprint) pairs currently ineligible for original-post
    re-selection (RC-107): confirmed within the coverage window, or held by an unresolved
    attempt regardless of window -- mirrors reply_is_held's held-status set so an uncertain
    publication can't be duplicated before RC-104 reconciliation resolves it. A draft (dry
    run or otherwise) never appears here; only a real publication attempt does. Legacy rows
    have no source_url (see init_db's version-1-to-2 migration) and are excluded, same as
    reply_is_held treats a legacy target as held only once it actually has a target_id."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT source_url, source_fingerprint FROM publications WHERE kind = 'post' "
            "AND source_url IS NOT NULL AND (status IN ('attempted', 'uncertain') OR "
            "(status = 'confirmed' AND confirmed_at >= ?))", (window_start,)
        ).fetchall()
    return {(row["source_url"], row["source_fingerprint"]) for row in rows}


def reply_is_held(target_id, db_path=None):
    with _connect(db_path) as conn:
        return conn.execute(
            "SELECT 1 FROM publications WHERE target_id = ? AND status IN "
            "('attempted', 'confirmed', 'uncertain', 'legacy_unknown')", (target_id,)
        ).fetchone() is not None


def transition_publication(publication_id, status, *, detail=None, external_id=None,
                           external_url=None, reconcile=False, db_path=None):
    """Durable attempt before browser access; explicit reconciliation releases held rows.

    A crashed attempted row stays held on restart. No automatic retry of ambiguous work.
    """
    now = datetime.now(timezone.utc).isoformat()
    with _connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM publications WHERE id = ?", (publication_id,)).fetchone()
        if row is None:
            raise ValueError("Unknown publication")
        allowed = {'draft': {'attempted'}, 'failed': {'attempted'},
                   'attempted': {'confirmed', 'failed', 'uncertain'}}
        if reconcile and detail:
            allowed.update({'uncertain': {'confirmed', 'failed'},
                            'legacy_unknown': {'confirmed', 'failed'}})
        if status not in allowed.get(row['status'], set()):
            raise ValueError("Invalid publication transition")
        if status == 'confirmed' and not (external_id or external_url):
            raise ValueError("Confirmation requires external publication identity")
        if status == 'attempted' and row['target_id']:
            held = conn.execute("SELECT 1 FROM publications WHERE target_id = ? AND id != ? "
                                "AND status IN ('attempted','confirmed','uncertain','legacy_unknown')",
                                (row['target_id'], publication_id)).fetchone()
            if held:
                raise ValueError("Reply target held for reconciliation or already confirmed")
        conn.execute("UPDATE publications SET status=?, updated_at=?, detail=?, "
                     "attempted_at=CASE WHEN ?='attempted' THEN ? ELSE attempted_at END, "
                     "confirmed_at=CASE WHEN ?='confirmed' THEN ? ELSE confirmed_at END, "
                     "external_id=COALESCE(?, external_id), external_url=COALESCE(?, external_url) "
                     "WHERE id=?", (status, now, detail, status, now, status, now,
                                    external_id, external_url, publication_id))
        conn.execute("INSERT INTO publication_events "
                     "(publication_id,status,timestamp,detail,external_id,external_url) "
                     "VALUES (?,?,?,?,?,?)", (publication_id,status,now,detail,external_id,external_url))
        if status == 'confirmed' and row['kind'] == 'post':
            conn.execute("UPDATE posts SET posted_at=? WHERE id=?", (now,row['post_row_id']))
            conn.execute("UPDATE signals SET used_at=? WHERE id=(SELECT signal_id FROM posts WHERE id=?)",
                         (now,row['post_row_id']))
        if status == 'confirmed' and row['kind'] == 'reply':
            conn.execute("INSERT INTO replied_posts "
                         "(post_id,post_author,post_content,reply_content,register,replied_at) "
                         "VALUES (?,?,?,?,?,?) ON CONFLICT(post_id) DO UPDATE SET "
                         "reply_content=excluded.reply_content, replied_at=excluded.replied_at",
                         (row['target_id'],row['target_author'],row['target_content'],
                          row['content'],row['register'],now))
