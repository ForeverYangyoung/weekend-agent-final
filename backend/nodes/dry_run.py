"""DryRun 节点：并行预检（≤3s）+ 三类故障分类。"""
from __future__ import annotations

from datetime import datetime

from backend.failure_detect import classify_dry_run_failures
from backend.roles import trace_line
from backend.schemas import ToolCall, ToolStatus
from backend.state import AgentState
from backend.timeline_utils import plan_to_timeline
from backend.tools import ToolContext, ToolError, invoke, plan_to_dry_run_calls
from backend.tools.http_client import run_parallel_sync_checks


def _run_read_call(call: ToolCall, ctx: ToolContext) -> ToolCall:
    call.started_at = datetime.utcnow()
    try:
        call.result = invoke(call.tool_name, call.args, ctx=ctx, stage_name=call.stage_name)
        if call.tool_name == "check_activity_availability":
            res = call.result or {}
            if not res.get("available", True) or int(res.get("tickets_left", 1) or 0) <= 0:
                call.status = ToolStatus.FAILED
                call.error = str(res.get("reason") or "活动无票")
                call.result = {**res, "code": res.get("code") or 410}
            else:
                call.status = ToolStatus.OK
        elif call.tool_name == "check_table_availability" and not call.result.get("available"):
            call.status = ToolStatus.FAILED
            reason = str(call.result.get("reason") or "")
            call.error = reason or "桌位不可用"
            if "满" in reason or "已满" in reason:
                call.result = {**call.result, "code": 409}
        elif call.tool_name == "check_addon_stock" and not call.result.get("in_stock"):
            call.status = ToolStatus.FAILED
            call.error = "加餐库存不足"
            call.result = {**(call.result or {}), "code": 410}
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
    pending = plan_to_dry_run_calls(plan, people=people)

    # 并行工具链：多家店同时打听，压到 3s 内
    calls = run_parallel_sync_checks(
        lambda c: _run_read_call(c, ctx),
        pending,
    )

    poi_names = {s.primary.poi_id: s.primary.name for s in plan.stages}
    trace_msgs: list[str] = [
        trace_line(
            "DryRun",
            f"并行预检 n={len(calls)} tools（async gather ≤3s）",
            phase="预检",
        )
    ]

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

    last_code: int | None = None
    for call in calls:
        if call.status == ToolStatus.FAILED and call.result:
            code = call.result.get("code")
            if isinstance(code, int):
                last_code = code

    failure_type = classify_dry_run_failures(calls, plan=plan, profile=profile)
    if failure_type is not None:
        trace_msgs.append(
            trace_line(
                "DryRun",
                f"故障分类 → {failure_type.value}",
                phase="预检",
            )
        )

    timeline = plan_to_timeline(plan, profile)
    return {
        "dry_run_calls": calls,
        "last_exception_code": last_code,
        "current_failure_type": failure_type,
        "timeline": timeline,
        "trace": trace_msgs,
    }
