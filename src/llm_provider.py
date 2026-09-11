"""Provider-agnostic LLM abstraction.

The persona layer never talks to an SDK directly -- it calls `get_provider().generate(...)`.
Which backend answers that call (a hosted API today, a local model on the M4 later) is purely
a config decision (see config.LLM_PROVIDER), never a code change.
"""
from abc import ABC, abstractmethod

import requests

import config


class LLMProvider(ABC):
    @abstractmethod
    def generate(self, prompt: str, system_prompt: str | None = None,
                 max_tokens: int = 300, temperature: float = 0.8) -> str:
        ...


class AnthropicProvider(LLMProvider):
    """Hosted Claude API -- used for development and testing."""

    def __init__(self, api_key: str, model: str):
        import anthropic
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is not set. Add it to .env (copy .env.example first)."
            )
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def generate(self, prompt: str, system_prompt: str | None = None,
                 max_tokens: int = 300, temperature: float = 0.8) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt or "",
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()


class OpenAICompatibleProvider(LLMProvider):
    """Anything speaking the OpenAI /v1/chat/completions protocol.

    This is the adapter used for the local-model path: point base_url at the M4's
    Ollama endpoint (e.g. http://<m4-hostname>.local:11434/v1) and it behaves
    identically to calling any hosted API.
    """

    def __init__(self, base_url: str, model: str, api_key: str | None = None):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key or "not-needed-for-local"

    def generate(self, prompt: str, system_prompt: str | None = None,
                 max_tokens: int = 300, temperature: float = 0.8) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = requests.post(
            f"{self._base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "model": self._model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()


def get_provider() -> LLMProvider:
    """Factory: reads config.LLM_PROVIDER and returns the matching adapter."""
    if config.LLM_PROVIDER == "anthropic":
        return AnthropicProvider(config.ANTHROPIC_API_KEY, config.ANTHROPIC_MODEL)
    elif config.LLM_PROVIDER == "local":
        return OpenAICompatibleProvider(config.LOCAL_LLM_BASE_URL, config.LOCAL_LLM_MODEL)
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {config.LLM_PROVIDER!r}")
