"""Researcher 节点（初搜）：搜「吃」+「玩」，写入 research_result。"""

from __future__ import annotations

from backend.agents import run_initial_research
from backend.roles import trace_line
from backend.state import AgentState
from backend.trace_compare import format_research_boards


def researcher_node(state: AgentState) -> dict:
    profile = state.get("group_profile")
    research = run_initial_research(profile)

    total_candidates = sum(len(s.candidates) for s in research.stages)
    selected = "，".join(
        f"{s.stage_name}={s.selected.name}"
        for s in research.stages
        if s.selected is not None
    )
    msg = f"初搜 阶段 {len(research.stages)}，候选 {total_candidates} 项"
    if selected:
        msg += f"｜{selected}"

    trace = [trace_line("Researcher", msg), *format_research_boards(research)]
    return {
        "research_result": research,
        "trace": trace,
    }
