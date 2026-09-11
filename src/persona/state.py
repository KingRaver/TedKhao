"""Register + Phase taxonomy and classification logic.

See docs/SPEC.md ("Personality Architecture") and VOICE_GUIDE.md for the full definition
of each Register and Phase -- this module is the mechanism, those docs are the meaning.
Keep the enum members in sync with both documents if the taxonomy ever changes.
"""
import random
import re
from enum import Enum
from typing import Optional

from signals.base import Signal


class Register(Enum):
    """Moment-to-moment tone. Drives word choice, rhythm, and voice-bank sampling."""
    DELIGHTED = "delighted"
    AWESTRUCK = "awestruck"
    REVERENT = "reverent"
    WISTFUL = "wistful"
    AMUSED = "amused"
    RESTLESS = "restless"
    PROVOKED = "provoked"
    GIDDY = "giddy"


class Phase(Enum):
    """Macro shape of today's signal pool. Drives content selection, not tone."""
    CONVERGENCE = "convergence"
    BREAKTHROUGH = "breakthrough"
    CONTESTED = "contested"
    ANNIVERSARY = "anniversary"
    EXCAVATION = "excavation"
    QUIET = "quiet"

    @classmethod
    def high_leverage(cls) -> set["Phase"]:
        """Phases worth over-weighting in signal scoring (see docs/SPEC.md)."""
        return {cls.CONVERGENCE, cls.BREAKTHROUGH}


# Which registers make sense for a given detected reply-topic. Mirrors the reference
# repos' contextual tone-selection pattern (bearish topic -> skeptical/contrarian, etc.)
# but built for tech/history/arts topics instead of market sentiment.
_TOPIC_REGISTER_AFFINITY: dict[str, list[Register]] = {
    "contested": [Register.PROVOKED, Register.AMUSED],
    "awe_worthy": [Register.AWESTRUCK, Register.DELIGHTED],
    "loss_or_nostalgia": [Register.WISTFUL, Register.REVERENT],
    "breaking": [Register.GIDDY, Register.RESTLESS],
    "craft_or_mastery": [Register.REVERENT, Register.DELIGHTED],
    "question": [Register.RESTLESS, Register.AMUSED],
}

_ALL_REGISTERS = list(Register)


def select_register_for_reply(topic_tags: list[str],
                               recent_registers: Optional[list[Register]] = None) -> Register:
    """Pick a Register for a reply, biased by detected topic and avoiding recent repeats.

    Args:
        topic_tags: tags from engagement.content_analyzer (e.g. ["contested", "question"])
        recent_registers: last few registers used, to keep output varied (memory.py owns this)

    Returns:
        The selected Register.
    """
    recent_registers = recent_registers or []
    available = [r for r in _ALL_REGISTERS if r not in recent_registers[-3:]] or _ALL_REGISTERS

    candidates: list[Register] = []
    for tag in topic_tags:
        candidates.extend(_TOPIC_REGISTER_AFFINITY.get(tag, []))

    contextual = [r for r in candidates if r in available]
    if contextual:
        return random.choice(contextual)

    return random.choice(available)


# Which registers make sense for a given Phase, for the original-post path (no incoming
# post text to pattern-match against, unlike the reply path above). Drawn straight from the
# per-Phase notes in docs/SPEC.md's Register/Phase tables (e.g. Giddy "pairs with
# Breakthrough phase"; Anniversary implies nostalgia -> Wistful/Reverent).
_PHASE_REGISTER_AFFINITY: dict[Phase, list[Register]] = {
    Phase.CONVERGENCE: [Register.AWESTRUCK, Register.DELIGHTED, Register.RESTLESS],
    Phase.BREAKTHROUGH: [Register.GIDDY, Register.RESTLESS],
    Phase.CONTESTED: [Register.PROVOKED, Register.AMUSED],
    Phase.ANNIVERSARY: [Register.WISTFUL, Register.REVERENT],
    Phase.EXCAVATION: [Register.REVERENT, Register.RESTLESS],
    Phase.QUIET: _ALL_REGISTERS,
}

# Thresholds on Signal.novelty_score (see signals/base.py's rank_novelty) that drive Phase
# detection below. Placeholder cutoffs, not a tuned formula -- docs/SPEC.md flags the real
# novelty/significance scoring formula as an open question pending real signal-pool data.
_CONVERGENCE_NOVELTY_THRESHOLD = 0.7
_BREAKTHROUGH_NOVELTY_THRESHOLD = 0.85
_EXCAVATION_NOVELTY_THRESHOLD = 0.3

# Words too generic to count as evidence two signals are about the same thing (RC-106's
# Convergence "rhyme" check below) -- short/common words would produce false-positive matches
# between genuinely unrelated signals.
_RHYME_STOPWORDS = {
    "about", "after", "their", "there", "these", "those", "which", "while", "would",
    "could", "should", "still", "years", "world", "first", "today", "shows", "study",
}
_RHYME_MIN_WORD_LENGTH = 5


def _pick_register_for_phase(phase: Phase, recent_registers: list[Register]) -> Register:
    available = [r for r in _ALL_REGISTERS if r not in recent_registers[-3:]] or _ALL_REGISTERS
    candidates = [r for r in _PHASE_REGISTER_AFFINITY.get(phase, _ALL_REGISTERS) if r in available]
    return random.choice(candidates or available)


def _select_top_signal(signals: list[Signal]) -> Signal:
    """Pick the highest-novelty signal, breaking ties with an explicit random choice among the
    tied signals instead of relying on list order. Without this, `max()` deterministically
    returns whichever tied signal appears first in the pool -- and since bot.py's
    _DOMAIN_SIGNAL_SOURCES always fetches arxiv first, arxiv would systematically win every tie
    regardless of merit (RC-106)."""
    top_score = max(s.novelty_score for s in signals)
    tied = [s for s in signals if s.novelty_score == top_score]
    return random.choice(tied)


def _significant_words(signal: Signal) -> set[str]:
    words = re.findall(r"[a-z0-9]+", f"{signal.title} {signal.summary}".lower())
    return {w for w in words if len(w) >= _RHYME_MIN_WORD_LENGTH and w not in _RHYME_STOPWORDS}


def _signals_rhyme(a: Signal, b: Signal) -> bool:
    """Lightweight, honest evidence that two different-domain signals are actually about the
    same thing -- shared significant vocabulary in their title/summary -- rather than inferring
    a relationship from domain count alone. Not semantic understanding; a real
    relationship-detection model is future work per docs/SPEC.md's novelty-scoring open
    question. Deliberately no fallback proxy when this comes back empty, same reasoning as
    Contested staying unreachable below."""
    return bool(_significant_words(a) & _significant_words(b))


def _find_convergent_pair(high_novelty: list[Signal]) -> Optional[tuple[Signal, Signal]]:
    """Find two different-domain high-novelty signals that rhyme (see _signals_rhyme). The pool
    is shuffled before the search so which pair is found -- when more than one rhyming pair
    exists -- doesn't inherit the same fetch-order bias _select_top_signal guards against."""
    pool = list(high_novelty)
    random.shuffle(pool)
    for i, a in enumerate(pool):
        for b in pool[i + 1:]:
            if a.domain != b.domain and _signals_rhyme(a, b):
                return (a, b)
    return None


def select_phase_register_and_signal(
    signals: list[Signal],
    recent_phases: Optional[list[Phase]] = None,
    recent_registers: Optional[list[Register]] = None,
) -> tuple[Phase, Register, Optional[Signal]]:
    """Score the day's fetched signal pool into a Phase + Register + which Signal to post
    about -- the original-post equivalent of select_register_for_reply() above.

    This is a first-pass heuristic over structural properties of the pool rather than deep
    semantic content -- detecting real Contested-phase material (a live disagreement) would
    need actual topic/sentiment analysis across signals, which this pool doesn't carry yet,
    so Contested is left unreachable here for now rather than faked from a proxy. The exact
    scoring formula is an open question in docs/SPEC.md and will need tuning once real
    signal data is flowing.

    Two structural fixes (RC-106) shape the heuristic below:
    - Ties on novelty_score are broken with an explicit random choice (_select_top_signal),
      not list order -- otherwise arxiv, always fetched first into the pool, would
      systematically win every tie.
    - Breakthrough requires novelty_evidenced=True (see signals/base.py's Signal.novelty_evidenced):
      a signal's rank_novelty() score alone is not evidence of genuine novelty for sources whose
      fetch order isn't a significance ranking (wikipedia_otd's "on this day" order, arts_feed's
      random sample) -- otherwise a first-ranked historical event or museum object becomes a
      "breakthrough" solely because rank 0 always scores 1.0.
    - Convergence requires two different-domain high-novelty signals to actually rhyme
      (_signals_rhyme -- shared significant vocabulary), not just that >=2 domains independently
      cleared the novelty bar; unrelated high-novelty signals fall through to whichever
      supported single-signal phase applies instead.

    Args:
        signals: the day's fetched signals, pooled across all signals/*.py sources.
        recent_phases: unused for now (signal-driven, not forced into variety) -- accepted
            so callers can pass persona.memory's tracked history without special-casing.
        recent_registers: last few registers used, to keep output varied (memory.py owns this).

    Returns:
        (phase, register, signal) -- signal is None only when the pool itself is empty.
    """
    recent_registers = recent_registers or []

    if not signals:
        return Phase.QUIET, _pick_register_for_phase(Phase.QUIET, recent_registers), None

    top_signal = _select_top_signal(signals)
    high_novelty = [s for s in signals if s.novelty_score >= _CONVERGENCE_NOVELTY_THRESHOLD]
    convergent_pair = _find_convergent_pair(high_novelty)

    if convergent_pair:
        phase = Phase.CONVERGENCE
        signal = _select_top_signal(list(convergent_pair))
    elif top_signal.novelty_evidenced and top_signal.novelty_score >= _BREAKTHROUGH_NOVELTY_THRESHOLD:
        phase = Phase.BREAKTHROUGH
        signal = top_signal
    elif top_signal.source == "wikipedia_otd":
        phase = Phase.ANNIVERSARY
        signal = top_signal
    elif top_signal.novelty_score <= _EXCAVATION_NOVELTY_THRESHOLD:
        phase = Phase.EXCAVATION
        signal = top_signal
    else:
        phase = Phase.QUIET
        signal = top_signal

    register = _pick_register_for_phase(phase, recent_registers)
    return phase, register, signal
