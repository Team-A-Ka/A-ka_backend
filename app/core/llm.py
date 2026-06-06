from __future__ import annotations

import logging
import time

from openai import OpenAI
from langchain_anthropic import ChatAnthropic
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app.core.config import settings

_openai_sdk: OpenAI | None = None
_embeddings_singleton: Embeddings | None = None


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


def _resolve_embedding_provider() -> str:
    explicit = settings.EMBEDDING_PROVIDER.strip().lower()
    if explicit:
        return explicit
    return settings.LLM_PRIMARY_PROVIDER.strip().lower() or "openai"


def get_embeddings() -> Embeddings:
    """싱글톤 임베딩 클라이언트. provider는 `EMBEDDING_PROVIDER`(빈 값이면 LLM_PRIMARY_PROVIDER) 따름."""
    global _embeddings_singleton
    if _embeddings_singleton is not None:
        return _embeddings_singleton

    provider = _resolve_embedding_provider()
    if provider in {"gemini", "google"}:
        key = settings.GOOGLE_API_KEY.strip() or None
        if not key:
            raise ValueError("GOOGLE_API_KEY is not configured for Gemini embeddings.")
        # gemini-embedding-001은 Matryoshka — output_dimensionality로 차원 선택 가능.
        # DB 컬럼이 vector(1536)이므로 1536으로 고정해 스키마 마이그레이션 회피.
        _embeddings_singleton = GoogleGenerativeAIEmbeddings(
            model=settings.GEMINI_EMBEDDING_MODEL,
            google_api_key=key,
            output_dimensionality=settings.GEMINI_EMBEDDING_DIM,
        )
    elif provider == "openai":
        key = settings.OPENAI_API_KEY.strip() or None
        if not key:
            raise ValueError("OPENAI_API_KEY is not configured for OpenAI embeddings.")
        _embeddings_singleton = OpenAIEmbeddings(
            model=settings.OPENAI_EMBEDDING_MODEL,
            api_key=key,
        )
    else:
        raise ValueError(f"Unsupported embedding provider: {provider}")

    return _embeddings_singleton


_embed_logger = logging.getLogger("aka.embeddings")

# Gemini 임베딩(gemini-embedding-001)은 RPM 제한이 빡빡해 대량 청크를 한 번에
# batchEmbedContents로 보내면 429 RESOURCE_EXHAUSTED가 난다. 그래서:
#   1) sub-batch로 나눠 호출량 스파이크를 줄이고
#   2) 429/503은 지수 백오프로 재시도한다.
# (원래는 재시도가 없어 RPM 스파이크 시 임베딩이 0개로 조용히 실패 → RAG가 비어버림)
_EMBED_SUB_BATCH = 16
_EMBED_MAX_RETRIES = 5
_EMBED_BACKOFF_BASE_S = 8.0
_EMBED_BACKOFF_MAX_S = 120.0
_RATE_LIMIT_MARKERS = ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE")


def _is_rate_limit_error(exc: Exception) -> bool:
    msg = str(exc)
    return any(m in msg for m in _RATE_LIMIT_MARKERS)


def _embed_with_retry(fn, arg):
    """429/503에만 지수 백오프 재시도. 그 외 예외는 즉시 전파."""
    delay = _EMBED_BACKOFF_BASE_S
    for attempt in range(1, _EMBED_MAX_RETRIES + 1):
        try:
            return fn(arg)
        except Exception as exc:
            if not _is_rate_limit_error(exc) or attempt == _EMBED_MAX_RETRIES:
                raise
            _embed_logger.warning(
                "임베딩 레이트 제한(시도 %d/%d) — %.0fs 백오프 후 재시도: %s",
                attempt, _EMBED_MAX_RETRIES, delay, str(exc)[:120],
            )
            time.sleep(delay)
            delay = min(delay * 2, _EMBED_BACKOFF_MAX_S)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """다수 텍스트를 배치 임베딩. UPLOAD 파이프라인용.

    sub-batch로 나눠 호출하고 각 배치를 429/503 백오프 재시도로 보호한다."""
    embeddings = get_embeddings()
    out: list[list[float]] = []
    for i in range(0, len(texts), _EMBED_SUB_BATCH):
        sub = texts[i : i + _EMBED_SUB_BATCH]
        out.extend(_embed_with_retry(embeddings.embed_documents, sub))
    return out


def embed_query(text: str) -> list[float]:
    """단일 텍스트 임베딩. SEARCH·FIND_SIMILAR용. 429/503 백오프 재시도."""
    return _embed_with_retry(get_embeddings().embed_query, text)


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
