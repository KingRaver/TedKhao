"""Ties content analysis, register selection, prompt construction, and the LLM provider
together into a single generate_reply() call -- the full reply pipeline described in
docs/SPEC.md's four-layer architecture.
"""
from engagement.content_analyzer import analyze_post
from llm_provider import GenerationError, LLMProvider
from persona.memory import PersonaMemory
from persona.prompts import build_reply_prompt, build_shorten_prompt
from persona.state import Register, select_register_for_reply
import config


def generate_reply(post: dict, llm_provider: LLMProvider, memory: PersonaMemory) -> dict:
    """Generate a reply to a single fake/real post.

    Args:
        post: dict with at least 'id', 'author_handle', 'text'
        llm_provider: any LLMProvider implementation
        memory: shared PersonaMemory instance for anti-repetition

    Returns:
        dict with the generated reply plus the register/analysis used, for inspection.
    """
    analysis = analyze_post(post["text"])
    register: Register = select_register_for_reply(
        analysis["topic_tags"], memory.recent_registers
    )

    prompt = build_reply_prompt(
        post_text=post["text"],
        author_handle=post.get("author_handle", "@someone"),
        register=register,
        topic_tags=analysis["topic_tags"],
    )

    reply_text = _generate_nonempty(
        llm_provider, prompt, max_tokens=200, temperature=0.9,
        attempts=config.REPLY_GENERATION_ATTEMPTS, label="reply generation",
    )
    reply_text = _ensure_length(reply_text, llm_provider)

    publication_id, _ = memory.save_draft(reply_text, register, target=post)

    return {
        "post": post,
        "publication_id": publication_id,
        "analysis": analysis,
        "register": register,
        "reply_text": reply_text,
    }


def _generate_nonempty(llm_provider: LLMProvider, prompt: str, *, max_tokens: int,
                        temperature: float, attempts: int, label: str) -> str:
    """Call llm_provider.generate() up to `attempts` times, returning the first result that
    is nonempty after stripping whitespace. A GenerationError (missing/null/malformed
    provider output -- see llm_provider.py) counts as an invalid attempt, not an unhandled
    crash. Raises GenerationError, without ever returning empty text, once every attempt is
    exhausted -- callers must not persist a draft or consume a reply target on this path.
    """
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            text = llm_provider.generate(
                prompt, max_tokens=max_tokens, temperature=temperature
            ).strip()
        except GenerationError as error:
            last_error = error
            continue
        if text:
            return text
    detail = f" (last error: {last_error})" if last_error else " (empty output)"
    raise GenerationError(f"{label} produced no usable text after {attempts} attempt(s){detail}")


def _ensure_length(text: str, llm_provider: LLMProvider) -> str:
    """Bring an over-length reply within the hard limit by having the model rewrite it.

    String-truncation can't "solve" an over-length reply -- it can only hide the symptom
    by cutting content, which is exactly the mid-sentence chop this replaces. The correct
    fix is generation-side: ask the model to compress its own reply, preserving voice and
    meaning, retrying a bounded number of times. Sentence-aware truncation is kept only as
    a last-resort safety net for the rare case the model can't converge -- we must never
    post something over the platform's hard limit, but reaching that fallback should be
    uncommon once the soft target in build_reply_prompt and this loop are doing their job.

    `text` is always nonempty on entry (generate_reply() validates it via
    _generate_nonempty() first), so `last_valid` -- the shortening candidate the final
    truncation falls back to -- is never empty either. A shorten attempt that comes back
    missing/null/malformed (GenerationError) or empty after stripping is treated as a
    wasted attempt rather than accepted output (RC-105): it neither returns early nor
    replaces `last_valid`, it just consumes one of the bounded attempts.
    """
    text = text.strip()
    if len(text) <= config.REPLY_MAX_CHARS:
        return text

    last_valid = text
    for _ in range(config.REPLY_SHORTEN_ATTEMPTS):
        shorten_prompt = build_shorten_prompt(last_valid, config.REPLY_MAX_CHARS)
        try:
            candidate = llm_provider.generate(
                shorten_prompt, max_tokens=150, temperature=0.5
            ).strip()
        except GenerationError:
            continue
        if not candidate:
            continue
        last_valid = candidate
        if len(candidate) <= config.REPLY_MAX_CHARS:
            return candidate

    return _sentence_aware_truncate(last_valid, config.REPLY_MAX_CHARS)


def _sentence_aware_truncate(text: str, max_chars: int) -> str:
    """Last-resort safety net only -- see _ensure_length. Never the primary mechanism.

    Prefers cutting at the end of the last complete sentence that fits (no ellipsis
    needed -- it already reads as finished). Only falls back to a word-boundary cut
    with a trailing ellipsis if no sentence boundary is available, and that fallback
    always reserves room for the ellipsis so the result never exceeds max_chars.
    """
    text = text.strip()
    if len(text) <= max_chars:
        return text

    sentence_end = max(
        text.rfind(ender, 0, max_chars) for ender in (".", "!", "?")
    )
    if sentence_end >= max_chars * 0.6:
        return text[:sentence_end + 1].strip()

    ellipsis = "..."
    limit = max_chars - len(ellipsis)
    truncated = text[:limit]
    last_space = truncated.rfind(" ")
    if last_space > limit * 0.6:
        truncated = truncated[:last_space]
    return truncated.rstrip() + ellipsis
