"""Planner + Scorer 模块入口。

用法:
    from planner import PlannerEngine, LLMClient, UserProfile
    from planner.state import TimeWindow, Geo, BudgetRange

    profile = UserProfile(
        mode="family", party_size=3,
        time_window=TimeWindow(start="14:00", end="18:00", duration_hours=4),
        geo=Geo(anchor="北京朝阳", radius_km=5),
        budget_per_person=BudgetRange(min=100, max=300),
        hard_filters=["needs_kid_friendly"],
        soft_preferences=["公园"],
    )
    engine = PlannerEngine(llm_client=LLMClient(api_key="..."))
    result = engine.run(profile, "下午带家人出去玩")
    for plan in result.scored_plans:
        print(f"#{plan.rank} {plan.score:.2f} {plan.summary}")

打分功能已独立为 peer package，请直接导入:
    from scoring import ScoringAgent
    from scoring.rules import compute_total_score, rank_plans
"""

from planner.graph import PlannerEngine, build_planner_graph
from planner.llm_wrapper import LLMClient
from planner.state import (
    INSERTABLE_CATALOG,
    Combo,
    InsertableBehavior,
    PlannerState,
    RouteInsertion,
    ScoreBreakdown,
    ScoredPlan,
    UserProfile,
    create_initial_state,
)
from planner.timeline import build_skeleton_from_order, enumerate_candidate_orders
from planner.tool_hub import ToolHub
from planner.trace import TraceLogger, TraceSpan

__all__ = [
    "PlannerEngine",
    "build_planner_graph",
    "ToolHub",
    "TraceLogger",
    "TraceSpan",
    "LLMClient",
    "UserProfile",
    "PlannerState",
    "ScoredPlan",
    "ScoreBreakdown",
    "Combo",
    "InsertableBehavior",
    "RouteInsertion",
    "INSERTABLE_CATALOG",
    "create_initial_state",
    "enumerate_candidate_orders",
    "build_skeleton_from_order",
]
