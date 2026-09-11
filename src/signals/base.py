"""Common Signal dataclass + fetch() interface every signals/*.py module implements.

Each source module exposes a module-level `fetch() -> list[Signal]` function with this
exact shape -- nothing else in the codebase should need to know which source it's talking
to. See docs/STRUCTURE.md's "growth by addition, not modification" design note and
docs/SPEC.md's `signals` table, which this dataclass mirrors.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Signal:
    """Raw content pulled from one signal source."""
    source: str            # 'arxiv', 'wikipedia_otd', 'hackernews', 'met_museum', etc.
    domain: str             # 'technology' | 'history' | 'arts'
    title: str
    summary: str = ""
    url: str = ""
    novelty_score: float = 0.0
    # True only when this source's fetch order is itself evidence of freshness or trending
    # significance (arxiv: sorted by submission date; hackernews: current top-stories rank).
    # False for sources whose order is arbitrary or unrelated to novelty (wikipedia_otd's "on
    # this day" order, arts_feed's random sample, a user's timeline scroll order) -- rank 0
    # there means "happened to be first," not "genuinely new." persona.state gates Breakthrough
    # on this so a first-ranked historical event or museum object can't become a breakthrough
    # solely because rank_novelty() gave it a 1.0 (RC-106).
    novelty_evidenced: bool = False
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def rank_novelty(rank: int, total: int) -> float:
    """Newest/highest-ranked-first index -> a 0-1 novelty placeholder score.

    Every signals/*.py source uses this same linear decay so there's one place to tune
    once real usage data exists -- the actual scoring formula is an open question in
    docs/SPEC.md ("Exact novelty/significance scoring formula for the signal pool").
    """
    if total <= 1:
        return 1.0
    return round(1.0 - (rank / (total - 1)), 3)
