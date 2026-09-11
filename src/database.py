"""SQLite schema + access layer -- docs/SPEC.md's Data Models section, table shapes mirrored
as closely as possible.

Every function opens its own short-lived connection rather than holding one open across the
process -- this matches the project's small, single-writer scale (one bot process) and avoids
cross-thread/connection-lifetime bookkeeping a long-lived pool would need. init_db() is
idempotent (CREATE TABLE IF NOT EXISTS) and safe to call on every startup; persona.memory
already does this automatically.

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
        conn.executescript(_SCHEMA)


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
            "INSERT INTO posts (post_text, register, phase, signal_id) VALUES (?, ?, ?, ?)",
            (post_text, register, phase, signal_id),
        )
        return cur.lastrowid


def insert_replied_post(post_id: str, post_author: Optional[str], post_content: Optional[str],
                         reply_content: Optional[str], register: Optional[str] = None,
                         db_path: Optional[str] = None) -> int:
    """INSERT OR REPLACE, not plain INSERT -- post_id is UNIQUE NOT NULL, and re-running a
    harness against the same fake/real post_id (e.g. manual_test_replies.py across runs)
    should overwrite the prior attempt rather than raise IntegrityError."""
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT OR REPLACE INTO replied_posts "
            "(post_id, post_author, post_content, reply_content, register) VALUES (?, ?, ?, ?, ?)",
            (post_id, post_author, post_content, reply_content, register),
        )
        return cur.lastrowid


def has_replied(post_id: str, db_path: Optional[str] = None) -> bool:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM replied_posts WHERE post_id = ?", (post_id,)
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
        rows = conn.execute("SELECT post_id FROM replied_posts").fetchall()
    return {row["post_id"] for row in rows}
