"""RC-106 deterministic checks: signal selection and phase classification in
persona.state.select_phase_register_and_signal (src/persona/state.py).

Covers the three structural fixes this phase makes:
  * Tie-breaking on Signal.novelty_score no longer favors whichever source was fetched (and
    therefore pooled) first -- bot.py's _DOMAIN_SIGNAL_SOURCES always fetches arxiv first, so
    a plain max() over the pool would let arxiv win every tie regardless of merit.
  * Breakthrough requires Signal.novelty_evidenced=True -- a source whose fetch order isn't
    itself a significance ranking (wikipedia_otd's "on this day" order, arts_feed's random
    sample) can't become a breakthrough solely because rank_novelty() gave its top item a 1.0.
  * Convergence requires two different-domain high-novelty signals to actually share evidence
    of a relationship (_signals_rhyme), not just that >=2 domains independently cleared the
    novelty bar.

Uses fetcher-shaped pools (real rank_novelty() scores and the novelty_evidenced value each real
signals/*.py module actually sets) with deterministic random.seed() calls rather than live
network fetches, per run_offline.py's no-network rule. Included in
`venv/bin/python tests/run_offline.py` (RC-101). Uses plain asserts. Run with:

    python tests/manual_test_state_selection.py
"""
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from persona.state import Phase, select_phase_register_and_signal  # noqa: E402
from signals.base import Signal, rank_novelty  # noqa: E402


def _arxiv_signal(rank: int, total: int, title: str, summary: str = "") -> Signal:
    return Signal(source="arxiv", domain="technology", title=title, summary=summary,
                  url=f"https://arxiv.org/abs/fake-{rank}",
                  novelty_score=rank_novelty(rank, total), novelty_evidenced=True)


def _hackernews_signal(rank: int, total: int, title: str) -> Signal:
    return Signal(source="hackernews", domain="technology", title=title,
                  url=f"https://news.ycombinator.com/item?id=fake-{rank}",
                  novelty_score=rank_novelty(rank, total), novelty_evidenced=True)


def _wikipedia_signal(rank: int, total: int, title: str, summary: str = "") -> Signal:
    return Signal(source="wikipedia_otd", domain="history", title=title, summary=summary,
                  url=f"https://en.wikipedia.org/wiki/fake-{rank}",
                  novelty_score=rank_novelty(rank, total), novelty_evidenced=False)


def _met_museum_signal(rank: int, total: int, title: str, summary: str = "") -> Signal:
    return Signal(source="met_museum", domain="arts", title=title, summary=summary,
                  url=f"https://example.org/met/fake-{rank}",
                  novelty_score=rank_novelty(rank, total), novelty_evidenced=False)


# --- tie-breaking: arxiv must not systematically win just because it's pooled first ---------

def test_tied_top_scores_not_order_biased() -> None:
    # Same three sources, tied at rank 0 (score 1.0) within their own fetch, pooled in bot.py's
    # real order (arxiv, history, hackernews, arts) -- fetcher-shaped, not synthetic ties.
    # Deliberately unrelated vocabulary across all three so _find_convergent_pair never fires
    # here -- this test isolates the tie-break itself, not the separate relationship check.
    arxiv = _arxiv_signal(0, 3, "A new neural architecture paper")
    wiki = _wikipedia_signal(0, 3, "On this day: a distant treaty was signed")
    hn = _hackernews_signal(0, 3, "Ask HN: what editor do you use")
    pool_arxiv_first = [arxiv, wiki, hn]
    pool_reversed = [hn, wiki, arxiv]

    random.seed(7)
    phase1, _, signal1 = select_phase_register_and_signal(pool_arxiv_first)
    random.seed(7)
    phase2, _, signal2 = select_phase_register_and_signal(pool_reversed)
    assert (phase1, signal1.source) == (phase2, signal2.source), (
        "same seed, different pool order must still pick the same signal -- selection must "
        "depend on the seed, not on which source happened to be pooled first"
    )

    winners = set()
    for seed in range(40):
        random.seed(seed)
        _, _, signal = select_phase_register_and_signal(pool_arxiv_first)
        winners.add(signal.source)
    assert len(winners) > 1, (
        f"tie-break always picked {winners} across 40 seeds -- still biased toward whichever "
        "source is fetched (and pooled) first"
    )
    print(f"  tied top scores: order-independent given a seed; {len(winners)} distinct "
          f"sources won across seeds -- OK")


# --- Breakthrough requires novelty_evidenced, not just top rank -----------------------------

def test_history_only_pool_top_rank_is_anniversary_not_breakthrough() -> None:
    signals = [
        _wikipedia_signal(0, 2, "On this day: a major treaty is signed"),
        _wikipedia_signal(1, 2, "On this day: a minor local event"),
    ]
    random.seed(1)
    phase, _, signal = select_phase_register_and_signal(signals)
    assert signal.novelty_score == 1.0, "sanity check: rank 0 should still score 1.0"
    assert phase == Phase.ANNIVERSARY, (
        f"history-only pool with top rank 1.0 selected {phase}, not Anniversary -- a "
        "first-ranked historical event must not become a breakthrough solely on rank"
    )
    print("  history-only pool, top rank 1.0 -> Anniversary (not Breakthrough): OK")


def test_arts_only_pool_top_rank_is_not_breakthrough() -> None:
    signals = [
        _met_museum_signal(0, 2, "A randomly sampled highlighted object"),
        _met_museum_signal(1, 2, "Another randomly sampled highlighted object"),
    ]
    random.seed(1)
    phase, _, signal = select_phase_register_and_signal(signals)
    assert signal.novelty_score == 1.0, "sanity check: rank 0 should still score 1.0"
    assert phase != Phase.BREAKTHROUGH, (
        "arts-only pool with top rank 1.0 (from random.sample(), not a significance ranking) "
        "must not become a breakthrough solely because its score is 1.0"
    )
    assert phase == Phase.QUIET
    print("  arts-only pool, top rank 1.0 (random sample) -> not Breakthrough: OK")


def test_evidenced_top_signal_can_still_be_breakthrough() -> None:
    signals = [
        _arxiv_signal(0, 3, "A genuinely major replicated result"),
        _hackernews_signal(1, 3, "Ask HN: something unrelated"),
        _met_museum_signal(2, 3, "A low-novelty museum object"),
    ]
    random.seed(1)
    phase, _, signal = select_phase_register_and_signal(signals)
    assert phase == Phase.BREAKTHROUGH, (
        f"novelty-evidenced top signal (arxiv, freshest-first) selected {phase}, not "
        "Breakthrough -- the evidenced gate must not block genuinely evidenced sources"
    )
    assert signal.source == "arxiv"
    print("  novelty-evidenced top signal (arxiv) -> Breakthrough still reachable: OK")


# --- Convergence requires evidence of a relationship, not just domain count -----------------

def test_unrelated_cross_domain_high_novelty_is_not_convergence() -> None:
    # Both clear the Convergence novelty bar (>=0.7) and span two domains, but share no
    # vocabulary -- must fall through to a supported single-signal phase instead. Scores are
    # deliberately not tied (0.9 vs 0.75) so this test isolates the relationship check from
    # the separate tied-score tie-break covered above.
    tech = Signal(source="arxiv", domain="technology",
                  title="Faster sorting algorithm for large arrays",
                  summary="A new in-place sorting algorithm beats existing benchmarks.",
                  url="https://arxiv.org/abs/fake-unrelated",
                  novelty_score=0.9, novelty_evidenced=True)
    arts = Signal(source="met_museum", domain="arts",
                  title="Conservation of a 15th-century Flemish altarpiece",
                  summary="Restorers stabilize flaking pigment on a wooden panel painting.",
                  url="https://example.org/met/fake-unrelated",
                  novelty_score=0.75, novelty_evidenced=False)
    assert tech.novelty_score >= 0.7 and arts.novelty_score >= 0.7, "sanity check: both high"

    random.seed(1)
    phase, _, signal = select_phase_register_and_signal([tech, arts])
    assert phase != Phase.CONVERGENCE, (
        "two unrelated high-novelty domains selected Convergence -- domain count alone must "
        "not be treated as evidence of a relationship"
    )
    assert phase == Phase.BREAKTHROUGH and signal.source == "arxiv", (
        "expected fallback to the evidenced top signal's supported single-signal phase, "
        f"got phase={phase} signal={signal.source}"
    )
    print("  unrelated cross-domain high-novelty items -> not Convergence, falls through to "
          "a supported single-signal phase: OK")


def test_related_cross_domain_high_novelty_is_convergence() -> None:
    tech = _arxiv_signal(
        0, 2, "New diffusion-model pipeline flags disputed Rembrandt attributions",
        "Researchers train a diffusion-based classifier on brushstroke patterns to help "
        "authenticate paintings attributed to Rembrandt.",
    )
    arts = _met_museum_signal(
        0, 2, "Newly attributed Rembrandt drawing found in a private collection",
        "A sketch long catalogued as circle of Rembrandt has been reattributed to the artist "
        "himself after pigment analysis.",
    )
    random.seed(1)
    phase, _, signal = select_phase_register_and_signal([tech, arts])
    assert phase == Phase.CONVERGENCE, (
        f"two different-domain high-novelty signals sharing 'Rembrandt' selected {phase}, "
        "not Convergence"
    )
    assert signal.source in {"arxiv", "met_museum"}
    print("  related cross-domain high-novelty items (shared vocabulary) -> Convergence: OK")


# --- empty pool -------------------------------------------------------------------------------

def test_empty_pool_is_quiet_with_no_signal() -> None:
    phase, _, signal = select_phase_register_and_signal([])
    assert phase == Phase.QUIET
    assert signal is None
    print("  empty pool -> Quiet, no signal: OK")


def main() -> None:
    print("Phase 6 (RC-106) source-selection and phase-correctness regression checks")

    test_tied_top_scores_not_order_biased()
    test_history_only_pool_top_rank_is_anniversary_not_breakthrough()
    test_arts_only_pool_top_rank_is_not_breakthrough()
    test_evidenced_top_signal_can_still_be_breakthrough()
    test_unrelated_cross_domain_high_novelty_is_not_convergence()
    test_related_cross_domain_high_novelty_is_convergence()
    test_empty_pool_is_quiet_with_no_signal()

    print("\nAll state-selection checks passed.")


if __name__ == "__main__":
    main()
