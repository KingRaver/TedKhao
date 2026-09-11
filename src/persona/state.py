"""Register + Phase taxonomy and classification logic.

See docs/SPEC.md ("Personality Architecture") and VOICE_GUIDE.md for the full definition
of each Register and Phase -- this module is the mechanism, those docs are the meaning.
Keep the enum members in sync with both documents if the taxonomy ever changes.
"""
import random
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


def _pick_register_for_phase(phase: Phase, recent_registers: list[Register]) -> Register:
    available = [r for r in _ALL_REGISTERS if r not in recent_registers[-3:]] or _ALL_REGISTERS
    candidates = [r for r in _PHASE_REGISTER_AFFINITY.get(phase, _ALL_REGISTERS) if r in available]
    return random.choice(candidates or available)


def select_phase_register_and_signal(
    signals: list[Signal],
    recent_phases: Optional[list[Phase]] = None,
    recent_registers: Optional[list[Register]] = None,
) -> tuple[Phase, Register, Optional[Signal]]:
    """Score the day's fetched signal pool into a Phase + Register + which Signal to post
    about -- the original-post equivalent of select_register_for_reply() above.

    This is a first-pass heuristic over structural properties of the pool (how many domains
    have high-novelty signals, the top signal's novelty_score, its source) rather than
    semantic content -- detecting real Contested-phase material (a live disagreement) would
    need actual topic/sentiment analysis across signals, which this pool doesn't carry yet,
    so Contested is left unreachable here for now rather than faked from a proxy. The exact
    scoring formula is an open question in docs/SPEC.md and will need tuning once real
    signal data is flowing.

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

    top_signal = max(signals, key=lambda s: s.novelty_score)
    high_novelty_domains = {
        s.domain for s in signals if s.novelty_score >= _CONVERGENCE_NOVELTY_THRESHOLD
    }

    if len(high_novelty_domains) >= 2:
        phase = Phase.CONVERGENCE
    elif top_signal.novelty_score >= _BREAKTHROUGH_NOVELTY_THRESHOLD:
        phase = Phase.BREAKTHROUGH
    elif top_signal.source == "wikipedia_otd":
        phase = Phase.ANNIVERSARY
    elif top_signal.novelty_score <= _EXCAVATION_NOVELTY_THRESHOLD:
        phase = Phase.EXCAVATION
    else:
        phase = Phase.QUIET

    register = _pick_register_for_phase(phase, recent_registers)
    return phase, register, top_signal
