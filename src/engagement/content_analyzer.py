"""Lightweight incoming-post classification.

Keyword/pattern based for now, matching the reference architecture's approach but scoped down
-- this exists to feed persona.state.select_register_for_reply with topic_tags, not to be a
full NLP pipeline. Expand as real timeline data reveals gaps.
"""
import re

_CONTESTED_PATTERNS = [
    r"\b(ai|artificial intelligence) (just )?(invented|solved|killed|ended)\b",
    r"\bnobody (talks about|knows)\b",
    r"\beveryone (knows|agrees)\b",
    r"\b(obviously|clearly) (the best|the worst|wrong|right)\b",
]

_AWE_PATTERNS = [
    r"\b(billion|trillion|light.?year|millenni|thousand years?)\b",
    r"\b(vast|enormous|staggering|unimaginable)\b",
]

_LOSS_PATTERNS = [
    r"\b(lost|destroyed|demolished|extinct|forgotten|deprecated|shut ?down)\b",
]

_CRAFT_PATTERNS = [
    r"\b(handmade|craft|technique|master(piece|ful)?|restoration|apprentice)\b",
]

_BREAKING_PATTERNS = [
    r"\bjust (announced|released|dropped|published|discovered)\b",
    r"\bbreaking\b",
]


def _matches_any(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def analyze_post(text: str) -> dict:
    """Classify a single post's text into topic tags and basic features.

    Returns a dict with:
        topic_tags: list[str] -- feeds persona.state.select_register_for_reply
        is_question: bool
        domain_guess: str -- rough guess at 'technology' | 'history' | 'arts' | 'general'
    """
    tags = []
    if _matches_any(_CONTESTED_PATTERNS, text):
        tags.append("contested")
    if _matches_any(_AWE_PATTERNS, text):
        tags.append("awe_worthy")
    if _matches_any(_LOSS_PATTERNS, text):
        tags.append("loss_or_nostalgia")
    if _matches_any(_CRAFT_PATTERNS, text):
        tags.append("craft_or_mastery")
    if _matches_any(_BREAKING_PATTERNS, text):
        tags.append("breaking")

    is_question = "?" in text
    if is_question:
        tags.append("question")

    domain_guess = "general"
    if re.search(r"\b(ai|algorithm|software|code|computer|tech|robot|internet)\b", text, re.IGNORECASE):
        domain_guess = "technology"
    elif re.search(r"\b(history|ancient|century|empire|war|dynasty|revolution)\b", text, re.IGNORECASE):
        domain_guess = "history"
    elif re.search(r"\b(art|museum|painting|sculpture|music|film|novel|poem)\b", text, re.IGNORECASE):
        domain_guess = "arts"

    return {
        "topic_tags": tags,
        "is_question": is_question,
        "domain_guess": domain_guess,
    }
