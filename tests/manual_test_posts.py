"""Manual test harness: run the real post-generation path against fake signal pools and print
the output for human review against VOICE_GUIDE.md.

Not an automated pytest suite -- this is meant to be read by a person deciding whether
TedKhao's original-post voice is working, before any of this touches a real timeline. Mirrors
tests/manual_test_replies.py's spirit; there's no engagement/post_handler.py yet (that pipeline
gets wired together in bot.py, Phase 7), so this script does the same analyze -> select ->
build prompt -> generate -> enforce length steps inline. Run with:

    python tests/manual_test_posts.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from engagement.reply_handler import _sentence_aware_truncate  # noqa: E402
from llm_provider import get_provider  # noqa: E402
from persona.memory import PersonaMemory  # noqa: E402
from persona.prompts import build_post_prompt, build_shorten_prompt  # noqa: E402
from persona.state import select_phase_register_and_signal  # noqa: E402
from signals.base import Signal  # noqa: E402
import config  # noqa: E402
import database  # noqa: E402

# Each scenario is its own fake signal pool, chosen to land on a different Phase via
# select_phase_register_and_signal's heuristic (src/persona/state.py). Contested is
# intentionally left out -- that heuristic can't reach it yet (no semantic/sentiment
# analysis over the pool), so there's no fake pool that would exercise it honestly.
SCENARIOS: list[tuple[str, list[Signal]]] = [
    ("Convergence (two domains high-novelty)", [
        Signal(
            source="arxiv", domain="technology",
            title="New paper on diffusion models for protein folding",
            summary="Researchers combine diffusion models with graph transformers to predict "
                    "novel protein structures faster than AlphaFold's original pipeline.",
            url="https://arxiv.org/abs/fake1", novelty_score=0.82,
        ),
        Signal(
            source="met_museum", domain="arts",
            title="Newly attributed Rembrandt drawing found in a private collection",
            summary="A sketch long catalogued as 'circle of Rembrandt' has been reattributed to "
                    "the artist himself after pigment analysis.",
            url="https://example.org/met/fake1", novelty_score=0.75,
        ),
        Signal(
            source="hackernews", domain="technology",
            title="Show HN: I built a JPEG decoder from scratch in 200 lines",
            url="https://news.ycombinator.com/item?id=fake1", novelty_score=0.4,
        ),
    ]),
    ("Breakthrough (single very high novelty)", [
        Signal(
            source="arxiv", domain="technology",
            title="Room-temperature superconductivity claim replicated by second lab",
            summary="A second independent team reports replicating last month's room-temperature "
                    "superconductor result under ambient pressure.",
            url="https://arxiv.org/abs/fake2", novelty_score=0.93,
        ),
        Signal(
            source="hackernews", domain="technology",
            title="Ask HN: best way to learn Rust in 2026",
            url="https://news.ycombinator.com/item?id=fake2", novelty_score=0.2,
        ),
    ]),
    ("Anniversary (top signal is wikipedia_otd)", [
        Signal(
            source="wikipedia_otd", domain="history",
            title="On this day: the Rosetta Stone is rediscovered near Rosetta, Egypt (1799)",
            summary="French soldiers rebuilding a fort near the town of Rosetta find a stone slab "
                    "inscribed in three scripts.",
            url="https://en.wikipedia.org/wiki/Rosetta_Stone", novelty_score=0.5,
        ),
        Signal(
            source="met_museum", domain="arts",
            title="Conservation notes on a 15th-century Flemish altarpiece",
            url="https://example.org/met/fake2", novelty_score=0.3,
        ),
    ]),
    ("Excavation (top signal is low novelty)", [
        Signal(
            source="met_museum", domain="arts",
            title="An obscure 1920s color-theory pamphlet by a little-known Bauhaus student",
            summary="A rediscovered pamphlet outlines a color-mixing notation system that "
                    "predates Pantone by decades.",
            url="https://example.org/met/fake3", novelty_score=0.15,
        ),
    ]),
    ("Quiet (mid novelty, nothing pressing)", [
        Signal(
            source="hackernews", domain="technology",
            title="A well-written blog post about database indexing",
            url="https://news.ycombinator.com/item?id=fake3", novelty_score=0.5,
        ),
    ]),
    ("Quiet via empty pool (no signal at all -- anti-fabrication path)", []),
]


def _ensure_post_length(text: str, provider) -> str:
    """Same shorten-then-truncate shape as engagement.reply_handler._ensure_length, scaled to
    POST_MAX_CHARS. Kept local to this test harness rather than duplicated as a src/ module --
    there's no post_handler.py yet for it to live in (that's Phase 7's bot.py orchestration).
    """
    text = text.strip()
    if len(text) <= config.POST_MAX_CHARS:
        return text

    for _ in range(config.POST_SHORTEN_ATTEMPTS):
        shorten_prompt = build_shorten_prompt(text, config.POST_MAX_CHARS)
        text = provider.generate(shorten_prompt, max_tokens=150, temperature=0.5).strip()
        if len(text) <= config.POST_MAX_CHARS:
            return text

    return _sentence_aware_truncate(text, config.POST_MAX_CHARS)


def main() -> None:
    try:
        provider = get_provider()
    except ValueError as e:
        print(f"\nCan't run live: {e}\n")
        print("Copy .env.example to .env and fill in ANTHROPIC_API_KEY, then re-run.\n")
        return

    memory = PersonaMemory()

    for scenario_name, signals in SCENARIOS:
        phase, register, signal = select_phase_register_and_signal(
            signals, memory.recent_phases, memory.recent_registers
        )

        prompt = build_post_prompt(phase, register, signal)
        post_text = provider.generate(prompt, max_tokens=250, temperature=0.9)
        post_text = _ensure_post_length(post_text, provider)

        # Persist the triggering signal first (if any) so posts.signal_id / state_history's
        # triggering_signal_id reference a real row. No engagement/post_handler.py exists yet
        # to own this wiring (deferred to Phase 7's bot.py orchestration, per
        # docs/SCAFFOLDING.md), so this harness does the same inline
        # analyze -> select -> build prompt -> generate -> persist steps it already does for
        # generation, rather than duplicating a module that doesn't exist yet.
        signal_id = None
        if signal is not None:
            signal_id = database.insert_signal(signal)
            database.mark_signal_used(signal_id)

        memory.record_state(register, phase, triggering_signal_id=signal_id)
        database.insert_post(post_text, register.value, phase.value, signal_id=signal_id)

        print("=" * 70)
        print(f"SCENARIO: {scenario_name}")
        print(f"  phase: {phase.value} | register: {register.value}")
        if signal:
            print(f"  signal: [{signal.source}/{signal.domain}] {signal.title}")
        else:
            print("  signal: none (empty pool)")
        print(f"POST ({len(post_text)} chars):")
        print(f"  {post_text}")
        print()

    print("=" * 70)
    print(f"Recent phases used (anti-repetition check): "
          f"{[p.value for p in memory.recent_phases]}")
    print(f"Recent registers used (anti-repetition check): "
          f"{[r.value for r in memory.recent_registers]}")


if __name__ == "__main__":
    main()
