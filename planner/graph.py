"""Planner 编排队 — 将所有模块串成完整工作流。

流程：
  enumerate_candidate_orders → LLM 选最优顺序 → build_skeleton_from_order
  → 检索（ToolHub）→ 过滤 → 组合 → 规则打分
  → LLM 地理凝聚力 → LLM pairwise 校准
  → 顺路插入 → Top-2 摘要

依赖 ToolHub 统一管理：重试 / 缓存 / 追踪 / 降级。
"""

from concurrent.futures import ThreadPoolExecutor, as_completed

from typing import TYPE_CHECKING

from planner.composer import generate_combinations
from planner.filters import apply_stage_filters
from planner.llm_wrapper import (
    LLMClient,
    generate_summary,
    judge_route_insertions,
    rank_timeline_orders,
)
from planner.state import (
    INSERTABLE_CATALOG,
    PlannerState,
    TimelineSkeleton,
    UserProfile,
    create_initial_state,
)
from planner.timeline import build_skeleton_from_order, enumerate_candidate_orders
from planner.tool_hub import ToolHub
from planner.trace import TraceLogger

# ── 循环上限（01 文档 NFR + 02 文档 §4.4） ───────────

MAX_TOOL_ROUNDS = 6
MAX_COMBOS = 15
MAX_CANDIDATES_PER_STAGE = 5


class PlannerEngine:
    """同步编排引擎，所有 I/O 经 ToolHub 统一管理。

    Scoring 由独立的 ScoringAgent 负责，Engine 只做编排。
    """

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        tool_hub: ToolHub | None = None,
        scorer: "ScoringAgent | None" = None,
        enable_calibration: bool = True,
        enable_geo_cohesion: bool = True,
    ):
        self.llm = llm_client or LLMClient()
        self.hub = tool_hub or ToolHub(llm=self.llm)
        if scorer is None:
            from scoring import ScoringAgent as _SA
            self.scorer = _SA(
                llm=self.llm,
                enable_calibration=enable_calibration,
                enable_geo_cohesion=enable_geo_cohesion,
            )
        else:
            self.scorer = scorer

    def run(self, profile: UserProfile, raw_query: str = "") -> PlannerState:
        state = create_initial_state(raw_query, profile)
        tracer = self.hub.tracer

        # ── Step 0: 枚举候选顺序 → LLM 选最优 ──
        candidates = enumerate_candidate_orders(profile)

        if self.llm.api_key:
            chosen = rank_timeline_orders(candidates, profile, self.llm)
            tracer.log("rank_timeline_orders", "success", {
                "chosen": chosen["label"],
                "reason": chosen["reason"],
                "confidence": chosen["confidence"],
                "candidates_count": len(candidates),
            })
        else:
            chosen = {
                "best_order": candidates[0]["order"],
                "label": candidates[0]["label"],
                "reason": "无 LLM，默认第一个候选",
                "confidence": 0.3,
            }

        # ── Step 0.5: 建骨架 ──
        skeleton = build_skeleton_from_order(chosen["best_order"], profile)
        state.skeleton = skeleton

        # ── Step 1: 并行检索 + 过滤 ──
        candidates = self._retrieve_and_filter(skeleton, profile, state)

        # ── Step 2: 路由矩阵（带缓存，ToolHub 自动去重）──
        route_cache = self._build_route_cache(candidates, skeleton)

        # ── Step 3: 组合 ──
        combos = generate_combinations(
            candidates, skeleton, profile, route_cache,
            max_combos=MAX_COMBOS,
        )
        if not combos:
            state.errors.append(f"无可行的阶段组合（{chosen['label']}）")
            return state

        # ── Step 4-6: 打分 Agent（规则 + 地理凝聚力 + pairwise 校准）──
        scored = self.scorer.full_pipeline(combos, profile)

        # ── Step 7: 顺路插入 ──
        top = scored[:2]
        if self.llm.api_key:
            for plan in top:
                plan.insertions = judge_route_insertions(
                    plan, profile, INSERTABLE_CATALOG, self.llm
                )

        # ── Step 8: Top-2 摘要 ──
        if self.llm.api_key:
            for plan in top:
                plan.summary = generate_summary(plan, self.llm)

        # ── 汇总输出 ──
        state.scored_plans = top
        state.candidates = candidates
        state.tool_trace = tracer.drain()
        tracer.log("planner_pipeline", "success", {
            "order": chosen["best_order"],
            "label": chosen["label"],
            "order_reason": chosen["reason"],
            "top_plans": len(top),
            "best_score": top[0].score if top else 0,
            "cache_stats": self.hub.stats,
        })
        state.tool_trace.extend(tracer.drain())
        return state

    # ── 内部步骤 ──────────────────────────────────────

    def _retrieve_and_filter(
        self,
        skeleton: TimelineSkeleton,
        profile: UserProfile,
        state: PlannerState,
    ) -> dict[str, list]:
        candidates: dict[str, list] = {}
        segments = [s for s in skeleton.segments if s.target_duration_min > 0]

        with ThreadPoolExecutor(max_workers=len(segments)) as pool:
            futures = {}
            for seg in segments:
                filters = _build_search_filters(profile, seg)
                fut = pool.submit(
                    self.hub.parallel_retrieve,
                    seg.category_filter,
                    profile.geo.anchor,
                    filters,
                    MAX_CANDIDATES_PER_STAGE,
                )
                futures[fut] = seg

            for fut in as_completed(futures):
                seg = futures[fut]
                try:
                    raw = fut.result()
                    filtered = apply_stage_filters(raw, seg, profile)
                    candidates[seg.stage_type.value] = filtered
                except Exception as e:
                    candidates[seg.stage_type.value] = []
                    state.errors.append(f"检索失败 [{seg.category_filter}]: {e}")

        return candidates

    def _build_route_cache(
        self,
        candidates: dict[str, list],
        skeleton: TimelineSkeleton,
    ) -> dict:
        route_cache: dict = {}
        segments = [s for s in skeleton.segments if s.target_duration_min > 0]
        for i in range(len(segments) - 1):
            pois_a = [ep.poi for ep in candidates.get(
                segments[i].stage_type.value, []
            )]
            pois_b = [ep.poi for ep in candidates.get(
                segments[i + 1].stage_type.value, []
            )]
            if pois_a and pois_b:
                route_cache.update(
                    self.hub.fetch_routes_between(pois_a, pois_b)
                )
        return route_cache

def build_planner_graph(llm_client: LLMClient | None = None):
    """构建 LangGraph 版 Planner 图（可选依赖）。"""
    try:
        from langgraph.graph import StateGraph, END
    except ImportError:
        raise ImportError("langgraph 未安装。请执行: pip install langgraph")

    engine = PlannerEngine(llm_client=llm_client)

    def plan_node(state: PlannerState) -> dict:
        result = engine.run(state.profile, state.raw_query)
        return {
            "scored_plans": result.scored_plans,
            "candidates": result.candidates,
            "tool_trace": result.tool_trace,
            "errors": result.errors,
        }

    builder = StateGraph(PlannerState)
    builder.add_node("plan", plan_node)
    builder.set_entry_point("plan")
    builder.add_edge("plan", END)

    return builder.compile()


# ── 辅助 ──────────────────────────────────────────────


def _build_search_filters(profile: UserProfile, seg) -> dict | None:
    filters = {}
    if profile.budget_per_person:
        filters["人均"] = (
            f"{profile.budget_per_person.min}-{profile.budget_per_person.max}"
        )
    if profile.hard_filters:
        filters["标签"] = profile.hard_filters
    return filters if filters else None
