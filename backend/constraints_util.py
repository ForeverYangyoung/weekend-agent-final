"""硬约束：从画像初始化、满座后修正、候选过滤。"""
from __future__ import annotations

from backend.schemas import ConstraintTracker, GroupProfile, POICandidate


def build_constraints(profile: GroupProfile | None) -> ConstraintTracker:
    if profile is None:
        return ConstraintTracker()
    cuisines: list[str] = []
    dietary = set(profile.dietary or [])
    if dietary & {"低卡", "轻食", "沙拉"}:
        cuisines.extend(["轻食", "沙拉", "江浙菜", "日料"])
        calories = 600.0
    else:
        cuisines.extend(["火锅", "川菜", "烤肉", "江浙菜"])
        calories = 1200.0
    if "火锅" in dietary:
        cuisines = ["火锅", *cuisines]
    if profile.scene == "family":
        cuisines = [c for c in cuisines if c not in ("重辣",)]
    return ConstraintTracker(
        remaining_calories=calories,
        child_fatigue_index=0,
        accepted_cuisines=list(dict.fromkeys(cuisines)),
    )


def blocked_poi_ids(anomaly_encountered: list[str] | None) -> set[str]:
    blocked: set[str] = set()
    for item in anomaly_encountered or []:
        pid = item.removesuffix("_full").removesuffix("_sold_out")
        if pid:
            blocked.add(pid)
    return blocked


def apply_full_seat_constraint_update(
    constraints: ConstraintTracker,
    *,
    failed_poi_id: str,
) -> ConstraintTracker:
    """满座等位：儿童疲劳度 +20（封顶 100）。"""
    updated = constraints.model_copy(deep=True)
    updated.child_fatigue_index = min(100, updated.child_fatigue_index + 20)
    # 延误消耗一点热量预算（等待走动）
    updated.remaining_calories = max(200.0, updated.remaining_calories - 30.0)
    return updated


def candidate_passes_constraints(
    c: POICandidate,
    constraints: ConstraintTracker | None,
    *,
    stage_name: str = "吃",
) -> bool:
    if constraints is None:
        return True
    meta = c.metadata or {}
    if constraints.child_fatigue_index > 80 and stage_name == "玩":
        if not meta.get("is_indoor") and "室内" not in " ".join(meta.get("tags") or []):
            return False
    if stage_name == "吃":
        cal = meta.get("avg_calories_per_meal")
        if cal is not None and float(cal) > constraints.remaining_calories:
            return False
        if constraints.accepted_cuisines:
            text = f"{c.name} {c.category} {' '.join(meta.get('tags') or [])}"
            if not any(cu in text for cu in constraints.accepted_cuisines):
                return False
    ages = meta.get("suitable_ages")
    if ages and stage_name == "玩":
        if not any(a in ages for a in (3, 4, 5)):
            return False
    return True
