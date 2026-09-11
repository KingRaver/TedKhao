"""Manual test harness: run the real post-generation path against fake signal pools and print
the output for human review against VOICE_GUIDE.md.

Model integration harness, separate from the offline regression command.
Run: python tests/manual_test_posts.py [--review-db PATH]
Defaults to a temporary database removed after review.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from engagement.post_handler import generate_post  # noqa: E402
from llm_provider import get_provider  # noqa: E402
from persona.memory import PersonaMemory  # noqa: E402
from signals.base import Signal  # noqa: E402
from review_database import review_database  # noqa: E402

# Each scenario is its own fake signal pool, chosen to land on a different Phase via
# select_phase_register_and_signal's heuristic (src/persona/state.py). Contested is
# intentionally left out -- that heuristic can't reach it yet (no semantic/sentiment
# analysis over the pool), so there's no fake pool that would exercise it honestly.
SCENARIOS: list[tuple[str, list[Signal]]] = [
    ("Convergence (two domains high-novelty, sharing evidence of a relationship)", [
        Signal(
            source="arxiv", domain="technology",
            title="New diffusion-model pipeline flags disputed Rembrandt attributions",
            summary="Researchers train a diffusion-based classifier on brushstroke patterns to "
                    "help authenticate paintings attributed to Rembrandt, flagging several works "
                    "long catalogued as workshop copies for further review.",
            url="https://arxiv.org/abs/fake1", novelty_score=0.82, novelty_evidenced=True,
        ),
        Signal(
            source="met_museum", domain="arts",
            title="Newly attributed Rembrandt drawing found in a private collection",
            summary="A sketch long catalogued as 'circle of Rembrandt' has been reattributed to "
                    "the artist himself after pigment analysis.",
            url="https://example.org/met/fake1", novelty_score=0.75, novelty_evidenced=False,
        ),
        Signal(
            source="hackernews", domain="technology",
            title="Show HN: I built a JPEG decoder from scratch in 200 lines",
            url="https://news.ycombinator.com/item?id=fake1", novelty_score=0.4,
            novelty_evidenced=True,
        ),
    ]),
    ("Breakthrough (single very high, novelty-evidenced signal)", [
        Signal(
            source="arxiv", domain="technology",
            title="Room-temperature superconductivity claim replicated by second lab",
            summary="A second independent team reports replicating last month's room-temperature "
                    "superconductor result under ambient pressure.",
            url="https://arxiv.org/abs/fake2", novelty_score=0.93, novelty_evidenced=True,
        ),
        Signal(
            source="hackernews", domain="technology",
            title="Ask HN: best way to learn Rust in 2026",
            url="https://news.ycombinator.com/item?id=fake2", novelty_score=0.2,
            novelty_evidenced=True,
        ),
    ]),
    ("Anniversary (top signal is wikipedia_otd, rank alone isn't breakthrough evidence)", [
        Signal(
            source="wikipedia_otd", domain="history",
            title="On this day: the Rosetta Stone is rediscovered near Rosetta, Egypt (1799)",
            summary="French soldiers rebuilding a fort near the town of Rosetta find a stone slab "
                    "inscribed in three scripts.",
            url="https://en.wikipedia.org/wiki/Rosetta_Stone", novelty_score=0.5,
            novelty_evidenced=False,
        ),
        Signal(
            source="met_museum", domain="arts",
            title="Conservation notes on a 15th-century Flemish altarpiece",
            url="https://example.org/met/fake2", novelty_score=0.3, novelty_evidenced=False,
        ),
    ]),
    ("Excavation (top signal is low novelty)", [
        Signal(
            source="met_museum", domain="arts",
            title="An obscure 1920s color-theory pamphlet by a little-known Bauhaus student",
            summary="A rediscovered pamphlet outlines a color-mixing notation system that "
                    "predates Pantone by decades.",
            url="https://example.org/met/fake3", novelty_score=0.15, novelty_evidenced=False,
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


def run_review(db_path: str) -> None:
    try:
        provider = get_provider()
    except ValueError as e:
        print(f"\nCan't run live: {e}\n")
        print("Copy .env.example to .env and fill in ANTHROPIC_API_KEY, then re-run.\n")
        return

    memory = PersonaMemory(db_path=db_path)

    for scenario_name, signals in SCENARIOS:
        result = generate_post(signals, provider, memory)
        phase, register, signal = result["phase"], result["register"], result["signal"]
        convergence_partner = result.get("convergence_partner")
        post_text = result["post_text"]

        print("=" * 70)
        print(f"SCENARIO: {scenario_name}")
        print(f"  phase: {phase.value} | register: {register.value}")
        if signal:
            print(f"  signal: [{signal.source}/{signal.domain}] {signal.title}")
        else:
            print("  signal: none (empty pool)")
        if convergence_partner:
            print(f"  convergence partner: [{convergence_partner.source}/{convergence_partner.domain}] "
                  f"{convergence_partner.title}")
        print(f"POST ({len(post_text)} chars):")
        print(f"  {post_text}")
        print()

    print("=" * 70)
    print(f"Recent phases used (anti-repetition check): "
          f"{[p.value for p in memory.recent_phases]}")
    print(f"Recent registers used (anti-repetition check): "
          f"{[r.value for r in memory.recent_registers]}")


def main(argv=None) -> None:
    with review_database(argv) as db_path:
        run_review(db_path)


if __name__ == "__main__":
    main()
