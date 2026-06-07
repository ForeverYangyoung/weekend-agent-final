"""Trace 对比格式化：候选榜 / 方案榜，供 Researcher / Planner 节点写入。"""
from __future__ import annotations

from backend.roles import trace_line
from backend.schemas import GroupProfile, POICandidate, Plan, ResearchResult
from backend.trace_score import format_plan_score_lines, format_poi_score_lines


def _candidate_score(c: POICandidate) -> float:
    if c.breakdown is not None:
        return c.breakdown.total
    return c.score


def format_candidate_board(
    stage_name: str,
    candidates: list[POICandidate],
    *,
    top_n: int = 5,
    role: str = "Researcher",
) -> str:
    if not candidates:
        return trace_line(role, f"对比·{stage_name} 无候选", phase="候选")
    shown = candidates[:top_n]
    rows: list[str] = []
    for i, c in enumerate(shown, start=1):
        dist = c.metadata.get("distance_km", "—")
        rows.append(f"#{i} {c.name}({c.poi_id}) score={_candidate_score(c):.2f} dist={dist}km")
    pick = shown[0]
    return trace_line(
        role,
        f"对比·{stage_name} | 入选={pick.name} | 榜单: " + "；".join(rows),
        phase="候选",
    )


def format_research_boards(
    research: ResearchResult,
    *,
    top_n: int = 5,
    role: str = "Researcher",
    profile: GroupProfile | None = None,
    score_formula_top: int = 3,
) -> list[str]:
    lines: list[str] = []
    for stage in research.stages:
        lines.append(
            format_candidate_board(stage.stage_name, stage.candidates, top_n=top_n, role=role)
        )
        if score_formula_top > 0:
            for i, c in enumerate(stage.candidates[:score_formula_top], start=1):
                lines.extend(
                    format_poi_score_lines(
                        c,
                        stage.stage_name,
                        rank=i,
                        profile=profile,
                        role=role,
                    )
                )
    return lines


def format_plan_board(
    plans: list[Plan],
    *,
    blocked: set[str] | None = None,
    iteration: int = 0,
) -> list[str]:
    lines: list[str] = []
    if blocked:
        lines.append(
            trace_line(
                "Planner",
                "对比·拉黑 POI=" + "、".join(sorted(blocked)),
                phase="候选" if iteration == 0 else "重规划",
            )
        )
    phase = "重规划" if iteration > 0 else "候选"
    primary_plan = plans[0] if plans else None
    for i, plan in enumerate(plans, start=1):
        venues = " → ".join(s.primary.name for s in plan.stages)
        poi_ids = "、".join(s.primary.poi_id for s in plan.stages)
        lines.append(
            trace_line(
                "Planner",
                f"对比·方案#{i} score={plan.score:.2f} | {venues} | poi=[{poi_ids}]",
                phase=phase,
            )
        )
        lines.extend(
            format_plan_score_lines(
                plan,
                rank=i,
                iteration=iteration,
                primary=primary_plan if i > 1 else None,
            )
        )
        if plan.is_compromised and plan.compromise_message:
            lines.append(
                trace_line(
                    "Planner",
                    f"妥协·方案#{i}｜{plan.compromise_message}",
                    phase=phase,
                )
            )
    if len(plans) >= 2:
        p0 = " → ".join(s.primary.name for s in plans[0].stages)
        p1 = " → ".join(s.primary.name for s in plans[1].stages)
        lines.append(
            trace_line(
                "Planner",
                f"对比·Top1 vs Top2 | {p0} || {p1} | Δscore={plans[0].score - plans[1].score:.2f}",
                phase=phase,
            )
        )
    return lines
