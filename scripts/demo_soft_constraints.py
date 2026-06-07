"""演示软约束打分：距离 Sigmoid、预算指数衰减、Global Cohesion。

用法:
    python scripts/demo_soft_constraints.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.agents.planner import _plan_score_math
from backend.agents.researcher import (
    _rank_and_filter,
    _score_budget_math,
    _score_distance_math,
)
from backend.schemas import (
    GroupProfile,
    POICandidate,
    Plan,
    PlanStage,
    ScoreBreakdown,
)


def demo_distance_sigmoid() -> None:
    profile = GroupProfile(distance_limit_km=5.0)
    print("=== 1. 距离 Sigmoid（limit=5km）===")
    print("  旧逻辑: 超过 5km 直接过滤，等于 0")
    print("  新逻辑: 平滑衰减，仍保留在候选里")
    for d in [3, 5, 6, 8, 10, 15]:
        c = POICandidate(
            poi_id="x",
            name="test",
            category="餐厅",
            score=0.9,
            metadata={"distance_km": d},
        )
        s = _score_distance_math(c, profile)
        print(f"  distance={d:2}km -> dist_score={s:.3f}")


def demo_budget_exponential() -> None:
    profile = GroupProfile(budget_per_person=100)
    print("\n=== 2. 预算指数衰减（budget=100）===")
    print("  旧逻辑: 线性扣分 1-over_ratio，超 2 倍直接变 0")
    print("  新逻辑: exp(-5*over_ratio)，轻微超支仍可接受")
    for price in [80, 100, 120, 150, 200]:
        c = POICandidate(
            poi_id="x",
            name="test",
            category="餐厅",
            score=0.9,
            metadata={"avg_price": price},
        )
        s = _score_budget_math(c, profile, "吃")
        print(f"  avg_price={price:3} -> budget_score={s:.3f}")


def demo_global_cohesion() -> None:
    print("\n=== 3. Global Cohesion（玩/吃距离差）===")
    print("  公式: base_avg * (1 - 0.4 * (1 - exp(-0.5 * max(0, gap-3))))")

    def make_plan(d_play: float, d_eat: float, base: float = 0.8) -> Plan:
        bd = ScoreBreakdown(
            total=base,
            distance=0.5,
            budget=0.7,
            preference=0.8,
            history=0.5,
            rating=0.9,
        )
        play = POICandidate(
            poi_id="p1",
            name="玩",
            category="活动",
            score=0.9,
            metadata={"distance_km": d_play},
            breakdown=bd,
        )
        eat = POICandidate(
            poi_id="e1",
            name="吃",
            category="餐厅",
            score=0.9,
            metadata={"distance_km": d_eat},
            breakdown=bd,
        )
        return Plan(
            stages=[
                PlanStage(
                    name="玩",
                    start_time="14:00",
                    end_time="16:00",
                    primary=play,
                ),
                PlanStage(
                    name="吃",
                    start_time="16:30",
                    end_time="18:30",
                    primary=eat,
                ),
            ]
        )

    cases = [
        ("同城商圈", 1, 2),
        ("临界 3km", 2, 5),
        ("跨区 7km", 1, 8),
        ("跨城 10km", 2, 12),
    ]
    for label, dp, de in cases:
        gap = abs(dp - de)
        sc = _plan_score_math(make_plan(dp, de))
        print(f"  {label:10} gap={gap:.0f}km -> plan_score={sc:.3f}")


def demo_no_hard_distance_filter() -> None:
    profile = GroupProfile(scene="friends", distance_limit_km=5.0)
    print("\n=== 4. 超距 POI 不再被硬过滤 ===")
    cands = [
        POICandidate(
            poi_id="near",
            name="近店",
            category="餐厅",
            score=0.85,
            metadata={"distance_km": 2},
        ),
        POICandidate(
            poi_id="edge",
            name="边界店",
            category="餐厅",
            score=0.90,
            metadata={"distance_km": 5},
        ),
        POICandidate(
            poi_id="far",
            name="远店",
            category="餐厅",
            score=0.95,
            metadata={"distance_km": 12},
        ),
    ]
    ranked = _rank_and_filter(cands, profile, "吃")
    print(f"  输入 {len(cands)} 家，输出 {len(ranked)} 家")
    for c in ranked:
        bd = c.breakdown
        assert bd is not None
        d = c.metadata["distance_km"]
        print(
            f"  {c.name:6} dist={d}km  "
            f"dist_score={bd.distance:.3f}  total={bd.total:.3f}"
        )


def main() -> None:
    demo_distance_sigmoid()
    demo_budget_exponential()
    demo_global_cohesion()
    demo_no_hard_distance_filter()
    print("\n完成。答辩时可强调：")
    print("  - Researcher 五维 breakdown.distance / budget 是连续曲线")
    print("  - Planner plan.score 含 Global Cohesion，跨区组合会降分但不消失")


if __name__ == "__main__":
    main()
