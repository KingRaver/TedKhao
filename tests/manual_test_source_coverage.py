"""RC-107 deterministic checks: recent-source-coverage deduplication for original posts.

engagement.post_handler.generate_post() must not draw a new post from a signal whose source
was already confirmed recently, or whose last attempt is still unresolved (attempted/
uncertain) -- but a draft/dry-run attempt, a failed attempt, an expired coverage window, or a
materially updated item (same URL, changed title) must all remain (or become) eligible. When
every candidate in the pool is covered, generate_post() must return an explicit skipped result
rather than silently reselecting an already-posted source.

Uses a real temporary database (RC-102's publication lifecycle) and a deterministic, no-network
FakeProvider -- no live model or browser call, per run_offline.py's no-network rule. Included in
`venv/bin/python tests/run_offline.py` (RC-101). Uses plain asserts. Run with:

    python tests/manual_test_source_coverage.py
"""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import database  # noqa: E402
from engagement.post_handler import generate_post  # noqa: E402
from llm_provider import LLMProvider  # noqa: E402
from persona.memory import PersonaMemory  # noqa: E402
from signals.base import Signal  # noqa: E402


class FakeProvider(LLMProvider):
    """Deterministic, no-network stand-in, same shape as the other offline harnesses."""

    def generate(self, prompt: str, system_prompt: str | None = None,
                 max_tokens: int = 300, temperature: float = 0.8) -> str:
        return "A perfectly reasonable, nonempty generated post about something curious."


def _signal(url: str, title: str, source: str = "arxiv", domain: str = "technology") -> Signal:
    return Signal(source=source, domain=domain, title=title,
                  summary="Enough detail to build a prompt from.", url=url,
                  novelty_score=0.9, novelty_evidenced=True)


def _confirm(memory: PersonaMemory, publication_id: int, external_id: str = "ext-1") -> None:
    memory.transition_publication(publication_id, "attempted")
    memory.transition_publication(publication_id, "confirmed", external_id=external_id)


def _mark_uncertain(memory: PersonaMemory, publication_id: int) -> None:
    memory.transition_publication(publication_id, "attempted")
    memory.transition_publication(publication_id, "uncertain", detail="no confirmation evidence")


def _mark_failed(memory: PersonaMemory, publication_id: int) -> None:
    memory.transition_publication(publication_id, "attempted")
    memory.transition_publication(publication_id, "failed", detail="submission error")


def _backdate_confirmation(db_path: str, publication_id: int, hours_ago: float) -> None:
    ts = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    with database._connect(db_path) as conn:
        conn.execute("UPDATE publications SET confirmed_at = ? WHERE id = ?", (ts, publication_id))


def test_repeated_fetch_of_confirmed_source_is_skipped(db_path: str) -> None:
    memory = PersonaMemory(db_path=db_path)
    signal = _signal("https://arxiv.org/abs/rc107-repeat", "A paper worth posting about")

    first = generate_post([signal], FakeProvider(), memory)
    assert not first.get("skipped") and first["post_id"] is not None
    _confirm(memory, first["publication_id"])

    second = generate_post([signal], FakeProvider(), memory)
    assert second["skipped"] == "all_candidate_sources_recently_covered"
    assert second["post_id"] is None and second["post_text"] is None
    print("  repeated fetch of a confirmed source: skipped, not re-posted: OK")


def test_skip_survives_process_restart(db_path: str) -> None:
    memory = PersonaMemory(db_path=db_path)
    signal = _signal("https://arxiv.org/abs/rc107-restart", "Another paper")
    result = generate_post([signal], FakeProvider(), memory)
    _confirm(memory, result["publication_id"])

    restarted = PersonaMemory(db_path=db_path)
    again = generate_post([signal], FakeProvider(), restarted)
    assert again["skipped"] == "all_candidate_sources_recently_covered"
    print("  coverage survives a fresh PersonaMemory (process restart): OK")


def test_dry_run_draft_does_not_count_as_coverage(db_path: str) -> None:
    memory = PersonaMemory(db_path=db_path)
    signal = _signal("https://arxiv.org/abs/rc107-dryrun", "A paper never confirmed")

    first = generate_post([signal], FakeProvider(), memory)
    assert not first.get("skipped")
    # Never transitioned past 'draft' -- a dry run, or a source-row insertion alone.
    second = generate_post([signal], FakeProvider(), memory)
    assert not second.get("skipped"), "a draft-only attempt must never count as coverage"
    assert second["post_id"] is not None
    print("  draft/dry-run attempts do not count as coverage: OK")


def test_uncertain_attempt_holds_the_source(db_path: str) -> None:
    memory = PersonaMemory(db_path=db_path)
    signal = _signal("https://arxiv.org/abs/rc107-uncertain", "A paper with an ambiguous attempt")

    result = generate_post([signal], FakeProvider(), memory)
    _mark_uncertain(memory, result["publication_id"])

    again = generate_post([signal], FakeProvider(), memory)
    assert again["skipped"] == "all_candidate_sources_recently_covered", (
        "an unresolved uncertain attempt must hold its source, preventing accidental "
        "duplicate publication before RC-104 reconciliation resolves it"
    )
    print("  unresolved uncertain attempt holds its source: OK")


def test_failed_attempt_does_not_hold_the_source(db_path: str) -> None:
    memory = PersonaMemory(db_path=db_path)
    signal = _signal("https://arxiv.org/abs/rc107-failed", "A paper whose first attempt failed")

    result = generate_post([signal], FakeProvider(), memory)
    _mark_failed(memory, result["publication_id"])

    again = generate_post([signal], FakeProvider(), memory)
    assert not again.get("skipped"), "a failed attempt must remain eligible for controlled retry"
    print("  failed attempt remains eligible for retry: OK")


def test_expired_coverage_window_becomes_eligible(db_path: str) -> None:
    memory = PersonaMemory(db_path=db_path)
    signal = _signal("https://arxiv.org/abs/rc107-expired", "A paper confirmed long ago")

    result = generate_post([signal], FakeProvider(), memory)
    _confirm(memory, result["publication_id"])
    _backdate_confirmation(db_path, result["publication_id"], hours_ago=1000)

    again = generate_post([signal], FakeProvider(), memory)
    assert not again.get("skipped"), "a confirmation older than the coverage window must expire"
    print("  confirmation older than the coverage window becomes eligible again: OK")


def test_missing_url_uses_source_and_title_fallback(db_path: str) -> None:
    memory = PersonaMemory(db_path=db_path)
    same_again = Signal(source="met_museum", domain="arts", title="An untitled highlighted object",
                         summary="", url="", novelty_score=0.9)
    different_title = Signal(source="met_museum", domain="arts", title="A different highlighted object",
                              summary="", url="", novelty_score=0.9)

    result = generate_post([same_again], FakeProvider(), memory)
    _confirm(memory, result["publication_id"])

    repeat = generate_post([same_again], FakeProvider(), memory)
    assert repeat["skipped"] == "all_candidate_sources_recently_covered", (
        "two urlless signals with the same source+title must share a stable fallback key"
    )
    distinct = generate_post([different_title], FakeProvider(), memory)
    assert not distinct.get("skipped"), (
        "two urlless signals with different titles must not collide on the fallback key"
    )
    print("  missing-URL fallback key: stable for a repeat, distinct for a different title: OK")


def test_same_url_materially_updated_title_is_eligible(db_path: str) -> None:
    memory = PersonaMemory(db_path=db_path)
    url = "https://arxiv.org/abs/rc107-updated"
    original = _signal(url, "Initial preprint of a new result")
    updated = _signal(url, "Revised preprint of a new result, with corrected figures")

    result = generate_post([original], FakeProvider(), memory)
    _confirm(memory, result["publication_id"])

    same_title_again = generate_post([original], FakeProvider(), memory)
    assert same_title_again["skipped"] == "all_candidate_sources_recently_covered"

    materially_updated = generate_post([updated], FakeProvider(), memory)
    assert not materially_updated.get("skipped"), (
        "the same URL with a changed title is a materially updated item, not a repeat, and "
        "must become eligible again even inside the coverage window"
    )
    print("  same URL, materially updated title: eligible again despite the coverage window: OK")


def test_all_candidates_covered_returns_explicit_skip_without_side_effects(db_path: str) -> None:
    memory = PersonaMemory(db_path=db_path)
    first = _signal("https://arxiv.org/abs/rc107-all-a", "First covered paper")
    second = _signal("https://news.ycombinator.com/item?id=rc107-all-b", "Second covered item",
                      source="hackernews")

    for signal in (first, second):
        result = generate_post([signal], FakeProvider(), memory)
        _confirm(memory, result["publication_id"])

    with sqlite3.connect(db_path) as conn:
        posts_before = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        publications_before = conn.execute("SELECT COUNT(*) FROM publications").fetchone()[0]

    result = generate_post([first, second], FakeProvider(), memory)
    assert result == {
        "post_id": None, "publication_id": None, "post_text": None,
        "phase": None, "register": None, "signal": None,
        "skipped": "all_candidate_sources_recently_covered",
    }

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == posts_before
        assert conn.execute("SELECT COUNT(*) FROM publications").fetchone()[0] == publications_before
    print("  all candidates covered: explicit skip result, no draft/post silently created: OK")


def main() -> None:
    print("Phase 7 (RC-107) source-coverage deduplication regression checks")

    with tempfile.TemporaryDirectory() as directory:
        tests = (
            test_repeated_fetch_of_confirmed_source_is_skipped,
            test_skip_survives_process_restart,
            test_dry_run_draft_does_not_count_as_coverage,
            test_uncertain_attempt_holds_the_source,
            test_failed_attempt_does_not_hold_the_source,
            test_expired_coverage_window_becomes_eligible,
            test_missing_url_uses_source_and_title_fallback,
            test_same_url_materially_updated_title_is_eligible,
            test_all_candidates_covered_returns_explicit_skip_without_side_effects,
        )
        for test in tests:
            test(os.path.join(directory, test.__name__ + ".db"))

    print("\nAll source-coverage checks passed.")


if __name__ == "__main__":
    main()
