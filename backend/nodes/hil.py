"""HIL 节点：应用用户画像覆盖后从 Researcher 重跑。"""
from __future__ import annotations

from backend.agents.profiler import apply_profile_overrides
from backend.hil import clear_planning_artifacts
from backend.roles import trace_line
from backend.state import AgentState


def hil_apply_overrides_node(state: AgentState) -> dict:
    profile = state.get("group_profile")
    overrides = state.get("profile_overrides") or []

    if not profile:
        return {
            **clear_planning_artifacts(),
            "trace": [trace_line("HIL", "跳过：无画像可覆盖", phase="重规划")],
        }

    if not overrides:
        if state.get("plan") is None:
            return {}
        return {
            **clear_planning_artifacts(),
            "trace": [trace_line("HIL", "无覆盖项，按原画像重搜", phase="重规划")],
        }

    before_dietary = set(profile.dietary)
    merged = apply_profile_overrides(profile, overrides)
    preview = [t.label for t in merged.editable_tags[:6]]
    dropped_light = before_dietary - set(merged.dietary)
    trace_lines = [
        trace_line(
            "HIL",
            f"已应用 {len(overrides)} 项覆盖 → 重跑 Researcher；tags={preview}",
            phase="重规划",
        )
    ]
    if dropped_light & {"低卡", "少糖", "轻食"}:
        trace_lines.append(
            trace_line(
                "HIL",
                "显式偏好优先：已移除档案轻食/低卡约束，按您点的菜系重新规划",
                phase="重规划",
            )
        )

    return {
        **clear_planning_artifacts(),
        "group_profile": merged,
        "profile_overrides": [],
        "plan_iteration": 0,
        "trace": trace_lines,
    }
