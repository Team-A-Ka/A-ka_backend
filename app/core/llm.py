from __future__ import annotations

from openai import OpenAI
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from app.core.config import settings

_openai_sdk: OpenAI | None = None


def get_openai_sdk_client() -> OpenAI:
    global _openai_sdk
    if _openai_sdk is None:
        key = settings.OPENAI_API_KEY.strip() or None
        _openai_sdk = OpenAI(api_key=key)
    return _openai_sdk


def openai_chat_model_id() -> str:
    return settings.OPENAI_MODEL


def openai_embedding_model_id() -> str:
    return settings.OPENAI_EMBEDDING_MODEL


def base_message_text(message: BaseMessage) -> str:
    raw = message.content
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, list):
        parts: list[str] = []
        for block in raw:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
            else:
                parts.append(str(block))
        return "".join(parts).strip()
    return str(raw or "").strip()


def _openai_llm() -> BaseChatModel:
    key = settings.OPENAI_API_KEY.strip() or None
    return ChatOpenAI(
        model=settings.OPENAI_MODEL,
        api_key=key,
        temperature=settings.LLM_TEMPERATURE,
        timeout=settings.LLM_TIMEOUT,
        max_retries=1,
    )


def _gemini_llm() -> BaseChatModel:
    key = settings.GOOGLE_API_KEY.strip() or None
    return ChatGoogleGenerativeAI(
        model=settings.GEMINI_MODEL,
        google_api_key=key,
        temperature=settings.LLM_TEMPERATURE,
        timeout=settings.LLM_TIMEOUT,
        max_retries=1,
    )


def _anthropic_llm() -> BaseChatModel:
    key = settings.ANTHROPIC_API_KEY.strip() or None
    return ChatAnthropic(
        model=settings.ANTHROPIC_MODEL,
        api_key=key,
        temperature=settings.LLM_TEMPERATURE,
        timeout=settings.LLM_TIMEOUT,
        max_retries=1,
    )


def _build_llm(provider: str) -> BaseChatModel:
    provider = provider.lower().strip()

    if provider == "openai":
        return _openai_llm()
    if provider in {"gemini", "google"}:
        return _gemini_llm()
    if provider in {"anthropic", "claude"}:
        return _anthropic_llm()

    raise ValueError(f"Unsupported LLM provider: {provider}")


def _provider_configured(provider: str) -> bool:
    p = provider.lower().strip()
    if p == "openai":
        return bool(settings.OPENAI_API_KEY.strip())
    if p in {"gemini", "google"}:
        return bool(settings.GOOGLE_API_KEY.strip())
    if p in {"anthropic", "claude"}:
        return bool(settings.ANTHROPIC_API_KEY.strip())
    return False


def get_chat_model_primary() -> BaseChatModel:
    """폴백 없이 `LLM_PRIMARY_PROVIDER` 한 종류만 쓰는 채팅 모델.

    `with_structured_output` 등 폴백 체인과 섞이기 어려운 경로용.
    """
    name = settings.LLM_PRIMARY_PROVIDER.strip()
    if not _provider_configured(name):
        raise ValueError(
            f"LLM provider '{name}' is not configured (check API key in settings)."
        )
    return _build_llm(name)


def get_llm() -> BaseChatModel:
    primary_name = settings.LLM_PRIMARY_PROVIDER.strip()
    if not _provider_configured(primary_name):
        raise ValueError(
            f"LLM provider '{primary_name}' is not configured (check API key in settings)."
        )
    primary = _build_llm(primary_name)
    fallbacks: list[BaseChatModel] = []
    for item in settings.LLM_FALLBACKS.split(","):
        p = item.strip()
        if not p or p.lower() == primary_name.lower():
            continue
        if _provider_configured(p):
            fallbacks.append(_build_llm(p))

    if not fallbacks:
        return primary

    return primary.with_fallbacks(fallbacks)
