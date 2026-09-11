"""Register + Phase taxonomy and classification logic.

See docs/SPEC.md ("Personality Architecture") and VOICE_GUIDE.md for the full definition
of each Register and Phase -- this module is the mechanism, those docs are the meaning.
Keep the enum members in sync with both documents if the taxonomy ever changes.
"""
import random
from enum import Enum
from typing import Optional


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
