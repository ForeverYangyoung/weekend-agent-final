"""DryRun 节点：根据 Plan「打听」一圈（查票、查桌、查库存），不下单。

现在通过 `weekend_agent.tools` 假后台真实走查询逻辑（仍是内存 Mock，不是真美团）。
"""
from __future__ import annotations

from datetime import datetime

from backend.roles import trace_line
from backend.schemas import ToolCall, ToolStatus
from backend.state import AgentState
from backend.tools import ToolContext, ToolError, invoke, plan_to_dry_run_calls


def _run_read_call(call: ToolCall, ctx: ToolContext) -> ToolCall:
    call.started_at = datetime.utcnow()
    try:
        call.result = invoke(call.tool_name, call.args, ctx=ctx, stage_name=call.stage_name)
        # 读类：available / in_stock 为 false 也算「不能继续下单」
        if call.tool_name == "check_table_availability" and not call.result.get("available"):
            call.status = ToolStatus.FAILED
            call.error = "桌位不可用"
        elif call.tool_name == "check_addon_stock" and not call.result.get("in_stock"):
            call.status = ToolStatus.FAILED
            call.error = "加餐库存不足"
        else:
            call.status = ToolStatus.OK
    except ToolError as e:
        call.status = ToolStatus.FAILED
        call.error = e.message
        call.result = {"code": e.code, **e.details}
    call.finished_at = datetime.utcnow()
    return call


def dry_run_node(state: AgentState) -> dict:
    plan = state.get("plan")
    if not plan:
        return {
            "dry_run_calls": [],
            "trace": [trace_line("Executor", "跳过：无 plan", phase="预检")],
        }

    profile = state.get("group_profile")
    people = profile.people_count if profile else 4

    ctx = ToolContext(force_failure_stage=state.get("force_failure"))
    calls = [_run_read_call(c, ctx) for c in plan_to_dry_run_calls(plan, people=people)]

    poi_names = {s.primary.poi_id: s.primary.name for s in plan.stages}
    trace_msgs: list[str] = []

    for call in calls:
        pid = (call.args or {}).get("poi_id", "?")
        pname = poi_names.get(pid, pid)
        if call.status == ToolStatus.FAILED:
            reason = call.error or "未知原因"
            waiting = None
            if call.result:
                reason = str(call.result.get("reason") or reason)
                waiting = call.result.get("waiting_minutes")
            people_n = (call.args or {}).get("people", people)
            rule_hint = ""
            if pid == "poi_rest_201" and int(people_n or 0) >= 4:
                rule_hint = " | mock_trap=朋友4人+poi_rest_201→满座"
            wait_hint = f" | wait={waiting}min" if waiting is not None else ""
            trace_msgs.append(
                trace_line(
                    "DryRun",
                    f"FAIL 店={pname}({pid}) people={people_n} | tool={call.tool_name}"
                    f" | reason={reason}{wait_hint}{rule_hint}",
                    phase="预检",
                )
            )
        else:
            trace_msgs.append(
                trace_line(
                    "DryRun",
                    f"OK  店={pname}({pid}) | tool={call.tool_name} | available/in_stock=true",
                    phase="预检",
                )
            )

    ok = sum(1 for c in calls if c.status == ToolStatus.OK)
    fail = len(calls) - ok
    summary = f"汇总 checked={len(calls)} ok={ok} fail={fail}"
    summary += " ✓" if fail == 0 else " ✗"
    trace_msgs.append(trace_line("DryRun", summary, phase="预检"))

    return {"dry_run_calls": calls, "trace": trace_msgs}
