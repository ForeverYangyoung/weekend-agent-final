"""LangGraph 状态机装配。

主路径：

    START → profiler → researcher → planner → targeted_researcher → critic
                                                   ▲                    │
                                                   │   ┌────┴──────────────────┐
                                                   │ approved              not approved & iter < max
                                                   │   ▼                       │
                                                   │ dry_run                   │
                                                   │   ▼                       │
                                                   │ executor                  │
                                                   │   ├── all ok ──→ notifier → END
                                                   │   └── any fail ──→ compensator
                                                   │                        │
                                                   └────── 重规划 ──────────┘

Researcher 分两阶段：
  1. researcher（初搜）：搜「吃」+「玩」
  2. planner 决定顺序 + 顺路活动 → targeted_researcher（精准搜）搜加餐/奶茶等
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from backend.config import get_settings
from backend.nodes import (
    compensator_node,
    critic_node,
    dry_run_node,
    executor_node,
    hil_apply_overrides_node,
    notifier_node,
    plan_patcher_node,
    planner_node,
    profiler_node,
    researcher_node,
    targeted_researcher_node,
)

_hil_apply = hil_apply_overrides_node
from backend.schemas import ToolStatus
from backend.state import AgentState


# ─────────────────────────── 条件分支函数 ───────────────────────────


def _critic_router(state: AgentState) -> str:
    fb = state.get("critic_feedback")
    iteration = state.get("plan_iteration", 0)
    max_iter = get_settings().max_plan_iterations

    if fb is None or fb.approved:
        return "dry_run"
    if iteration >= max_iter:
        return "dry_run"
    return "planner"


def _executor_router(state: AgentState) -> str:
    failed = state.get("failed_calls", []) or []
    return "compensator" if failed else "notifier"


def _compensator_router(state: AgentState) -> str:
    iteration = state.get("plan_iteration", 0)
    max_iter = get_settings().max_plan_iterations
    return "planner" if iteration < max_iter else "notifier"


def _dry_run_router(state: AgentState) -> str:
    """预检有不可用项 → 回 Planner 换备选 POI（如 4 人烤肉满座）。"""
    dry_calls = state.get("dry_run_calls", []) or []
    failed_dry = any(c.status == ToolStatus.FAILED for c in dry_calls)
    if not failed_dry:
        return "executor"
    iteration = state.get("plan_iteration", 0)
    max_iter = get_settings().max_plan_iterations
    return "planner" if iteration < max_iter else "executor"


# ─────────────────────────── 装配 ───────────────────────────


def _wire_after_researcher(g: StateGraph) -> None:
    """researcher → … → dry_run（不含 profiler）。"""
    g.add_edge("researcher", "planner")
    g.add_edge("planner", "targeted_researcher")
    g.add_edge("targeted_researcher", "critic")
    g.add_conditional_edges(
        "critic",
        _critic_router,
        {"dry_run": "dry_run", "planner": "planner"},
    )


def _wire_planning_edges(g: StateGraph) -> None:
    """profiler → researcher → … → dry_run。"""
    g.add_edge("profiler", "researcher")
    _wire_after_researcher(g)


def build_graph():
    """完整图：CLI demo 一键跑通含下单。"""
    g = StateGraph(AgentState)

    g.add_node("profiler", profiler_node)
    g.add_node("researcher", researcher_node)
    g.add_node("planner", planner_node)
    g.add_node("targeted_researcher", targeted_researcher_node)
    g.add_node("critic", critic_node)
    g.add_node("dry_run", dry_run_node)
    g.add_node("executor", executor_node)
    g.add_node("compensator", compensator_node)
    g.add_node("notifier", notifier_node)

    g.add_edge(START, "profiler")
    _wire_planning_edges(g)
    g.add_conditional_edges(
        "dry_run",
        _dry_run_router,
        {"planner": "planner", "executor": "executor"},
    )
    g.add_conditional_edges(
        "executor",
        _executor_router,
        {"compensator": "compensator", "notifier": "notifier"},
    )
    g.add_conditional_edges(
        "compensator",
        _compensator_router,
        {"planner": "planner", "notifier": "notifier"},
    )
    g.add_edge("notifier", END)

    return g.compile()


def build_dry_run_recovery_graph():
    """预检失败后：从 Planner 重选 POI 再跑 critic → dry_run。"""
    g = StateGraph(AgentState)
    g.add_node("planner", planner_node)
    g.add_node("targeted_researcher", targeted_researcher_node)
    g.add_node("critic", critic_node)
    g.add_node("dry_run", dry_run_node)

    g.add_edge(START, "planner")
    g.add_edge("planner", "targeted_researcher")
    g.add_edge("targeted_researcher", "critic")
    g.add_conditional_edges(
        "critic",
        _critic_router,
        {"dry_run": "dry_run", "planner": "planner"},
    )
    g.add_edge("dry_run", END)
    return g.compile()


def build_planning_graph():
    """HIL 阶段一：规划 + 预检，暂停在 dry_run（待用户确认）。"""
    g = StateGraph(AgentState)
    g.add_node("profiler", profiler_node)
    g.add_node("hil_apply", _hil_apply)
    g.add_node("researcher", researcher_node)
    g.add_node("planner", planner_node)
    g.add_node("targeted_researcher", targeted_researcher_node)
    g.add_node("critic", critic_node)
    g.add_node("dry_run", dry_run_node)

    g.add_edge(START, "profiler")
    g.add_edge("profiler", "hil_apply")
    g.add_edge("hil_apply", "researcher")
    _wire_after_researcher(g)
    g.add_edge("dry_run", END)
    return g.compile()


def build_replan_graph():
    """HIL 重规划：应用覆盖后从 Researcher 重跑至 dry_run。"""
    g = StateGraph(AgentState)
    g.add_node("hil_apply", hil_apply_overrides_node)
    g.add_node("researcher", researcher_node)
    g.add_node("planner", planner_node)
    g.add_node("targeted_researcher", targeted_researcher_node)
    g.add_node("critic", critic_node)
    g.add_node("dry_run", dry_run_node)

    g.add_edge(START, "hil_apply")
    g.add_edge("hil_apply", "researcher")
    _wire_after_researcher(g)
    g.add_edge("dry_run", END)
    return g.compile()


def build_execution_graph():
    """HIL 阶段二：用户确认后执行下单 + 交付。"""
    g = StateGraph(AgentState)
    g.add_node("executor", executor_node)
    g.add_node("compensator", compensator_node)
    g.add_node("notifier", notifier_node)

    g.add_edge(START, "executor")
    g.add_conditional_edges(
        "executor",
        _executor_router,
        {"compensator": "compensator", "notifier": "notifier"},
    )
    g.add_conditional_edges(
        "compensator",
        _compensator_router,
        {"planner": "notifier", "notifier": "notifier"},
    )
    g.add_edge("notifier", END)
    return g.compile()


def build_revise_graph():
    """方案微调：patch 当前方案后重跑 critic + dry_run，不进入执行下单。"""
    g = StateGraph(AgentState)
    g.add_node("plan_patcher", plan_patcher_node)
    g.add_node("critic", critic_node)
    g.add_node("dry_run", dry_run_node)

    g.add_edge(START, "plan_patcher")
    g.add_edge("plan_patcher", "critic")
    g.add_conditional_edges(
        "critic",
        _critic_router,
        {"dry_run": "dry_run", "planner": "dry_run"},
    )
    g.add_edge("dry_run", END)
    return g.compile()


agent_graph = build_graph()
planning_graph = build_planning_graph()
dry_run_recovery_graph = build_dry_run_recovery_graph()
replan_graph = build_replan_graph()
execution_graph = build_execution_graph()
revise_graph = build_revise_graph()
