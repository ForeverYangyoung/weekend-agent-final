"""LLM 调用封装：共享客户端 + 小模型 JSON 防猝死解析。"""
from __future__ import annotations

import json
import re
from typing import Any

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


def extract_json_from_mess(text: str) -> str:
    """从模型胡说八道的输出里抠出 JSON 子串。"""
    raw = (text or "").strip()
    if not raw:
        return raw
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw, re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()
    for pattern in (r"\{[\s\S]*\}", r"\[[\s\S]*\]"):
        m = re.search(pattern, raw)
        if m:
            return m.group(0).strip()
    return raw


def parse_llm_json(text: str) -> Any:
    """解析 LLM JSON；失败抛 JSONDecodeError。"""
    return json.loads(extract_json_from_mess(text))


def chat_json(
    client: OpenAI,
    *,
    system: str,
    user: str,
    model: str | None = None,
    temperature: float = 0.1,
) -> Any:
    """优先 response_format=json_object，不支持则普通调用 + 清洗解析。"""
    model = model or get_model_name()
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    use_json_mode = True
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        content = (resp.choices[0].message.content or "").strip()
        return parse_llm_json(content)
    except TypeError:
        use_json_mode = False
    except Exception as e:
        err = str(e).lower()
        if "response_format" in err or "json_object" in err or "unsupported" in err:
            use_json_mode = False
        else:
            raise

    if use_json_mode:
        raise RuntimeError("json_object mode failed unexpectedly")

    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
    )
    content = (resp.choices[0].message.content or "").strip()
    return parse_llm_json(content)
