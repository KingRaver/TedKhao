"""Manual test harness: exercise database.py directly and prove PersonaMemory actually
survives a simulated restart (a fresh PersonaMemory instance picking up a prior instance's
writes) -- the core claim of Phase 5. Also exercises engagement.reply_handler.generate_reply()
against a fake, non-network LLMProvider so the reply_handler -> database wiring is proven
without needing a live API key.

Included in `venv/bin/python tests/run_offline.py` (RC-101). Uses plain asserts so failures
are loud and specific. Run with:

    python tests/manual_test_persistence.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import database  # noqa: E402
from engagement.reply_handler import generate_reply  # noqa: E402
from llm_provider import LLMProvider  # noqa: E402
from persona.memory import PersonaMemory  # noqa: E402
from persona.state import Phase, Register  # noqa: E402
from signals.base import Signal  # noqa: E402


class FakeProvider(LLMProvider):
    """Deterministic, no-network stand-in so this harness never needs ANTHROPIC_API_KEY."""

    def generate(self, prompt: str, system_prompt: str | None = None,
                 max_tokens: int = 300, temperature: float = 0.8) -> str:
        return "That's a genuinely delightful little detail, honestly."


def test_schema_and_signal_lifecycle(db_path: str) -> None:
    database.init_db(db_path)

    signal = Signal(
        source="arxiv", domain="technology", title="Fake paper for persistence testing",
        summary="n/a", url="https://arxiv.org/abs/fake-persistence", novelty_score=0.9,
    )
    signal_id = database.insert_signal(signal, db_path=db_path)
    assert signal_id is not None, "insert_signal should return a row id"

    database.mark_signal_used(signal_id, db_path=db_path)

    post_id = database.insert_post(
        "A fake post referencing the fake signal.", Register.DELIGHTED.value,
        Phase.BREAKTHROUGH.value, signal_id=signal_id, db_path=db_path,
    )
    assert post_id is not None, "insert_post should return a row id"

    print("  schema creation + signal -> post FK chain: OK")


def test_state_history_nullable_phase(db_path: str) -> None:
    reply_row = database.insert_state_history(Register.AMUSED.value, db_path=db_path)
    post_row = database.insert_state_history(
        Register.GIDDY.value, phase=Phase.BREAKTHROUGH.value, db_path=db_path,
    )
    assert reply_row is not None and post_row is not None

    recent_registers = database.get_recent_registers(10, db_path=db_path)
    recent_phases = database.get_recent_phases(10, db_path=db_path)
    assert Register.AMUSED.value in recent_registers
    assert Register.GIDDY.value in recent_registers
    assert recent_phases == [Phase.BREAKTHROUGH.value], (
        "get_recent_phases must skip the reply-path row with phase=NULL"
    )

    print("  state_history nullable phase (reply path) vs populated phase (post path): OK")


def test_persona_memory_survives_restart(db_path: str) -> None:
    first_session = PersonaMemory(db_path=db_path)
    first_session.record_state(Register.WISTFUL, Phase.ANNIVERSARY)
    first_session.record_reply(
        post_id="restart-test-1", post_author="@someone", post_content="original post text",
        reply_content="a reply", register=Register.WISTFUL,
    )

    second_session = PersonaMemory(db_path=db_path)
    assert Register.WISTFUL in second_session.recent_registers, (
        "a fresh PersonaMemory instance should load prior registers from the database"
    )
    assert Phase.ANNIVERSARY in second_session.recent_phases, (
        "a fresh PersonaMemory instance should load prior phases from the database"
    )
    assert not second_session.has_replied("restart-test-1"), (
        "draft replies must not become successful replies after restart"
    )

    print("  PersonaMemory state visible to a brand-new instance (simulated restart): OK")


def test_reply_handler_wiring(db_path: str) -> None:
    memory = PersonaMemory(db_path=db_path)
    fake_post = {
        "id": "reply-handler-wiring-test",
        "author_handle": "@wiring_test",
        "text": "this restoration technique the conservators used is absolutely masterful",
    }

    result = generate_reply(fake_post, FakeProvider(), memory)
    assert result["reply_text"], "generate_reply should return non-empty reply text"
    assert not database.has_replied("reply-handler-wiring-test", db_path=db_path), (
        "generate_reply must not mark a draft as published"
    )

    print("  engagement.reply_handler.generate_reply() -> draft without publication: OK")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "phase5_smoke_test.db")

        print("Phase 5 persistence smoke test (temp db, not the real data/tedkhao.db)")
        test_schema_and_signal_lifecycle(db_path)
        test_state_history_nullable_phase(db_path)
        test_persona_memory_survives_restart(db_path)
        test_reply_handler_wiring(db_path)

    print("\nAll persistence checks passed.")


if __name__ == "__main__":
    main()
