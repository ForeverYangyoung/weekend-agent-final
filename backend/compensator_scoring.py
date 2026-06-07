"""Compensator 公式选店：Score = α·f_health + β·f_child - γ·D。"""
from __future__ import annotations

from backend.schemas import GroupProfile, POICandidate, Plan

_ALPHA = 0.35
_BETA = 0.35
_GAMMA = 0.30

_KIDS_KEYS = ("亲子", "儿童", "公园", "童", "宝宝", "海洋馆")
_LIGHT_KEYS = ("轻食", "低卡", "沙拉", "健康", "少糖")
_HEAVY_KEYS = ("烤肉", "火锅", "烧烤", "重口味", "川菜")
_SNACK_KEYS = ("快餐", "小吃", "简餐", "便利店")
_CROWDED_POIS = frozenset({"poi_rest_201"})


def _candidate_text(c: POICandidate) -> str:
    tags = c.metadata.get("tags") or []
    return f"{c.name} {c.category} {c.reason} {' '.join(str(t) for t in tags)}".lower()


def f_health(c: POICandidate) -> float:
    if c.metadata.get("is_low_calorie") is True:
        return 1.0
    text = _candidate_text(c)
    if any(k in text for k in _LIGHT_KEYS):
        return 1.0
    if any(k in text for k in _HEAVY_KEYS):
        return 0.25
    return 0.55


def f_child(c: POICandidate) -> float:
    if c.metadata.get("kid_friendly") is True:
        return 1.0
    text = _candidate_text(c)
    if any(k in text for k in _KIDS_KEYS):
        return 1.0
    if c.metadata.get("is_crowded"):
        return 0.3
    return 0.45


def distance_gap_km(c: POICandidate, anchor_km: float) -> float:
    d = float(c.metadata.get("distance_km", 0) or 0)
    return abs(d - anchor_km)


def compensator_score(
    c: POICandidate,
    *,
    anchor_km: float,
    profile: GroupProfile | None,
) -> float:
    """Score(p) = α·f_health + β·f_child - γ·D"""
    scene = profile.scene if profile else "unknown"
    health = f_health(c)
    child = f_child(c)
    if scene == "friends":
        health = 0.5
        child = 0.5 if not c.metadata.get("is_crowded") else 0.2
    dist = distance_gap_km(c, anchor_km)
    return _ALPHA * health + _BETA * child - _GAMMA * dist


def _anchor_km_for_stage(plan: Plan, stage_name: str) -> float:
    if stage_name == "吃":
        play = next((s for s in plan.stages if s.name == "玩"), None)
        if play is not None:
            return float(play.primary.metadata.get("distance_km", 0) or 0)
    stage = next((s for s in plan.stages if s.name == stage_name), None)
    if stage is not None:
        return float(stage.primary.metadata.get("distance_km", 0) or 0)
    return 0.0


def _pool_for_stage(
    candidates: list[POICandidate],
    *,
    failed_poi_id: str,
    profile: GroupProfile | None,
    stage_name: str,
) -> list[POICandidate]:
    scene = profile.scene if profile else "unknown"
    pool: list[POICandidate] = []
    for c in candidates:
        if c.poi_id == failed_poi_id:
            continue
        if scene == "friends" and stage_name == "吃":
            if c.poi_id in _CROWDED_POIS or c.metadata.get("is_crowded"):
                continue
            text = _candidate_text(c)
            if any(k in text for k in _SNACK_KEYS):
                continue
        if scene == "family" and stage_name == "吃":
            text = _candidate_text(c)
            dietary = set(profile.dietary if profile else [])
            if "火锅" in dietary and "火锅" not in text:
                continue
            if dietary & {"轻食", "低卡"} and not any(k in text for k in _LIGHT_KEYS):
                if not dietary & {"火锅", "烤肉", "川菜", "重口味"}:
                    continue
        pool.append(c)
    return pool


def pick_best_alternative(
    candidates: list[POICandidate],
    *,
    failed_poi_id: str,
    plan: Plan,
    stage_name: str,
    profile: GroupProfile | None,
    exclude_poi_ids: set[str] | None = None,
) -> POICandidate | None:
    reserved = set(exclude_poi_ids or ())
    reserved.add(failed_poi_id)
    pool = _pool_for_stage(
        candidates,
        failed_poi_id=failed_poi_id,
        profile=profile,
        stage_name=stage_name,
    )
    pool = [c for c in pool if c.poi_id not in reserved]
    if not pool:
        pool = _pool_for_stage(
            candidates,
            failed_poi_id=failed_poi_id,
            profile=profile,
            stage_name=stage_name,
        )
    if not pool:
        return None
    anchor = _anchor_km_for_stage(plan, stage_name)
    ranked = sorted(
        pool,
        key=lambda c: compensator_score(c, anchor_km=anchor, profile=profile),
        reverse=True,
    )
    return ranked[0]
