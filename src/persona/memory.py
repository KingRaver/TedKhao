"""Anti-repetition tracking.

In-memory for now (a single process's lifetime) -- see docs/SPEC.md's `state_history` /
`replied_posts` tables for how this gets persisted across restarts once database.py exists.
"""
from persona.state import Phase, Register


class PersonaMemory:
    def __init__(self, capacity: int = 10):
        self._capacity = capacity
        self.recent_registers: list[Register] = []
        self.recent_phases: list[Phase] = []
        self.replied_post_ids: set[str] = set()

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
