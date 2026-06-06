"""Compensator 节点：有下单失败时，取消已成功的订单，并触发重规划。

现在会真调假后台的 `cancel_order`（不再只改内存里的 status 字段）。
"""
from __future__ import annotations

from backend.roles import trace_line
from backend.schemas import ToolStatus
from backend.state import AgentState
from backend.tools import ToolContext, ToolError, invoke


def compensator_node(state: AgentState) -> dict:
    executed = state.get("executed_calls", []) or []
    failed = state.get("failed_calls", []) or []

    rolled_back = 0
    rollback_errors: list[str] = []
    ctx = ToolContext()

    for call in executed:
        if call.status != ToolStatus.OK or not call.result:
            continue
        order_id = call.result.get("order_id")
        if not order_id:
            continue
        try:
            invoke("cancel_order", {"order_id": order_id}, ctx=ctx, stage_name=call.stage_name)
            call.status = ToolStatus.ROLLED_BACK
            rolled_back += 1
        except ToolError as e:
            rollback_errors.append(f"{order_id}:{e.message}")

    msg = (
        f"回滚 {rolled_back} 笔成功订单 ↩，失败原因: "
        + "; ".join(f.error or "?" for f in failed)
    )
    if rollback_errors:
        msg += "；回滚异常: " + ", ".join(rollback_errors)
    trace = trace_line("Executor", msg, phase="回滚")

    return {
        "executed_calls": [],
        "dry_run_calls": [],
        "failed_calls": failed,
        "plan_iteration": state.get("plan_iteration", 0) + 1,
        # Demo 故障开关只触发一次，回滚后清掉，让重规划能演示成功路径
        "force_failure": None,
        "trace": [trace],
    }
