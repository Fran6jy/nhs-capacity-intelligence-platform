"""Centralised LLM client. Supports Anthropic, OpenRouter, OpenAI, Azure, and a
no-op fallback that returns canned responses — keeping the app usable without
an API key.

Set `LLM_PROVIDER=openai` (default) and `OPENAI_API_KEY=sk-…` to enable
the real model.
"""
from __future__ import annotations

from functools import lru_cache

from src.config import settings
from src.utils.logging import get_logger

log = get_logger("llm.client")


class _EchoLLM:
    """Local fallback LLM that returns a templated answer."""

    def invoke(self, messages: list[dict]) -> _EchoResponse:
        user = next((m for m in reversed(messages) if m["role"] == "user"), messages[-1])
        content = (
            "[Local LLM — no API key set]\n\n"
            f"Question context: {user['content'][:240]}…\n\n"
            "Based on the data retrieved from the warehouse, here is a structured answer:\n"
            "• Explanation:  trend is increasing over the observation window.\n"
            "• Quantified insight:  ~12% rise versus 30 days ago.\n"
            "• Forecast:  continued pressure over the next 30–60 days.\n"
            "• Recommendation:  open surge capacity and review staffing."
        )
        return _EchoResponse(content)


class _EchoResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class _AnthropicLLM:
    """Thin adapter exposing a LangChain-style `.invoke(messages)` over the
    Anthropic SDK, so the rest of the codebase stays provider-agnostic."""

    def __init__(self, client, model: str) -> None:
        self._client = client
        self._model = model

    def invoke(self, messages: list[dict]) -> _EchoResponse:
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        chat = [m for m in messages if m["role"] in ("user", "assistant")]
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            temperature=0.2,
            system=system or None,
            messages=[{"role": m["role"], "content": m["content"]} for m in chat],
        )
        return _EchoResponse("".join(b.text for b in resp.content if b.type == "text"))


class _OpenAICompatLLM:
    """Adapter over any OpenAI-compatible Chat Completions endpoint (OpenAI,
    OpenRouter, local gateways). Exposes the same `.invoke(messages)` API."""

    def __init__(self, client, model: str) -> None:
        self._client = client
        self._model = model

    def invoke(self, messages: list[dict]) -> _EchoResponse:
        resp = self._client.chat.completions.create(
            model=self._model,
            temperature=0.2,
            messages=[{"role": m["role"], "content": m["content"]} for m in messages],
        )
        return _EchoResponse(resp.choices[0].message.content or "")


@lru_cache(maxsize=1)
def get_llm():
    """Return a LangChain-compatible chat model.

    Returns `_EchoLLM` (no-op) if no API key is configured, so the dashboard
    and recommendation engine always work.
    """
    if settings.llm_provider == "openrouter" and settings.openrouter_api_key:
        try:
            from openai import OpenAI
            log.info("llm.openrouter_init", model=settings.openrouter_model)
            client = OpenAI(
                api_key=settings.openrouter_api_key,
                base_url=settings.openrouter_base_url,
            )
            return _OpenAICompatLLM(client, settings.openrouter_model)
        except Exception as exc:  # noqa: BLE001
            log.warning("llm.openrouter_failed", error=str(exc))

    if settings.llm_provider == "anthropic" and settings.anthropic_api_key:
        try:
            import anthropic
            log.info("llm.anthropic_init", model=settings.anthropic_model)
            return _AnthropicLLM(
                anthropic.Anthropic(api_key=settings.anthropic_api_key),
                settings.anthropic_model,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("llm.anthropic_failed", error=str(exc))

    if settings.llm_provider == "openai" and settings.openai_api_key:
        try:
            from langchain_openai import ChatOpenAI
            log.info("llm.openai_init", model=settings.openai_model)
            return ChatOpenAI(model=settings.openai_model,
                              api_key=settings.openai_api_key,
                              temperature=0.2)
        except Exception as exc:  # noqa: BLE001
            log.warning("llm.openai_failed", error=str(exc))

    if settings.llm_provider == "azure" and settings.azure_openai_api_key:
        try:
            from langchain_openai import AzureChatOpenAI
            log.info("llm.azure_init", deployment=settings.azure_openai_deployment)
            return AzureChatOpenAI(
                deployment_name=settings.azure_openai_deployment,
                openai_api_key=settings.azure_openai_api_key,
                azure_endpoint=settings.azure_openai_endpoint,
                temperature=0.2,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("llm.azure_failed", error=str(exc))

    if settings.llm_provider == "ollama":
        try:
            from langchain_community.chat_models import ChatOllama
            log.info("llm.ollama_init")
            return ChatOllama(model="llama3.1")
        except Exception as exc:  # noqa: BLE001
            log.warning("llm.ollama_failed", error=str(exc))

    log.warning("llm.fallback_echo")
    return _EchoLLM()
