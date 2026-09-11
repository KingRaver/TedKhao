"""Manual test harness: exercise bot.py's cycle functions directly against a fake,
non-network LLMProvider and a temp database, same spirit as tests/manual_test_persistence.py
for Phase 5. Proves the signals -> persona -> engagement -> database wiring bot.py coordinates
without needing a live API key or a real X session.

Included in `venv/bin/python tests/run_offline.py` (RC-101). Uses plain asserts. Run with:

    python tests/manual_test_bot_cycle.py
"""
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import bot  # noqa: E402
import database  # noqa: E402
from llm_provider import LLMProvider  # noqa: E402
from persona.memory import PersonaMemory  # noqa: E402
from signals.base import Signal  # noqa: E402


class FakeProvider(LLMProvider):
    """Deterministic, no-network stand-in so this harness never needs ANTHROPIC_API_KEY."""

    def generate(self, prompt: str, system_prompt: str | None = None,
                 max_tokens: int = 300, temperature: float = 0.8) -> str:
        return "That's a genuinely delightful little detail, honestly."


_FAKE_DOMAIN_SIGNALS = [
    Signal(
        source="arxiv", domain="technology",
        title="Fake paper for bot-cycle testing",
        summary="A fake abstract with enough detail to build a prompt from.",
        url="https://arxiv.org/abs/fake-bot-cycle", novelty_score=0.9,
    ),
]

_FAKE_TIMELINE_SIGNALS = [
    Signal(
        source="x_timeline", domain="technology",
        title="a fake timeline post about a new algorithm",
        summary="a fake timeline post about a new algorithm, worth replying to",
        url="https://x.com/some_handle/status/1111111111",
        novelty_score=0.6,
    ),
    Signal(
        source="x_timeline", domain="history",
        title="a fake timeline post about ancient Rome",
        summary="a fake timeline post about ancient Rome, worth replying to",
        url="https://x.com/another_handle/status/2222222222",
        novelty_score=0.4,
    ),
    Signal(
        source="x_timeline", domain="arts",
        title="malformed permalink, should be skipped",
        summary="no usable status URL here",
        url="https://x.com/i/some_other_shape",
        novelty_score=0.3,
    ),
]


def test_parse_x_post_url() -> None:
    handle, post_id = bot._parse_x_post_url("https://x.com/some_handle/status/1111111111")
    assert (handle, post_id) == ("@some_handle", "1111111111")

    handle, post_id = bot._parse_x_post_url("https://x.com/i/some_other_shape")
    assert (handle, post_id) == (None, None), "non-status URLs must not parse as a reply target"

    handle, post_id = bot._parse_x_post_url("")
    assert (handle, post_id) == (None, None), "empty url must not parse as a reply target"

    print("  _parse_x_post_url handle/id extraction + malformed-URL rejection: OK")


def test_run_post_cycle(db_path: str) -> None:
    memory = PersonaMemory(db_path=db_path)
    result = bot.run_post_cycle(
        FakeProvider(), memory, _FAKE_DOMAIN_SIGNALS, _FAKE_TIMELINE_SIGNALS, live_posting=False,
    )

    assert result["post_text"], "run_post_cycle should return generated post text"
    assert result["post_id"] is not None

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT post_text FROM posts WHERE id = ?", (result["post_id"],)
        ).fetchone()
    finally:
        conn.close()
    assert row is not None and row[0] == result["post_text"], (
        "run_post_cycle's post must be persisted to the posts table"
    )

    print("  run_post_cycle (dry run): generated + persisted post, no browser call: OK")


def test_run_reply_cycle(db_path: str) -> None:
    memory = PersonaMemory(db_path=db_path)
    results = bot.run_reply_cycle(
        FakeProvider(), memory, _FAKE_TIMELINE_SIGNALS, live_posting=False, max_replies=3,
    )

    assert len(results) == 2, (
        "the malformed-permalink signal must be skipped, leaving exactly 2 reply candidates"
    )
    replied_ids = {r["post"]["id"] for r in results}
    assert replied_ids == {"1111111111", "2222222222"}
    for r in results:
        assert database.has_replied(r["post"]["id"], db_path=db_path)

    # Re-running the same cycle should skip both -- already-replied dedup via memory.has_replied.
    second_pass = bot.run_reply_cycle(
        FakeProvider(), memory, _FAKE_TIMELINE_SIGNALS, live_posting=False, max_replies=3,
    )
    assert second_pass == [], "already-replied signals must be skipped on a second pass"

    print("  run_reply_cycle (dry run): handle/id parsing, generation, persistence, "
          "already-replied dedup, no browser call: OK")


def test_run_reply_cycle_respects_max_replies(db_path: str) -> None:
    memory = PersonaMemory(db_path=db_path)
    results = bot.run_reply_cycle(
        FakeProvider(), memory, _FAKE_TIMELINE_SIGNALS, live_posting=False, max_replies=1,
    )
    assert len(results) == 1, "max_replies must cap how many candidates are acted on"

    print("  run_reply_cycle respects max_replies: OK")


def main() -> None:
    print("Phase 7 bot.py cycle smoke test (temp db, fake provider, no network/browser calls)")
    test_parse_x_post_url()

    with tempfile.TemporaryDirectory() as tmp_dir:
        test_run_post_cycle(os.path.join(tmp_dir, "post_cycle.db"))
        test_run_reply_cycle(os.path.join(tmp_dir, "reply_cycle.db"))
        test_run_reply_cycle_respects_max_replies(os.path.join(tmp_dir, "max_replies.db"))

    print("\nAll bot-cycle checks passed.")


if __name__ == "__main__":
    main()
