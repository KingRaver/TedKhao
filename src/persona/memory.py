"""Anti-repetition tracking.

Persisted across restarts via database.py (docs/SPEC.md's `state_history` / `replied_posts`
tables) as of Phase 5 -- previously in-process-only. On construction, PersonaMemory loads its
recent history from the database so a freshly-started process picks up where the last one left
off, instead of starting anti-repetition tracking from empty every time the bot restarts.

record_register()/record_phase()/mark_replied() remain simple in-memory-only primitives (kept
for callers that only need local tracking, e.g. tests). The persisting entry points are
record_state() and record_reply() -- both update the in-memory lists/set *and* write through
to the database in one call, so production call sites don't have to remember to do both.
"""
from typing import Optional

import database
from persona.state import Phase, Register


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
        self.record_register(register)
        if phase is not None:
            self.record_phase(phase)

        database.insert_state_history(
            register=register.value,
            phase=phase.value if phase else None,
            triggering_signal_id=triggering_signal_id,
            db_path=self._db_path,
        )

    def record_reply(self, post_id: str, post_author: Optional[str], post_content: Optional[str],
                      reply_content: str, register: Register) -> None:
        """Update the in-memory dedup set and persist one replied_posts row in a single call."""
        self.mark_replied(post_id)

        database.insert_replied_post(
            post_id=post_id,
            post_author=post_author,
            post_content=post_content,
            reply_content=reply_content,
            register=register.value,
            db_path=self._db_path,
        )
