"""Anti-repetition tracking.

Generation history and confirmed reply IDs load from SQLite on construction.
Drafts do not consume targets. Publication holds are read from the database so
attempted, uncertain, and legacy rows survive restarts without implying success.
All production writes commit before updating the in-memory history or success set.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

import database
import config
from persona.state import Phase, Register
from signals.base import content_fingerprint, source_key


class PersonaMemory:
    def __init__(self, capacity: int = 10, db_path: Optional[str] = None):
        self._capacity = capacity
        self._db_path = db_path
        database.init_db(db_path)

        self.recent_registers: list[Register] = [
            Register(value) for value in database.get_recent_registers(capacity, db_path)
        ]
        self.recent_phases: list[Phase] = [
            Phase(value) for value in database.get_recent_phases(capacity, db_path)
        ]
        self.replied_post_ids: set[str] = database.get_replied_post_ids(db_path)

    @property
    def db_path(self) -> Optional[str]:
        """The database this memory instance reads/writes -- callers making their own direct
        database.* calls alongside a PersonaMemory (e.g. engagement.post_handler) should pass
        this through rather than silently hitting config.DATABASE_PATH's default."""
        return self._db_path

    def record_register(self, register: Register) -> None:
        self.recent_registers.append(register)
        self.recent_registers = self.recent_registers[-self._capacity:]

    def record_phase(self, phase: Phase) -> None:
        self.recent_phases.append(phase)
        self.recent_phases = self.recent_phases[-self._capacity:]

    def has_replied(self, post_id: str) -> bool:
        return post_id in self.replied_post_ids

    def mark_replied(self, post_id: str) -> None:
        self.replied_post_ids.add(post_id)

    def record_state(self, register: Register, phase: Optional[Phase] = None,
                      triggering_signal_id: Optional[int] = None) -> None:
        """Update anti-repetition tracking and persist one state_history row in a single call.

        phase is optional because the reply path (select_register_for_reply) only ever
        produces a Register -- pass phase only from the post-generation path, which always
        has one (select_phase_register_and_signal).
        """
        database.insert_state_history(
            register=register.value,
            phase=phase.value if phase else None,
            triggering_signal_id=triggering_signal_id,
            db_path=self._db_path,
        )
        self.record_register(register)
        if phase is not None:
            self.record_phase(phase)

    def save_draft(self, content, register, phase=None, signal=None, target=None):
        key = fingerprint = None
        if signal is not None and target is None:
            key, fingerprint = source_key(signal), content_fingerprint(signal)
        ids = database.save_draft(content, register.value, phase.value if phase else None,
                                  signal, target, self._db_path,
                                  source_key=key, source_fingerprint=fingerprint)
        self.record_register(register)
        if phase is not None:
            self.record_phase(phase)
        return ids

    def reply_is_held(self, post_id):
        return database.reply_is_held(post_id, self._db_path)

    def covered_source_keys(self) -> set[tuple[str, str]]:
        """(source_url, content_fingerprint) pairs an original post must not be generated
        from right now (RC-107) -- see database.get_covered_sources for exactly what counts.
        Queried fresh against the database each call, not cached alongside recent_registers/
        recent_phases above, since the coverage window is time-relative: "confirmed within the
        last N hours" keeps moving forward across a resident loop's cycles even with no new
        writes, which an in-memory snapshot taken once at construction wouldn't reflect."""
        window_start = (datetime.now(timezone.utc) -
                         timedelta(hours=config.SOURCE_COVERAGE_WINDOW_HOURS)).isoformat()
        return database.get_covered_sources(window_start, self._db_path)

    def last_confirmed_post(self) -> Optional[str]:
        """Text of the most recently confirmed original post (RC-108), or None if none has
        ever been confirmed -- gates prompts.build_post_prompt's callback structure so a
        callback only fires against a post that genuinely exists, never a fabricated one."""
        return database.get_last_confirmed_post(self._db_path)

    def transition_publication(self, publication_id, status, **kwargs):
        database.transition_publication(publication_id, status, db_path=self._db_path, **kwargs)
        self.replied_post_ids = database.get_replied_post_ids(self._db_path)

    def record_reply(self, post_id: str, post_author: Optional[str], post_content: Optional[str],
                      reply_content: str, register: Register) -> int:
        """Compatibility entry point: recording generated text creates a draft only."""
        return self.save_draft(reply_content, register, target={
            'id': post_id, 'author_handle': post_author, 'text': post_content})[0]
