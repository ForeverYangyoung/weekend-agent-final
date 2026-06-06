"""Researcher Agent：两阶段搜索。

Phase 1 — run_initial_research：搜「吃」+「玩」，五维打分，返回 ResearchResult。
  Planner 拿到初搜结果后决定阶段顺序、组合、顺路活动需求。

Phase 2 — run_targeted_research：根据 Planner 给出的精准搜索需求（位置/品类），
  搜顺路活动 POI（加餐/甜品/奶茶等），五维打分后返回。
"""

from __future__ import annotations

from typing import Any

from backend.schemas import (
    GroupProfile,
    POICandidate,
    ResearchResult,
    ResearchStageResult,
    ScoreBreakdown,
)
from backend.tools.errors import ToolError
from backend.tools.http_client import search_poi

_TOP_K = 3
_TOP_K_EAT_WITH_HARD_CONSTRAINT = 8

_WEIGHTS: dict[str, float] = {
    "preference": 0.35,
    "history": 0.20,
    "rating": 0.20,
    "distance": 0.15,
    "budget": 0.10,
}

# ─────────────────────────── Phase 1：初搜（吃 + 玩） ───────────────────────────


def run_initial_research(profile: GroupProfile | None) -> ResearchResult:
    """初搜：只搜「吃」和「玩」两个核心阶段，不做顺序决策。

    Planner 拿到这两个阶段的候选后，根据时间和画像决定：
      - 先吃后玩 vs 先玩后吃
      - 是否需要加餐/顺路活动
      - 需要哪些精准搜索来补充
    """
    if profile is None:
        return ResearchResult(stages=[], tool_trace=["skip: no profile"])

    scene_key = profile.scene if profile.scene != "unknown" else "family"
    stages: list[ResearchStageResult] = []
    trace: list[str] = []

    for stage_name in ("玩", "吃"):
        try:
            raw = search_poi(scene=scene_key, stage=stage_name, limit=10)
        except ToolError as e:
            trace.append(
                f"GET /poi/search(stage={stage_name}) → {e.code} {e.message}"
            )
            continue

        candidates = [_to_candidate(it) for it in raw]
        if not candidates:
            trace.append(f"GET /poi/search(stage={stage_name}) → 0")
            continue

        ranked = _rank_and_filter(candidates, profile, stage_name)
        if not ranked:
            trace.append(
                f"GET /poi/search(stage={stage_name}) → {len(candidates)}，"
                f"过滤后 0（distance_limit={profile.distance_limit_km}）"
            )
            continue

        top = ranked[0]
        stages.append(
            ResearchStageResult(
                stage_name=stage_name, candidates=ranked, selected=top
            )
        )
        bd = top.breakdown
        bd_str = (
            f" total={bd.total:.2f} pref={bd.preference:.2f} hist={bd.history:.2f}"
            f" dist={bd.distance:.2f}"
            if bd
            else ""
        )
        trace.append(
            f"GET /poi/search(stage={stage_name}) → {len(ranked)} top={top.name}{bd_str}"
        )

    return ResearchResult(stages=stages, tool_trace=trace)


# ─────────────────────────── Phase 2：精准搜（顺路活动） ───────────────────────────


def run_targeted_research(
    profile: GroupProfile | None,
    requests: list[dict] | None,
) -> ResearchResult:
    """精准搜：根据 Planner 给的搜索需求，搜顺路活动 POI。

    requests 每项格式：
        {"stage": "加餐", "scene": "family", "limit": 5, "reason": "顺路买奶茶"}

    返回的 stage_name 会带上 reason 以便前端区分。
    """
    if profile is None or not requests:
        return ResearchResult(stages=[], tool_trace=["skip: no profile or no requests"])

    scene_key = profile.scene if profile.scene != "unknown" else "family"
    stages: list[ResearchStageResult] = []
    trace: list[str] = []

    for req in requests:
        stage_name = req.get("stage", "加餐")
        scene = req.get("scene", scene_key)
        limit = req.get("limit", 5)
        reason = req.get("reason", "")

        try:
            raw = search_poi(scene=scene, stage=stage_name, limit=limit)
        except ToolError as e:
            trace.append(
                f"targeted: {reason} → {e.code} {e.message}"
            )
            continue

        candidates = [_to_candidate(it) for it in raw]
        if not candidates:
            trace.append(f"targeted: {reason} → 0")
            continue

        ranked = _rank_and_filter(candidates, profile, stage_name)
        if not ranked:
            trace.append(
                f"targeted: {reason} → {len(candidates)} raw, "
                f"过滤后 0（distance_limit={profile.distance_limit_km}）"
            )
            continue

        top = ranked[0]
        label = f"{stage_name}" if not reason else f"{stage_name}({reason})"
        stages.append(
            ResearchStageResult(
                stage_name=label,
                candidates=ranked,
                selected=top,
            )
        )
        trace.append(
            f"targeted: {reason} → {len(ranked)} top={top.name}"
        )

    return ResearchResult(stages=stages, tool_trace=trace)


# ─────────────────────────── 辅助函数 ───────────────────────────


def _to_candidate(item: dict[str, Any]) -> POICandidate:
    return POICandidate(
        poi_id=item.get("poi_id", ""),
        name=item.get("name", ""),
        category=item.get("category", ""),
        score=float(item.get("score", 0.0) or 0.0),
        reason=item.get("reason", ""),
        metadata=dict(item.get("metadata") or {}),
    )


# ─────────────────────────── 五维打分（两阶段共用） ───────────────────────────


def _hit_in_text(text_lower: str, candidates) -> int:
    return sum(1 for t in candidates if t and t.lower() in text_lower)


def _score_preference(c: POICandidate, profile: GroupProfile) -> float:
    target = set(profile.interests) | set(profile.dietary)
    if profile.scene == "family":
        target |= {"亲子", "儿童"}
    if profile.scene == "friends":
        target |= {"朋友", "聚餐"}
    if not target:
        return 0.5
    tags = c.metadata.get("tags") or []
    tag_str = " ".join(str(t) for t in tags)
    haystack = f"{c.name} {c.category} {c.reason} {tag_str}".lower()
    hits = _hit_in_text(haystack, target)
    return min(1.0, hits / max(len(target), 1) * 2)


def _score_history(c: POICandidate, profile: GroupProfile) -> float:
    if not profile.history_weights:
        return 0.5
    haystack = f"{c.name} {c.category} {c.reason}".lower()
    values = [
        w
        for tag, w in profile.history_weights.items()
        if tag and tag.lower() in haystack
    ]
    return max(values) if values else 0.3


def _score_rating(c: POICandidate) -> float:
    return max(0.0, min(c.score, 1.0))


def _score_distance(c: POICandidate, profile: GroupProfile) -> float:
    d = float(c.metadata.get("distance_km", 0) or 0)
    limit = max(profile.distance_limit_km, 1.0)
    return max(0.0, 1.0 - d / limit)


def _score_budget(c: POICandidate, profile: GroupProfile, stage_name: str) -> float:
    avg_price = float(c.metadata.get("avg_price", 0) or 0)
    budget = profile.budget_per_person
    if stage_name != "吃" or budget is None or avg_price <= 0:
        return 0.7
    if avg_price <= budget:
        return 1.0
    over_ratio = (avg_price - budget) / max(budget, 1)
    return max(0.0, 1.0 - over_ratio)


def _score_one(
    c: POICandidate, profile: GroupProfile, stage_name: str
) -> ScoreBreakdown:
    pref = _score_preference(c, profile)
    hist = _score_history(c, profile)
    rating = _score_rating(c)
    dist = _score_distance(c, profile)
    budget = _score_budget(c, profile, stage_name)
    total = (
        _WEIGHTS["preference"] * pref
        + _WEIGHTS["history"] * hist
        + _WEIGHTS["rating"] * rating
        + _WEIGHTS["distance"] * dist
        + _WEIGHTS["budget"] * budget
    )
    return ScoreBreakdown(
        preference=round(pref, 3),
        history=round(hist, 3),
        rating=round(rating, 3),
        distance=round(dist, 3),
        budget=round(budget, 3),
        total=round(total, 3),
    )


def _rank_and_filter(
    candidates: list[POICandidate], profile: GroupProfile, stage_name: str
) -> list[POICandidate]:
    kept: list[POICandidate] = []
    for c in candidates:
        if float(c.metadata.get("distance_km", 0) or 0) > profile.distance_limit_km:
            continue
        scored = c.model_copy(
            update={"breakdown": _score_one(c, profile, stage_name)}
        )
        kept.append(scored)

    if not kept:
        return []

    if profile.district:
        district_key = profile.district.replace("区", "")
        district_hits = [
            c
            for c in kept
            if c.metadata.get("district") == profile.district
            or district_key in c.name
            or district_key in c.reason
        ]
        if district_hits:
            kept = district_hits

    kept.sort(
        key=lambda x: (x.breakdown.total if x.breakdown else 0.0), reverse=True
    )

    # 吃阶段若用户给了明确饮食约束（如 川菜/火锅/轻食），
    # 不要在 Researcher 就过早裁掉长尾候选；留给 Planner 做硬过滤与组合。
    if stage_name == "吃" and profile.dietary:
        return kept[:_TOP_K_EAT_WITH_HARD_CONSTRAINT]
    return kept[:_TOP_K]
