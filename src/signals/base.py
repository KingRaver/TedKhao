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


def source_key(signal: Signal) -> str:
    """Stable identity for where a signal came from, for recent-coverage tracking (RC-107).

    Prefers the canonical URL. The interface (this module's docstring) doesn't require every
    source to set one, so a source that doesn't falls back to "<source>:<title>" -- still
    stable across repeated fetches of the same item, just coarser than a real URL."""
    return signal.url or f"{signal.source}:{signal.title}"


def content_fingerprint(signal: Signal) -> str:
    """Coarse content identity for a signal, alongside source_key's origin identity (RC-107).

    A signal whose title changed since it was last covered is treated as materially updated
    and becomes eligible again even inside the coverage window -- title is what every
    signals/*.py source refreshes when the underlying item changes (an edited HN title, a
    corrected summary line), so comparing it is a cheap, deterministic proxy for "this isn't
    the same thing already covered," in the same spirit as persona.state's vocabulary-overlap
    "rhyme" check rather than real diffing."""
    return signal.title.strip().lower()


def rank_novelty(rank: int, total: int) -> float:
    """Newest/highest-ranked-first index -> a 0-1 novelty placeholder score.

    Every signals/*.py source uses this same linear decay so there's one place to tune
    once real usage data exists -- the actual scoring formula is an open question in
    docs/SPEC.md ("Exact novelty/significance scoring formula for the signal pool").
    """
    if total <= 1:
        return 1.0
    return round(1.0 - (rank / (total - 1)), 3)
