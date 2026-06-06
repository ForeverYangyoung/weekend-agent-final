"""LLM 调用封装：所有 Agent 共享同一个客户端实例。"""
from __future__ import annotations

from openai import OpenAI

from backend.config import get_settings

_client: OpenAI | None = None
_client_built: bool = False


def get_llm_client() -> OpenAI | None:
    global _client, _client_built
    settings = get_settings()
    if not settings.use_llm:
        return None
    if not _client_built:
        _client = OpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )
        _client_built = True
    return _client


def get_model_name() -> str:
    return get_settings().openai_model
