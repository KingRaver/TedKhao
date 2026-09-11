"""RC-108 deterministic checks: prompt-assembly contracts around persona.prompts.build_post_prompt
and the post_handler orchestration that feeds it.

Covers the structural fixes this phase makes:
  * Convergence must be grounded in both rhyming signals, not just the one persisted for the
    post record -- a prompt built from only one had nothing to actually connect. Convergence
    selected without a partner is a broken contract: build_post_prompt raises rather than
    emitting a half-grounded prompt, and generate_post() degrades to an explicit skip instead
    of letting that raise reach the middle of a post cycle.
  * "A callback to an earlier post" (a structural reference to specific prior content) must
    never be offered unless a real confirmed post is actually supplied as context -- otherwise
    the model has nothing to callback to but its own invention.
  * A no-signal prompt must never be offered a structure that presupposes a fact (a comparison,
    a quiet fact stated with commentary) or an earlier post it doesn't have -- only the
    signal-agnostic, non-fabricating options stay reachable.
  * Thread-opening generation is removed entirely from the single-post structure pool.

Uses plain asserts, real Register/Phase/Signal objects, deterministic random.seed() calls, and
a real temporary database for the end-to-end confirmed-history case -- no live model or browser
call, per run_offline.py's no-network rule. Included in `venv/bin/python tests/run_offline.py`
(RC-101). Run with:

    python tests/manual_test_prompt_grounding.py
"""
import os
import random
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import engagement.post_handler as post_handler_module  # noqa: E402
from engagement.post_handler import generate_post  # noqa: E402
from llm_provider import LLMProvider  # noqa: E402
from persona.memory import PersonaMemory  # noqa: E402
from persona.prompts import (  # noqa: E402
    _CALLBACK_STRUCTURE, _SIGNAL_REQUIRED_STRUCTURES, POST_STRUCTURE_POOL, build_post_prompt,
)
from persona.state import Phase, Register  # noqa: E402
from signals.base import Signal  # noqa: E402


class FakeProvider(LLMProvider):
    """Deterministic, no-network stand-in, same shape as the other offline harnesses."""

    def generate(self, prompt: str, system_prompt: str | None = None,
                 max_tokens: int = 300, temperature: float = 0.8) -> str:
        return "A perfectly reasonable, nonempty generated post about something curious."


def _signal(title: str, summary: str = "", source: str = "arxiv",
            domain: str = "technology", url: str = "https://example.org/x") -> Signal:
    return Signal(source=source, domain=domain, title=title, summary=summary, url=url,
                  novelty_score=0.9, novelty_evidenced=True)


def _structure_of(prompt: str) -> str:
    prefix = "Structure the post as: "
    for line in prompt.splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].rstrip(".")
    raise AssertionError("Prompt has no 'Structure the post as:' line")


# --- thread-opening is gone from the single-post structure pool -----------------------------

def test_thread_opening_structure_removed() -> None:
    assert not any("thread" in s.lower() for s in POST_STRUCTURE_POOL), (
        "thread-opening generation must be removed from the single-post workflow (RC-108) -- "
        "full thread publishing is deferred and needs its own tracked scope"
    )
    print("  thread-opening structure removed from POST_STRUCTURE_POOL: OK")


# --- Convergence must be grounded in both signals, or the phase is refused ------------------

def test_convergence_prompt_includes_both_signals() -> None:
    first = _signal("A diffusion model flags disputed Rembrandt attributions",
                     "Brushstroke analysis via a trained classifier.",
                     source="arxiv", domain="technology")
    second = _signal("A newly attributed Rembrandt drawing surfaces",
                      "Pigment analysis reattributes a sketch to the artist himself.",
                      source="met_museum", domain="arts")
    random.seed(3)
    prompt = build_post_prompt(Phase.CONVERGENCE, Register.AWESTRUCK, first, second)
    assert first.title in prompt and second.title in prompt, (
        "Convergence prompt must ground both rhyming signals, not just the one persisted "
        "for the post record"
    )
    print("  Convergence prompt includes both supporting signals: OK")


def test_convergence_without_partner_raises() -> None:
    signal = _signal("A lone signal with no partner")
    try:
        build_post_prompt(Phase.CONVERGENCE, Register.AWESTRUCK, signal, None)
    except ValueError:
        pass
    else:
        raise AssertionError(
            "Convergence without a convergence_partner must raise, not silently emit a "
            "half-grounded prompt"
        )
    print("  Convergence without a supporting signal raises rather than degrading: OK")


def test_post_handler_skips_convergence_missing_partner() -> None:
    # Simulate persona.state breaking its own contract (Convergence selected with no partner)
    # to prove post_handler.generate_post() degrades gracefully -- an explicit skip, matching
    # RC-107's skip-over-silently-wrong-behavior precedent -- instead of letting
    # build_post_prompt's guard raise in the middle of a post cycle.
    def broken_selection(signals, recent_phases, recent_registers):
        return Phase.CONVERGENCE, Register.AWESTRUCK, signals[0], None

    with tempfile.TemporaryDirectory() as tmp:
        memory = PersonaMemory(db_path=os.path.join(tmp, "test.db"))
        signal = _signal("A signal that will never reach the model")
        with patch.object(post_handler_module, "select_phase_register_and_signal",
                           side_effect=broken_selection):
            result = generate_post([signal], FakeProvider(), memory)

    assert result["skipped"] == "convergence_missing_supporting_signal"
    assert result["post_text"] is None and result["post_id"] is None
    print("  post_handler skips (not crashes) when Convergence's contract breaks upstream: OK")


# --- a structural callback requires a real confirmed earlier post ---------------------------

def test_callback_structure_unreachable_without_confirmed_post() -> None:
    signal = _signal("A perfectly ordinary technology signal", "Some detail.")
    for seed in range(60):
        random.seed(seed)
        prompt = build_post_prompt(Phase.QUIET, Register.RESTLESS, signal)
        assert _structure_of(prompt) != _CALLBACK_STRUCTURE, (
            "callback structure must never be offered without a confirmed earlier post"
        )
    print("  callback structure unreachable across 60 seeds with no confirmed earlier post: OK")


def test_callback_structure_reachable_and_grounded_with_confirmed_post() -> None:
    signal = _signal("A perfectly ordinary technology signal", "Some detail.")
    earlier = "A genuinely earlier, already-confirmed post about lighthouse keepers."
    seen_callback = False
    for seed in range(60):
        random.seed(seed)
        prompt = build_post_prompt(Phase.QUIET, Register.RESTLESS, signal,
                                    last_confirmed_post=earlier)
        assert earlier in prompt, "the real confirmed post text must be given as context"
        if _structure_of(prompt) == _CALLBACK_STRUCTURE:
            seen_callback = True
    assert seen_callback, "callback structure must be reachable once a confirmed post exists"
    print("  callback structure reachable and grounded in the real confirmed post: OK")


# --- no-signal prompts can't select a structure that presupposes an unavailable fact ---------

def test_no_signal_prompt_excludes_fact_and_callback_structures() -> None:
    for seed in range(60):
        random.seed(seed)
        prompt = build_post_prompt(Phase.QUIET, Register.RESTLESS, None)
        structure = _structure_of(prompt)
        assert structure not in _SIGNAL_REQUIRED_STRUCTURES, (
            f"no-signal prompt selected {structure!r}, which presupposes a fact there's no "
            "signal to supply"
        )
        assert structure != _CALLBACK_STRUCTURE, (
            "no-signal prompt with no confirmed earlier post must not offer a callback either"
        )
    print("  no-signal, no-history prompt never selects a fact- or earlier-post-requiring "
          "structure across 60 seeds: OK")


def test_no_signal_prompt_allows_grounded_callback_when_confirmed_post_supplied() -> None:
    earlier = "A genuinely earlier, already-confirmed post about a shipwreck."
    seen_callback = False
    for seed in range(60):
        random.seed(seed)
        prompt = build_post_prompt(Phase.QUIET, Register.RESTLESS, None,
                                    last_confirmed_post=earlier)
        structure = _structure_of(prompt)
        assert structure not in _SIGNAL_REQUIRED_STRUCTURES
        if structure == _CALLBACK_STRUCTURE:
            seen_callback = True
            assert earlier in prompt
    assert seen_callback, (
        "a real confirmed post should make the callback structure reachable even on a day "
        "with no signal at all"
    )
    print("  no-signal prompt still allows a grounded callback once a confirmed post exists: OK")


def test_single_signal_prompt_allows_fact_requiring_structures() -> None:
    signal = _signal("A concrete technology finding", "Enough detail to compare against.")
    seen_fact_requiring = False
    for seed in range(60):
        random.seed(seed)
        prompt = build_post_prompt(Phase.EXCAVATION, Register.REVERENT, signal)
        if _structure_of(prompt) in _SIGNAL_REQUIRED_STRUCTURES:
            seen_fact_requiring = True
    assert seen_fact_requiring, (
        "a real signal should still make fact-requiring structures reachable -- the no-signal "
        "restriction must not over-apply to the normal, signal-grounded path"
    )
    print("  single-signal prompt still allows fact-requiring structures: OK")


# --- end-to-end: a real confirmed post grounds the next generation's callback context --------

def _confirm_post(memory: PersonaMemory, content: str) -> None:
    publication_id, _post_id = memory.save_draft(content, Register.DELIGHTED, Phase.QUIET)
    memory.transition_publication(publication_id, "attempted")
    memory.transition_publication(publication_id, "confirmed", external_id="ext-earlier")


def test_generate_post_grounds_callback_in_real_confirmed_history() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        memory = PersonaMemory(db_path=os.path.join(tmp, "test.db"))
        assert memory.last_confirmed_post() is None, "no post confirmed yet"

        earlier_text = "An earlier, already-confirmed post about tide-predicting machines."
        _confirm_post(memory, earlier_text)
        assert memory.last_confirmed_post() == earlier_text

        captured_prompts: list[str] = []
        real_build_post_prompt = post_handler_module.build_post_prompt

        def capturing_build(*args, **kwargs):
            prompt = real_build_post_prompt(*args, **kwargs)
            captured_prompts.append(prompt)
            return prompt

        signal = _signal("A fresh technology signal", "Some detail.")
        with patch.object(post_handler_module, "build_post_prompt", side_effect=capturing_build):
            result = generate_post([signal], FakeProvider(), memory)

        assert result["post_text"] is not None and not result.get("skipped")
        assert captured_prompts and earlier_text in captured_prompts[-1], (
            "generate_post must pass the real confirmed post through as callback context, "
            "never a fabricated one"
        )
    print("  generate_post grounds callback context in a real confirmed post, end-to-end: OK")


def main() -> None:
    print("Phase 8 (RC-108) prompt-grounding regression checks")

    test_thread_opening_structure_removed()
    test_convergence_prompt_includes_both_signals()
    test_convergence_without_partner_raises()
    test_post_handler_skips_convergence_missing_partner()
    test_callback_structure_unreachable_without_confirmed_post()
    test_callback_structure_reachable_and_grounded_with_confirmed_post()
    test_no_signal_prompt_excludes_fact_and_callback_structures()
    test_no_signal_prompt_allows_grounded_callback_when_confirmed_post_supplied()
    test_single_signal_prompt_allows_fact_requiring_structures()
    test_generate_post_grounds_callback_in_real_confirmed_history()

    print("\nAll prompt-grounding checks passed.")


if __name__ == "__main__":
    main()
