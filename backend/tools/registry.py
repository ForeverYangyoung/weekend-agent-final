"""Tool 注册表：节点只认 tool_name，具体执行走 HTTP 打到 Mock 美团 (`mock_meituan` 包)。

升级前：直接调 `tools/mock_client.MockBackend` 方法（同进程函数）。
升级后：本模块把 tool_name 翻译成 POST /availability/* 或 /order/*，再把 HTTP
返回还原成原 dict，对节点完全透明。

force_failure 注入：保持原语义——演示开关 `state["force_failure"] = "吃"` 会让
该阶段的写类调用在请求体里带 `force_fail=table_full`，mock 路由直接返 409。
"""
from __future__ import annotations

from dataclasses import dataclass

from backend.tools.errors import ToolError
from backend.tools.http_client import post_json

# 演示开关：阶段名 → 注入到请求里的失败类型
_STAGE_WRITE_FAIL: dict[str, str] = {
    "玩": "sold_out",
    "吃": "table_full",
    "加餐": "out_of_stock",
}

_WRITE_TOOLS = frozenset({"buy_ticket", "book_table", "order_addon"})

# tool_name → HTTP path
_TOOL_PATHS: dict[str, str] = {
    "check_activity_availability": "/availability/activity",
    "check_table_availability": "/availability/table",
    "check_addon_stock": "/availability/addon",
    "buy_ticket": "/order/buy_ticket",
    "book_table": "/order/book_table",
    "order_addon": "/order/order_addon",
    "cancel_order": "/order/cancel",
}


@dataclass
class ToolContext:
    """一次 Tool 调用的上下文（从 Agent state 传进来）。"""

    force_failure_stage: str | None = None  # 例如 "吃" → 该阶段写操作失败
    idempotency_key: str | None = None
    force_fail: str | None = None  # 显式指定：table_full / sold_out / out_of_stock


def _resolve_force_fail(tool_name: str, ctx: ToolContext, stage_name: str) -> str | None:
    if ctx.force_fail:
        return ctx.force_fail
    # 演示开关只作用于「下单」，不影响 DryRun 的「打听」
    if tool_name in _WRITE_TOOLS and ctx.force_failure_stage == stage_name:
        return _STAGE_WRITE_FAIL.get(stage_name)
    return None


def _build_payload(tool_name: str, args: dict, ctx: ToolContext, stage_name: str) -> dict:
    """把 dict 形态的 args 适配成对应路由的 payload。"""
    ff = _resolve_force_fail(tool_name, ctx, stage_name)

    if tool_name == "check_activity_availability":
        return {
            "poi_id": args["poi_id"],
            "start": args.get("start", ""),
            "force_fail": ff,
        }
    if tool_name == "check_table_availability":
        return {
            "poi_id": args["poi_id"],
            "time": args.get("time", ""),
            "people": int(args.get("people", args.get("ppl", 4))),
            "force_fail": ff,
        }
    if tool_name == "check_addon_stock":
        return {"poi_id": args["poi_id"], "force_fail": ff}

    # 写类：必须带 idempotency_key
    key = ctx.idempotency_key or args.get("idempotency_key", "idem_default")

    if tool_name == "buy_ticket":
        return {
            "activity_id": args.get("activity_id", args.get("poi_id", "")),
            "count": int(args.get("count", args.get("people", 2))),
            "idempotency_key": key,
            "force_fail": ff,
        }
    if tool_name == "book_table":
        return {
            "poi_id": args["poi_id"],
            "time": args.get("time", ""),
            "people": int(args.get("people", args.get("ppl", 4))),
            "idempotency_key": key,
            "force_fail": ff,
        }
    if tool_name == "order_addon":
        deliver_to = args.get("delivery_address") or args.get("deliver_to_poi_id")
        payload = {
            "poi_id": args["poi_id"],
            "idempotency_key": key,
            "items": args.get("items"),
            "force_fail": ff,
        }
        if deliver_to:
            payload["delivery_address"] = deliver_to
            payload["deliver_to_poi_id"] = deliver_to
        return payload
    if tool_name == "cancel_order":
        return {"order_id": args["order_id"]}

    raise ToolError(400, f"未知 Tool: {tool_name}")


def invoke(tool_name: str, args: dict, *, ctx: ToolContext, stage_name: str = "") -> dict:
    """调用 Mock 美团（走 HTTP）。成功返回 dict；失败抛 ToolError。"""
    path = _TOOL_PATHS.get(tool_name)
    if not path:
        raise ToolError(400, f"未知 Tool: {tool_name}")
    payload = _build_payload(tool_name, args, ctx, stage_name)
    return post_json(path, payload)
