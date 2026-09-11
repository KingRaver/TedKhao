"""RC-105 deterministic checks: invalid provider output must never reach a publishable draft
or consume a reply target, and bounded regeneration must actually bound.

Two layers are exercised, matching this phase's file scope:
  * llm_provider.py -- missing/null/malformed provider responses raise GenerationError
    instead of a bare IndexError/KeyError/AttributeError, for both provider adapters.
  * engagement.post_handler/reply_handler -- generate_post()/generate_reply() validate
    nonempty text on initial generation and every shortening response, retry a bounded
    number of times, and raise GenerationError (never persisting an empty draft or holding
    a reply target) once attempts are exhausted. The existing overlength shorten/truncate
    fallback path keeps working once empty/malformed shorten attempts are skipped rather
    than accepted.

Included in `venv/bin/python tests/run_offline.py` (RC-101). Uses plain asserts. Run with:

    python tests/manual_test_generation_validation.py
"""
import os
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import config  # noqa: E402
import database  # noqa: E402
from engagement.post_handler import generate_post  # noqa: E402
from engagement.reply_handler import generate_reply  # noqa: E402
from llm_provider import AnthropicProvider, GenerationError, LLMProvider, OpenAICompatibleProvider  # noqa: E402
from persona.memory import PersonaMemory  # noqa: E402


def expect_error(call, error=Exception):
    try:
        call()
    except error:
        return
    raise AssertionError(f"expected {error.__name__}")


# --- llm_provider.py: malformed/missing/null responses become GenerationError ---------------

def test_anthropic_provider_malformed_responses() -> None:
    provider = AnthropicProvider(api_key="fake-test-key", model="fake-model")

    with patch.object(provider._client.messages, "create",
                       return_value=SimpleNamespace(content=[])):
        expect_error(lambda: provider.generate("prompt"), GenerationError)

    with patch.object(provider._client.messages, "create",
                       return_value=SimpleNamespace(content=[SimpleNamespace(text=None)])):
        expect_error(lambda: provider.generate("prompt"), GenerationError)

    with patch.object(provider._client.messages, "create",
                       return_value=SimpleNamespace(content=[SimpleNamespace(text="  hi there  ")])):
        assert provider.generate("prompt") == "hi there"

    print("  AnthropicProvider: empty content, null text -> GenerationError; valid text -> OK")


def test_openai_compatible_provider_malformed_responses() -> None:
    provider = OpenAICompatibleProvider(base_url="http://fake-local-host:11434/v1", model="fake-model")

    def fake_response(json_result=None, json_error=None):
        def raise_for_status():
            return None

        def json_call():
            if json_error is not None:
                raise json_error
            return json_result

        return SimpleNamespace(raise_for_status=raise_for_status, json=json_call)

    with patch("llm_provider.requests.post", return_value=fake_response(json_error=ValueError("bad json"))):
        expect_error(lambda: provider.generate("prompt"), GenerationError)

    with patch("llm_provider.requests.post", return_value=fake_response(json_result={"choices": []})):
        expect_error(lambda: provider.generate("prompt"), GenerationError)

    with patch("llm_provider.requests.post",
               return_value=fake_response(json_result={"choices": [{"message": {"content": None}}]})):
        expect_error(lambda: provider.generate("prompt"), GenerationError)

    with patch("llm_provider.requests.post",
               return_value=fake_response(json_result={"choices": [{"message": {"content": "  hi  "}}]})):
        assert provider.generate("prompt") == "hi"

    print("  OpenAICompatibleProvider: bad JSON, missing choices, null content -> GenerationError; "
          "valid content -> OK")


# --- engagement handlers: nonempty validation + bounded regeneration ------------------------

class _CallSequenceProvider(LLMProvider):
    """Returns a different scripted result on each successive call, then repeats the last
    entry. Entries are either a string (returned as-is) or a GenerationError instance/class
    (raised) -- lets one fake provider script "malformed then empty then valid" sequences
    without needing three separate classes."""

    def __init__(self, results: list):
        self._results = results
        self.calls = 0

    def generate(self, prompt: str, system_prompt: str | None = None,
                 max_tokens: int = 300, temperature: float = 0.8) -> str:
        index = min(self.calls, len(self._results) - 1)
        result = self._results[index]
        self.calls += 1
        if isinstance(result, type) and issubclass(result, Exception):
            raise result("scripted failure")
        if isinstance(result, Exception):
            raise result
        return result


def _counts(db_path: str) -> tuple[int, int]:
    conn = sqlite3.connect(db_path)
    try:
        posts = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        publications = conn.execute("SELECT COUNT(*) FROM publications").fetchone()[0]
        return posts, publications
    finally:
        conn.close()


def test_generate_post_rejects_whitespace_only_output(db_path: str) -> None:
    memory = PersonaMemory(db_path=db_path)
    before = _counts(db_path)
    provider = _CallSequenceProvider(["   \n\t  "])

    expect_error(lambda: generate_post([], provider, memory), GenerationError)

    assert provider.calls == config.POST_GENERATION_ATTEMPTS, (
        "regeneration attempts must be bounded, not retried forever"
    )
    assert _counts(db_path) == before, (
        "whitespace-only generation must never persist a draft"
    )
    print("  generate_post: whitespace-only output -> bounded GenerationError, no draft persisted: OK")


def test_generate_post_rejects_provider_generation_error(db_path: str) -> None:
    memory = PersonaMemory(db_path=db_path)
    before = _counts(db_path)
    provider = _CallSequenceProvider([GenerationError])

    expect_error(lambda: generate_post([], provider, memory), GenerationError)

    assert provider.calls == config.POST_GENERATION_ATTEMPTS
    assert _counts(db_path) == before, (
        "a provider that only ever raises GenerationError must never persist a draft"
    )
    print("  generate_post: provider raises GenerationError every attempt -> "
          "bounded failure, no draft persisted: OK")


def test_generate_post_recovers_within_bounded_attempts(db_path: str) -> None:
    memory = PersonaMemory(db_path=db_path)
    provider = _CallSequenceProvider(["   ", "a perfectly good post about something curious"])

    result = generate_post([], provider, memory)

    assert result["post_text"] == "a perfectly good post about something curious"
    assert provider.calls == 2, "must stop retrying as soon as a valid attempt succeeds"
    print("  generate_post: first attempt empty, second attempt valid -> succeeds within bound: OK")


def test_generate_reply_rejects_null_and_empty_output(db_path: str) -> None:
    memory = PersonaMemory(db_path=db_path)
    fake_post = {"id": "gen-validation-null", "author_handle": "@x", "text": "a post about history"}
    provider = _CallSequenceProvider([GenerationError, "   "])

    expect_error(lambda: generate_reply(fake_post, provider, memory), GenerationError)

    assert provider.calls == config.REPLY_GENERATION_ATTEMPTS
    assert not memory.reply_is_held(fake_post["id"]), (
        "a failed generation must not consume/hold the reply target"
    )
    print("  generate_reply: malformed then empty output -> bounded GenerationError, "
          "target not held: OK")


def test_generate_reply_valid_output(db_path: str) -> None:
    memory = PersonaMemory(db_path=db_path)
    fake_post = {"id": "gen-validation-valid", "author_handle": "@x", "text": "a post about art"}
    provider = _CallSequenceProvider(["a genuinely thoughtful reply about that fresco"])

    result = generate_reply(fake_post, provider, memory)

    assert result["reply_text"] == "a genuinely thoughtful reply about that fresco"
    print("  generate_reply: valid output on first attempt -> OK")


# --- _ensure_length shortening loop: empty/malformed shorten attempts must not win ----------

def _overlength_text(marker: str) -> str:
    return f"{marker} " + ("word " * 60)  # well over both REPLY_MAX_CHARS and POST_MAX_CHARS


def test_ensure_length_skips_empty_shorten_attempts(db_path: str) -> None:
    memory = PersonaMemory(db_path=db_path)
    fake_post = {"id": "gen-validation-shorten-empty", "author_handle": "@x", "text": "a post"}
    long_text = _overlength_text("initial")
    provider = _CallSequenceProvider([long_text, "   ", GenerationError])

    result = generate_reply(fake_post, provider, memory)

    assert result["reply_text"], "an empty shorten attempt must never produce an empty reply"
    assert len(result["reply_text"]) <= config.REPLY_MAX_CHARS
    print("  generate_reply _ensure_length: empty/malformed shorten attempts skipped, "
          "falls back to truncating the last valid (over-length) text: OK")


def test_ensure_length_accepts_valid_shorten_attempt(db_path: str) -> None:
    memory = PersonaMemory(db_path=db_path)
    fake_post = {"id": "gen-validation-shorten-valid", "author_handle": "@x", "text": "a post"}
    long_text = _overlength_text("initial")
    short_text = "a properly shortened reply that fits comfortably under the limit"
    provider = _CallSequenceProvider([long_text, short_text])

    result = generate_reply(fake_post, provider, memory)

    assert result["reply_text"] == short_text, (
        "a valid, in-limit shorten attempt must be accepted as-is"
    )
    print("  generate_reply _ensure_length: valid shorten attempt accepted early: OK")


def test_ensure_length_existing_truncation_path_still_works(db_path: str) -> None:
    memory = PersonaMemory(db_path=db_path)
    fake_post = {"id": "gen-validation-truncate", "author_handle": "@x", "text": "a post"}
    long_text = _overlength_text("initial")
    still_long = _overlength_text("shortened but still too long somehow")
    provider = _CallSequenceProvider([long_text, still_long])

    result = generate_reply(fake_post, provider, memory)

    assert result["reply_text"], "the truncation fallback must never produce empty text"
    assert len(result["reply_text"]) <= config.REPLY_MAX_CHARS, (
        "the existing sentence-aware-truncate safety net must still enforce the hard limit"
    )
    print("  generate_reply _ensure_length: every shorten attempt still over length -> "
          "existing sentence-aware truncation fallback still enforces the hard limit: OK")


def main() -> None:
    print("Phase 5 (RC-105) generation-validation regression checks")

    test_anthropic_provider_malformed_responses()
    test_openai_compatible_provider_malformed_responses()

    with tempfile.TemporaryDirectory() as tmp_dir:
        test_generate_post_rejects_whitespace_only_output(
            os.path.join(tmp_dir, "post_whitespace.db"))
        test_generate_post_rejects_provider_generation_error(
            os.path.join(tmp_dir, "post_provider_error.db"))
        test_generate_post_recovers_within_bounded_attempts(
            os.path.join(tmp_dir, "post_recovers.db"))
        test_generate_reply_rejects_null_and_empty_output(
            os.path.join(tmp_dir, "reply_null_empty.db"))
        test_generate_reply_valid_output(
            os.path.join(tmp_dir, "reply_valid.db"))
        test_ensure_length_skips_empty_shorten_attempts(
            os.path.join(tmp_dir, "shorten_empty.db"))
        test_ensure_length_accepts_valid_shorten_attempt(
            os.path.join(tmp_dir, "shorten_valid.db"))
        test_ensure_length_existing_truncation_path_still_works(
            os.path.join(tmp_dir, "shorten_truncate.db"))

    print("\nAll generation-validation checks passed.")


if __name__ == "__main__":
    main()
