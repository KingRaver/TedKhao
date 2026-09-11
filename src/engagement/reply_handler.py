"""Ties content analysis, register selection, prompt construction, and the LLM provider
together into a single generate_reply() call -- the full reply pipeline described in
docs/SPEC.md's four-layer architecture.
"""
from engagement.content_analyzer import analyze_post
from llm_provider import LLMProvider
from persona.memory import PersonaMemory
from persona.prompts import build_reply_prompt
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

    reply_text = llm_provider.generate(prompt, max_tokens=200, temperature=0.9)
    reply_text = _enforce_length(reply_text, config.REPLY_MAX_CHARS)

    memory.record_register(register)
    memory.mark_replied(post["id"])

    return {
        "post": post,
        "analysis": analysis,
        "register": register,
        "reply_text": reply_text,
    }


def _enforce_length(text: str, max_chars: int) -> str:
    """Bring text within max_chars without lopping off mid-sentence.

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
