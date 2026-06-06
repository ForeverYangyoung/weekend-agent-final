"""Planner 节点：薄适配层，业务在 `backend.agents.planner`。

流程：
  1. 调 build_plans → 时间感知的顺序枚举 + 硬过滤 + 选 primary → 写 plan + plan_alternatives
  2. 调 suggest_insertions → 生成顺路活动精准搜索需求 → 写 targeted_search_requests
  3. 降级：初搜无产出 → 回退 stub
"""
from __future__ import annotations

from backend.agents import (
    build_family_stub,
    build_friends_stub,
    build_plans,
    suggest_insertions,
)
from backend.roles import trace_line
from backend.schemas import Plan, ToolStatus
from backend.state import AgentState
from backend.trace_compare import format_plan_board


def planner_node(state: AgentState) -> dict:
    profile = state.get("group_profile")
    iteration = state.get("plan_iteration", 0)
    research = state.get("research_result")

    blocked = {
        (call.args or {}).get("poi_id")
        for call in state.get("failed_calls", []) or []
        if (call.args or {}).get("poi_id")
    }
    for call in state.get("dry_run_calls", []) or []:
        if call.status == ToolStatus.FAILED:
            pid = (call.args or {}).get("poi_id")
            if pid:
                blocked.add(pid)
    blocked.discard(None)

    plans: list[Plan] = []
    source = "stub"
    if profile is not None and research is not None and research.stages:
        plans = build_plans(profile, research, blocked, top_k=2)
        if plans:
            source = "research"

    if not plans:
        stub = (
            build_friends_stub(profile)
            if profile and profile.scene == "friends"
            else build_family_stub()
        )
        plans = [stub]

    primary = plans[0]
    alternatives = plans[1:]

    # 根据主方案生成顺路活动搜索需求
    insertion_requests: list[dict] = []
    if profile is not None and source == "research":
        insertion_requests = suggest_insertions(primary, profile)

    alt_brief = (
        "；备选 " + "; ".join(f"{p.order_label} score={p.score:.2f}" for p in alternatives)
        if alternatives
        else ""
    )
    detail = (
        f"{primary.summary}（来源={source}，{len(primary.stages)} 阶段，"
        f"预计 ¥{primary.total_cost_estimate}，score={primary.score:.2f}{alt_brief}）"
    )
    insertion_detail = (
        f"，顺路活动 {len(insertion_requests)} 项" if insertion_requests else ""
    )
    if iteration > 0:
        line = trace_line("Planner", detail + insertion_detail, phase="重规划", suffix=f"#{iteration}")
    else:
        line = trace_line("Planner", f"首次规划：{detail}{insertion_detail}")

    compare_lines = format_plan_board(plans, blocked=blocked, iteration=iteration)

    return {
        "plan": primary,
        "plan_alternatives": alternatives,
        "plan_iteration": iteration + 1,
        "targeted_search_requests": insertion_requests,
        "trace": [line, *compare_lines],
    }
