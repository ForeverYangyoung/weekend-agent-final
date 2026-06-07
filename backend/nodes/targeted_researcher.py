"""Targeted Researcher 节点（精准搜）：根据 Planner 的顺路活动需求精准搜索。"""

from __future__ import annotations

from backend.agents import run_targeted_research
from backend.roles import trace_line
from backend.state import AgentState
from backend.trace_compare import format_research_boards


def targeted_researcher_node(state: AgentState) -> dict:
    profile = state.get("group_profile")
    requests = state.get("targeted_search_requests", []) or []

    if not requests:
        return {
            "targeted_research_result": None,
            "trace": [trace_line("TargetedResearcher", "无顺路活动搜索需求，跳过")],
        }

    research = run_targeted_research(profile, requests)

    total_candidates = sum(len(s.candidates) for s in research.stages)
    selected = "，".join(
        f"{s.stage_name}={s.selected.name}"
        for s in research.stages
        if s.selected is not None
    )
    msg = f"精准搜 {len(research.stages)} 项，候选 {total_candidates}"
    if selected:
        msg += f"｜{selected}"

    board_lines = format_research_boards(
        research, top_n=3, role="TargetedResearcher", profile=profile, score_formula_top=0
    )
    return {
        "targeted_research_result": research,
        "trace": [trace_line("TargetedResearcher", msg), *board_lines],
    }
