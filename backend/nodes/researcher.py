"""Researcher 节点（初搜）：搜「吃」+「玩」，写入 research_result。"""

from __future__ import annotations

from backend.agents import run_initial_research
from backend.roles import trace_line
from backend.state import AgentState
from backend.trace_compare import format_research_boards
from backend.trace_score import score_legend_trace_lines


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

    backoff_lines = [
        trace_line("Researcher", line, phase="候选")
        for line in research.tool_trace
        if line.startswith(("严苛·", "退避·"))
    ]
    trace = [
        *score_legend_trace_lines(),
        trace_line("Researcher", msg),
        *backoff_lines,
        *format_research_boards(research, profile=profile),
    ]
    return {
        "research_result": research,
        "trace": trace,
    }
