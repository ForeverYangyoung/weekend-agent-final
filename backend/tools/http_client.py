"""HTTP 客户端：Agent ↔ Mock 美团 之间的唯一通道。

设计要点：
  - 对外暴露的所有函数都是 **同步** 的（节点都是 sync 代码），内部用
    `asyncio.run(...) + httpx.AsyncClient`。
  - 通过环境变量 `MOCK_MEITUAN_BASE_URL` 切换两种部署：
      * 未设 / `internal://` → 内联：`ASGITransport(app=mock_app)`，零端口
      * `http://host:port`   → 真 TCP，便于评委 curl 验证 / 切真 API
  - 写类调用失败时（HTTP 4xx/5xx）转回 `ToolError`，让上层节点照原路抛。

为什么不在 invoke 里裸调 `mock_app`？
  这样 Agent 完全不知道有内联这回事，行为=「我发出真 HTTP」，故事更顺。
"""
from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from typing import Any

import httpx

from backend.tools.errors import ToolError

_INTERNAL_BASE = "http://mock-meituan.internal"  # ASGI 模式下的占位 host


def _resolved_base_url() -> str:
    """优先环境变量，缺省走内联 ASGI。"""
    raw = os.environ.get("MOCK_MEITUAN_BASE_URL", "").strip()
    if not raw or raw.lower() in {"internal", "internal://", "memory", "asgi"}:
        return _INTERNAL_BASE
    return raw.rstrip("/")


def current_mode() -> tuple[str, str]:
    """返回 (mode, base_url)；mode ∈ {"internal", "tcp"}，给 demo / health 展示。"""
    raw = os.environ.get("MOCK_MEITUAN_BASE_URL", "").strip()
    if not raw or raw.lower() in {"internal", "internal://", "memory", "asgi"}:
        return "internal", _INTERNAL_BASE
    return "tcp", raw.rstrip("/")


def _build_transport() -> httpx.AsyncBaseTransport | None:
    """internal 模式才需要 ASGITransport；tcp 模式返回 None，让 httpx 走默认。"""
    mode, _ = current_mode()
    if mode != "internal":
        return None
    # 延迟 import 避免 mock_meituan / tools 循环导入
    from backend.mock_meituan.app import mock_app

    return httpx.ASGITransport(app=mock_app)


def _trust_env() -> bool:
    """默认 False：Windows 注册表里的系统代理会把 127.0.0.1 也劫持成 502，必须显式关掉。

    如果以后要切真公网 API，可以 `MOCK_MEITUAN_TRUST_ENV=1` 让 httpx 读系统代理。
    """
    return os.environ.get("MOCK_MEITUAN_TRUST_ENV", "0").strip() not in {"", "0", "false", "False"}


async def _arequest(method: str, path: str, **kwargs: Any) -> httpx.Response:
    transport = _build_transport()
    base_url = _resolved_base_url()
    async with httpx.AsyncClient(
        transport=transport,
        base_url=base_url,
        timeout=httpx.Timeout(10.0, connect=3.0),
        trust_env=_trust_env(),
    ) as client:
        return await client.request(method, path, **kwargs)


def _request(method: str, path: str, **kwargs: Any) -> httpx.Response:
    """同步包一层 asyncio.run，给所有同步节点用。"""
    try:
        return asyncio.run(_arequest(method, path, **kwargs))
    except httpx.HTTPError as e:
        raise ToolError(599, f"Mock 美团网络异常: {e}") from e


def _ensure_ok(resp: httpx.Response) -> dict[str, Any]:
    if resp.status_code >= 400:
        body: Any
        try:
            body = resp.json()
        except Exception:  # noqa: BLE001
            body = {"message": resp.text}
        message = body.get("detail", {}).get("message") if isinstance(body, dict) else None
        details = body.get("detail", {}).get("details") if isinstance(body, dict) else None
        raise ToolError(
            resp.status_code,
            message or f"Mock 美团返回 {resp.status_code}",
            details=details or {},
        )
    try:
        return resp.json()
    except Exception as e:  # noqa: BLE001
        raise ToolError(599, f"Mock 美团响应非 JSON: {resp.text[:120]}") from e


# ─────────────────────────── 高层 API（供 Researcher / registry 用） ───────────────────────────


def search_poi(*, scene: str, stage: str, limit: int = 10) -> list[dict[str, Any]]:
    """GET /poi/search → 返回候选 dict 列表（dict 字段对齐 POICandidate）。"""
    resp = _request("GET", "/poi/search", params={"scene": scene, "stage": stage, "limit": limit})
    body = _ensure_ok(resp)
    return list(body.get("items", []))


def post_json(path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """POST /xxx → 解析 JSON；4xx/5xx 转成 ToolError。"""
    resp = _request("POST", path, json=dict(payload))
    return _ensure_ok(resp)


# ─────────────────────────── 异步并行预检（≤3s 死线）───────────────────────────


async def _check_single_poi_mock(poi_id: str) -> dict[str, Any]:
    """单店并行探针：桌位 + 票量 + 库存同时打听（I/O 并发）。"""
    await asyncio.sleep(0.05)
    table_task = _arequest(
        "POST",
        "/availability/table",
        json={"poi_id": poi_id, "time": "18:00", "people": 4},
    )
    activity_task = _arequest(
        "POST",
        "/availability/activity",
        json={"poi_id": poi_id, "start": "14:00"},
    )
    addon_task = _arequest(
        "POST",
        "/availability/addon",
        json={"poi_id": poi_id},
    )
    table_r, activity_r, addon_r = await asyncio.gather(table_task, activity_task, addon_task)
    table = _ensure_ok(table_r) if table_r.status_code < 400 else {}
    activity = _ensure_ok(activity_r) if activity_r.status_code < 400 else {}
    addon = _ensure_ok(addon_r) if addon_r.status_code < 400 else {}
    return {
        "poi_id": poi_id,
        "seat_available": bool(table.get("available", False)),
        "ticket_count": int(activity.get("tickets_left", 0) or 0),
        "addon_in_stock": bool(addon.get("in_stock", True)),
    }


async def mock_parallel_precheck(poi_ids: list[str]) -> list[dict[str, Any]]:
    """并行工具链：多家店同时预检，总耗时压到 3s 内。"""
    tasks = [_check_single_poi_mock(pid) for pid in poi_ids]
    return await asyncio.wait_for(asyncio.gather(*tasks), timeout=3.0)


def parallel_precheck_poi_ids(poi_ids: list[str]) -> list[dict[str, Any]]:
    """同步节点入口：asyncio.run 包装并行预检。"""
    if not poi_ids:
        return []
    try:
        return asyncio.run(mock_parallel_precheck(poi_ids))
    except TimeoutError as e:
        raise ToolError(599, "并行预检超时（>3s）", details={"poi_ids": poi_ids}) from e


async def parallel_run_sync_checks(check_fn, items: list) -> list:
    """通用：对同步检查函数做 asyncio.to_thread 并行。"""
    tasks = [asyncio.to_thread(check_fn, item) for item in items]
    return await asyncio.wait_for(asyncio.gather(*tasks), timeout=3.0)


def run_parallel_sync_checks(check_fn, items: list) -> list:
    if not items:
        return []
    try:
        return asyncio.run(parallel_run_sync_checks(check_fn, items))
    except TimeoutError as e:
        raise ToolError(599, "并行工具链超时（>3s）") from e
