"""Ties signal-pool scoring, prompt construction, and the LLM provider together into a
single generate_post() call -- the original-post equivalent of
engagement.reply_handler.generate_reply(). Lives here (not inline in bot.py) so bot.py stays
a thin orchestrator per docs/STRUCTURE.md -- see docs/SCAFFOLDING.md's Phase 4/5/6 notes,
which deferred this exact module to Phase 7.
"""
from engagement.reply_handler import _generate_nonempty, _sentence_aware_truncate
from llm_provider import GenerationError, LLMProvider
from persona.memory import PersonaMemory
from persona.prompts import build_post_prompt, build_shorten_prompt
from persona.state import select_phase_register_and_signal
from signals.base import Signal
import config


def generate_post(signals: list[Signal], llm_provider: LLMProvider, memory: PersonaMemory) -> dict:
    """Score the given signal pool, generate an original post, and persist it.

    Args:
        signals: the current cycle's fetched signals, pooled across signals/*.py sources.
        llm_provider: any LLMProvider implementation
        memory: shared PersonaMemory instance for anti-repetition

    Returns:
        dict with the generated post plus the phase/register/signal used, for inspection.
    """
    phase, register, signal = select_phase_register_and_signal(
        signals, memory.recent_phases, memory.recent_registers
    )

    prompt = build_post_prompt(phase, register, signal)
    post_text = _generate_nonempty(
        llm_provider, prompt, max_tokens=250, temperature=0.9,
        attempts=config.POST_GENERATION_ATTEMPTS, label="post generation",
    )
    post_text = _ensure_length(post_text, llm_provider)

    publication_id, post_id = memory.save_draft(post_text, register, phase, signal)

    return {
        "post_id": post_id,
        "publication_id": publication_id,
        "post_text": post_text,
        "phase": phase,
        "register": register,
        "signal": signal,
    }


def _ensure_length(text: str, llm_provider: LLMProvider) -> str:
    """Same shorten-then-truncate shape as engagement.reply_handler._ensure_length, scaled to
    POST_MAX_CHARS -- including the RC-105 fix that skips empty/malformed shorten attempts
    instead of accepting them. See that function's docstring for the full rationale."""
    text = text.strip()
    if len(text) <= config.POST_MAX_CHARS:
        return text

    last_valid = text
    for _ in range(config.POST_SHORTEN_ATTEMPTS):
        shorten_prompt = build_shorten_prompt(last_valid, config.POST_MAX_CHARS)
        try:
            candidate = llm_provider.generate(
                shorten_prompt, max_tokens=150, temperature=0.5
            ).strip()
        except GenerationError:
            continue
        if not candidate:
            continue
        last_valid = candidate
        if len(candidate) <= config.POST_MAX_CHARS:
            return candidate

    return _sentence_aware_truncate(last_valid, config.POST_MAX_CHARS)
