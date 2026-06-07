"""Trace 算式打分：POI 五维拆解 + 方案 Global Cohesion，供 trace_compare 写入。"""
from __future__ import annotations

import math

from backend.agents.researcher import _WEIGHTS
from backend.roles import trace_line
from backend.schemas import GroupProfile, POICandidate, Plan

_MAX_PLAY_EAT_DIST_KM = 3.0
_COHESION_LAMBDA = 0.4
_COHESION_ALPHA = 0.5

# 图例各行前缀，前端可识别并置顶展示（与 trace 流无关的静态图例亦用同一文案）
SCORE_LEGEND_LINES: tuple[str, ...] = (
    "【POI 五维分】Researcher 对每家候选店打分，加权求和 = 单店总分",
    "  偏好 35% — 标签/菜系/场景是否匹配用户画像（0~1，越高越贴偏好）",
    "  历史 20% — 用户历史偏好权重命中（0~1，无历史时默认 0.5）",
    "  评分 20% — Mock 平台 POI 评分（0~1）",
    "  距离 15% — Sigmoid 平滑：1/(1+e^(2×(实际km-上限km)))，越近越高，超距不砍店只降分",
    "  预算 10% — 仅「吃」阶段：人均≤预算→1；超出→e^(-5×超出比例)，轻微超支可容忍",
    "【方案全局分】Planner 对「玩+吃」组合打分",
    "  基础均分 = (玩 POI 总分 + 吃 POI 总分) ÷ 2",
    "  顺路惩罚 = 1 - e^(-0.5×max(0, |d玩-d吃|-3km))；差≤3km 时惩罚=0",
    "  方案分 = 基础均分 × (1 - 0.4 × 顺路惩罚)",
    "【内存退避】一次拉池20家，严苛不足时在内存放宽距离+3km、预算+30% 重排",
    "【妥协保底】硬过滤无匹配时取综合分最高，Plan.is_compromised 触发前端黄条",
)


def score_legend_trace_lines(*, role: str = "Researcher") -> list[str]:
    """打分图例，规划开始后写入 trace 一次即可。"""
    return [trace_line(role, f"算式·图例｜{line}", phase="候选") for line in SCORE_LEGEND_LINES]


def _short_name(name: str) -> str:
    return name.split("（")[0].strip()


def _budget_note(c: POICandidate, profile: GroupProfile | None, stage_name: str) -> str:
    avg = int(c.metadata.get("avg_price", 0) or 0)
    budget = profile.budget_per_person if profile else None
    if stage_name != "吃" or not budget or avg <= 0:
        return ""
    if avg <= budget:
        return f"¥{avg}/预算¥{budget}"
    return f"¥{avg}/预算¥{budget}⚠超支"


def _distance_note(c: POICandidate, profile: GroupProfile | None) -> str:
    d = float(c.metadata.get("distance_km", 0) or 0)
    limit = max(profile.distance_limit_km, 1.0) if profile else 10.0
    return f"{d:g}km/限{limit:g}km"


def format_poi_score_lines(
    c: POICandidate,
    stage_name: str,
    *,
    rank: int,
    profile: GroupProfile | None = None,
    role: str = "Researcher",
) -> list[str]:
    """单店算式卡片（2 行）。"""
    bd = c.breakdown
    if bd is None:
        return []

    w = _WEIGHTS
    name = _short_name(c.name)
    header = f"{stage_name}·#{rank} {name}"

    formula = (
        f"算式·POI｜{header}｜总分 {bd.total:.2f} = "
        f"{w['preference']:.2f}×{bd.preference:.2f} + "
        f"{w['history']:.2f}×{bd.history:.2f} + "
        f"{w['rating']:.2f}×{bd.rating:.2f} + "
        f"{w['distance']:.2f}×{bd.distance:.2f} + "
        f"{w['budget']:.2f}×{bd.budget:.2f}"
    )
    budget_note = _budget_note(c, profile, stage_name)
    dist_note = _distance_note(c, profile)
    detail_parts = [
        f"偏好 {bd.preference:.2f}",
        f"历史 {bd.history:.2f}",
        f"评分 {bd.rating:.2f}",
        f"距离 {bd.distance:.2f}({dist_note})",
        f"预算 {bd.budget:.2f}" + (f"({budget_note})" if budget_note else ""),
    ]
    detail = f"算式·POI｜{header}｜" + " | ".join(detail_parts)

    return [
        trace_line(role, formula, phase="候选"),
        trace_line(role, detail, phase="候选"),
    ]


def _plan_cohesion_parts(plan: Plan) -> tuple[float, float, float, float, float]:
    """返回 base_avg, d_play, d_eat, gap, penalty。"""
    stages = plan.stages
    if not stages:
        return 0.0, 0.0, 0.0, 0.0, 0.0

    base_avg = sum(
        s.primary.breakdown.total if s.primary.breakdown else 0.5 for s in stages
    ) / len(stages)

    play_stage = next((s for s in stages if s.name == "玩"), None)
    eat_stage = next((s for s in stages if s.name == "吃"), None)
    d_play = float(play_stage.primary.metadata.get("distance_km", 0) or 0) if play_stage else 0.0
    d_eat = float(eat_stage.primary.metadata.get("distance_km", 0) or 0) if eat_stage else 0.0
    gap = abs(d_play - d_eat)
    penalty = 0.0
    if gap > _MAX_PLAY_EAT_DIST_KM:
        penalty = 1.0 - math.exp(-_COHESION_ALPHA * (gap - _MAX_PLAY_EAT_DIST_KM))
    return base_avg, d_play, d_eat, gap, penalty


def format_plan_score_lines(
    plan: Plan,
    *,
    rank: int,
    iteration: int = 0,
    primary: Plan | None = None,
) -> list[str]:
    """单套方案算式（1~2 行）。"""
    play_stage = next((s for s in plan.stages if s.name == "玩"), None)
    eat_stage = next((s for s in plan.stages if s.name == "吃"), None)
    play_bd = play_stage.primary.breakdown if play_stage and play_stage.primary.breakdown else None
    eat_bd = eat_stage.primary.breakdown if eat_stage and eat_stage.primary.breakdown else None
    play_total = play_bd.total if play_bd else 0.5
    eat_total = eat_bd.total if eat_bd else 0.5

    base_avg, d_play, d_eat, gap, penalty = _plan_cohesion_parts(plan)
    cohesion_mul = 1.0 - penalty * _COHESION_LAMBDA
    phase = "重规划" if iteration > 0 else "候选"

    venues = " → ".join(_short_name(s.primary.name) for s in plan.stages)
    if penalty <= 0:
        cohesion_desc = f"差{gap:g}km≤{_MAX_PLAY_EAT_DIST_KM:g}km，顺路×{cohesion_mul:.2f}"
    else:
        cohesion_desc = (
            f"玩{d_play:g}km 吃{d_eat:g}km 差{gap:g}km，"
            f"惩罚={penalty:.2f}，顺路×{cohesion_mul:.2f}"
        )

    formula = (
        f"算式·方案｜#{rank} 分 {plan.score:.2f} = "
        f"({play_total:.2f}+{eat_total:.2f})/2 × {cohesion_mul:.2f}｜{cohesion_desc}"
    )
    lines = [trace_line("Planner", formula, phase=phase)]

    if primary is not None and rank > 1 and primary.score > plan.score:
        delta = primary.score - plan.score
        p_eat_bd = next(
            (
                s.primary.breakdown.total
                for s in primary.stages
                if s.name == "吃" and s.primary.breakdown
            ),
            None,
        )
        reason = f"算式·方案｜#{rank} 比推荐低 {delta:.2f}"
        if p_eat_bd is not None and abs(eat_total - p_eat_bd) > 0.01:
            reason += f"（餐厅 POI 分差 {eat_total - p_eat_bd:+.2f}）"
        reason += f"｜{venues}"
        lines.append(trace_line("Planner", reason, phase=phase))
    else:
        lines.append(trace_line("Planner", f"算式·方案｜#{rank}｜{venues}", phase=phase))

    return lines
