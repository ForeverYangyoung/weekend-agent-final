"""候选组合生成器。

两段式组合 + 边组边剪枝 + 贪心兜底（02 文档 §4.1 步骤 4）。
"""

from planner.state import (
    Combo,
    EnrichedPOI,
    POI,
    RouteResult,
    StageAssignment,
    StageType,
    TimeSegment,
    TimelineSkeleton,
    UserProfile,
)

MAX_COMBOS = 15


def generate_combinations(
    stage_candidates: dict[str, list[EnrichedPOI]],
    skeleton: TimelineSkeleton,
    profile: UserProfile,
    route_cache: dict[tuple[str, str], RouteResult] | None = None,
    max_combos: int = MAX_COMBOS,
) -> list[Combo]:
    """两段式组合：玩×吃 → 剪枝 → ×增 → 剪枝。

    stage_candidates key 是 StageType.value（"玩"、"吃"、"增"）。
    """
    if route_cache is None:
        route_cache = {}

    segments = [s for s in skeleton.segments if s.target_duration_min > 0]
    if len(segments) < 2:
        return _single_stage_combos(stage_candidates, segments)

    # 按 skeleton 顺序取每阶段的候选列表
    stage_keys = _get_stage_keys(segments)
    lists = []
    for key in stage_keys:
        cands = stage_candidates.get(key, [])
        if not cands:
            cands = _fallback_candidates(key)
        lists.append(cands)

    # Phase 1: 前两段组合 + 剪枝
    partials: list[list[EnrichedPOI]] = []
    for a in lists[0]:
        for b in lists[1]:
            route_key = (a.poi.id, b.poi.id)
            route = route_cache.get(route_key)
            transit_min = route.duration_min if route else 15.0
            if transit_min > 45:  # 路途 > 45min → 剪掉
                continue
            partials.append([a, b])

    if len(partials) >= max_combos:
        partials = partials[:max_combos]

    # Phase 2: 叠加第三段（如果有）
    if len(lists) <= 2:
        return [_partial_to_combo(p, skeleton, route_cache) for p in partials]

    combos: list[Combo] = []
    for partial in partials:
        for c in lists[2]:
            route_key = (partial[-1].poi.id, c.poi.id)
            route = route_cache.get(route_key)
            transit_min = route.duration_min if route else 15.0
            if transit_min > 45:
                continue
            combo = _partial_to_combo(partial + [c], skeleton, route_cache)
            if combo.total_duration_min <= profile.time_window.duration_hours * 60 * 1.2:
                combos.append(combo)
            if len(combos) >= max_combos:
                return combos

    # 没组合也把 partial 升格（增项可选的情况下）
    if not combos:
        combos = [_partial_to_combo(p, skeleton, route_cache) for p in partials]

    return combos[:max_combos]


def _partial_to_combo(
    enriched_list: list[EnrichedPOI],
    skeleton: TimelineSkeleton,
    route_cache: dict[tuple[str, str], RouteResult],
) -> Combo:
    """把 EnrichedPOI 序列转成 Combo。"""
    stages: list[StageAssignment] = []
    segments = [s for s in skeleton.segments if s.target_duration_min > 0]

    for i, ep in enumerate(enriched_list):
        stage_type = segments[i].stage_type if i < len(segments) else StageType.ENRICH
        route = None
        if i > 0:
            prev_id = enriched_list[i - 1].poi.id
            route = route_cache.get((prev_id, ep.poi.id))
        stages.append(StageAssignment(
            stage_type=stage_type,
            poi=ep.poi,
            route_from_prev=route,
        ))

    return Combo(stages=stages)


def _single_stage_combos(
    stage_candidates: dict[str, list[EnrichedPOI]],
    segments: list[TimeSegment],
) -> list[Combo]:
    """退化情况：只有一段有效阶段。"""
    key = segments[0].stage_type.value
    cands = stage_candidates.get(key, [])
    return [Combo(stages=[StageAssignment(
        stage_type=segments[0].stage_type, poi=ep.poi
    )]) for ep in cands]


def _get_stage_keys(segments: list[TimeSegment]) -> list[str]:
    return [s.stage_type.value for s in segments]


def _fallback_candidates(stage_key: str) -> list[EnrichedPOI]:
    """某阶段无候选时给一个虚拟占位，保证组合不中断。"""
    dummy_poi = POI(
        id=f"fallback_{stage_key}",
        name=f"[缺省]{stage_key}",
        category=stage_key,
        location="未知",
        avg_price=0,
        rating=3.0,
    )
    return [EnrichedPOI(poi=dummy_poi)]
