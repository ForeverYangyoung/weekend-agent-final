"""HIL 会话：规划暂停、画像覆盖、从 Researcher 重跑。"""
from __future__ import annotations

import uuid
from typing import Any

from backend.agents.planner import (
    _HEAVY_FOOD_KEYS,
    _LOW_CAL_KEYS,
    _candidate_text,
    _explicit_cuisines,
    _matches_cuisine,
    _wants_light_meal,
)

BUILD_VERSION = "2026-06-06-issue-v4"
from backend.schemas import GroupProfile, Plan, POICandidate, ResearchResult
from backend.state import AgentState

_sessions: dict[str, AgentState] = {}


def create_session(state: AgentState) -> str:
    session_id = uuid.uuid4().hex[:12]
    _sessions[session_id] = dict(state)
    return session_id


def get_session(session_id: str) -> AgentState | None:
    return _sessions.get(session_id)


def save_session(session_id: str, state: AgentState) -> None:
    _sessions[session_id] = dict(state)


def clear_planning_artifacts() -> dict[str, Any]:
    """重规划前清空下游产物，保留 user_input / group_profile。"""
    return {
        "research_result": None,
        "targeted_search_requests": [],
        "targeted_research_result": None,
        "plan": None,
        "plan_alternatives": [],
        "critic_feedback": None,
        "dry_run_calls": [],
        "executed_calls": [],
        "failed_calls": [],
        "summary_card": None,
        "user_confirmed": False,
        "selected_addon_ids": [],
        "force_failure": None,
    }


def select_plan(state: AgentState, plan_id: str) -> AgentState:
    """确认前切换主方案（primary / alt_0 / alt_1 …）。"""
    updated = dict(state)
    plan = updated.get("plan")
    alts = list(updated.get("plan_alternatives") or [])

    if plan_id == "primary" or not plan:
        return updated

    if not plan_id.startswith("alt_"):
        return updated

    try:
        idx = int(plan_id.split("_", 1)[1])
    except (IndexError, ValueError):
        return updated

    if idx < 0 or idx >= len(alts):
        return updated

    chosen = alts[idx]
    rest = [plan] + [a for i, a in enumerate(alts) if i != idx]
    updated["plan"] = chosen
    updated["plan_alternatives"] = rest
    return updated


def _stage_by_name(plan: Plan, name: str):
    return next((s for s in plan.stages if s.name == name), None)


def _short_poi_name(name: str) -> str:
    return name.split("（")[0].strip()


def _venue_extras(stage_name: str, meta: dict) -> dict[str, str]:
    avg = int(meta.get("avg_price", 0) or 0)
    dist = float(meta.get("distance_km", 0) or 0)
    price_label = ""
    if avg:
        price_label = f"约¥{avg}" if stage_name == "加餐" else f"约¥{avg}/人"
    distance_label = f"距家 {dist:g} km" if dist else ""
    return {"priceLabel": price_label, "distanceLabel": distance_label}


def _build_active_constraints(profile: GroupProfile | None) -> list[str]:
    """返回当前会话真正生效的约束，供前端先展示。"""
    if profile is None:
        return []

    constraints: list[str] = []
    scene_labels = {
        "family": "场景: 家庭",
        "friends": "场景: 朋友",
        "couple": "场景: 情侣",
        "solo": "场景: 独自",
    }
    if profile.scene in scene_labels:
        constraints.append(scene_labels[profile.scene])
    if profile.people_count:
        constraints.append(f"人数: {profile.people_count} 人")
    if profile.distance_limit_km:
        constraints.append(f"距离: ≤{profile.distance_limit_km:.0f}km")
    if profile.duration_hours:
        constraints.append(f"时长: 约{profile.duration_hours:.0f}小时")
    if profile.kids_ages:
        constraints.append(f"孩子: {profile.kids_ages[0]}岁")
    for tag in profile.dietary:
        constraints.append(f"饮食: {tag}")
    return constraints


def _build_match_reasons(plan: Plan, profile: GroupProfile | None) -> list[str]:
    """把 Profiler / Planner / Critic 命中的约束翻成可展示文案。"""
    if profile is None:
        return []

    reasons: list[str] = []
    play = _stage_by_name(plan, "玩")
    eat = _stage_by_name(plan, "吃")

    scene_labels = {
        "family": "家庭出游",
        "friends": "朋友聚会",
        "couple": "情侣约会",
        "solo": "独自放松",
    }
    if profile.scene in scene_labels:
        reasons.append(f"场景·{scene_labels[profile.scene]}")

    if profile.people_count:
        reasons.append(f"人数·{profile.people_count} 人")

    if eat is not None:
        eat_text = _candidate_text(eat.primary)
        if _wants_light_meal(profile):
            if any(k.lower() in eat_text for k in _LOW_CAL_KEYS):
                reasons.append("饮食·轻食/低卡（已匹配餐厅）")
            elif any(k.lower() in eat_text for k in _HEAVY_FOOD_KEYS):
                reasons.append("未满足·轻食约束（当前餐厅为重口味）")
        elif "重口味" in profile.dietary:
            if any(k in eat_text for k in ("烤肉", "火锅", "重口味")):
                reasons.append("口味·重口味（烤肉/火锅）")
        for tag in _explicit_cuisines(profile):
            if tag not in ("轻食",) and _matches_cuisine(eat.primary, {tag}):
                reasons.append(f"菜系·{tag}（已匹配）")

    if profile.kids_ages and play is not None:
        reasons.append(f"亲子·适合 {profile.kids_ages[0]} 岁娃")

    if play is not None and eat is not None:
        d_play = float(play.primary.metadata.get("distance_km", 0) or 0)
        d_eat = float(eat.primary.metadata.get("distance_km", 0) or 0)
        if abs(d_play - d_eat) <= 3.0:
            reasons.append("顺路·玩/吃相距 ≤3km")

    if eat is not None and profile.people_count >= 4:
        table_types = eat.primary.metadata.get("table_type") or []
        reason_text = eat.primary.reason or ""
        if "4 人" in reason_text or "4人" in reason_text or "4人桌" in table_types:
            reasons.append("订座·支持 4 人桌")

    if profile.scene == "friends" and eat is not None:
        eat_tags = eat.primary.metadata.get("tags") or []
        if "社交" in eat_tags:
            reasons.append("氛围·适合朋友社交")

    if profile.distance_limit_km and play is not None and eat is not None:
        d_play = float(play.primary.metadata.get("distance_km", 0) or 0)
        d_eat = float(eat.primary.metadata.get("distance_km", 0) or 0)
        if max(d_play, d_eat) <= profile.distance_limit_km:
            reasons.append(f"距离·≤{profile.distance_limit_km:.0f}km")

    return reasons


_HEAVY_CUISINE_TAGS = frozenset({"川菜", "火锅", "烤肉", "重口味", "湘菜"})
_MAX_PLAY_EAT_DIST_KM = 3.0


def detect_preference_conflicts(profile: GroupProfile | None) -> list[dict[str, Any]]:
    """画像层矛盾：轻食/减肥 vs 重口味菜系等，需用户先改偏好再规划。"""
    if profile is None:
        return []

    conflicts: list[dict[str, Any]] = []
    cuisines = _explicit_cuisines(profile)
    heavy_cuisines = sorted(cuisines & _HEAVY_CUISINE_TAGS)
    light = _wants_light_meal(profile)

    if light and heavy_cuisines:
        heavy_text = "、".join(heavy_cuisines)
        conflicts.append(
            {
                "code": "light_vs_heavy_cuisine",
                "headline": "Zero-Skill Mock：隐式健康档案与显式偏好冲突",
                "detail": (
                    "跨端档案显示家庭成员处于控糖控卡周期，已自动叠加「轻食/低卡」；"
                    f"但您又指定了「{heavy_text}」。"
                    "请先调整偏好后再规划（保留健康档案，或显式移除低卡约束）。"
                ),
                "suggestions": [
                    f"去掉「{heavy_text}」，保留轻食/减肥",
                    "去掉轻食要求，保留重口味菜系",
                ],
                "conflictingTags": ["轻食", "低卡", *heavy_cuisines],
            }
        )

    if light and "重口味" in profile.dietary:
        conflicts.append(
            {
                "code": "light_vs_heavy_taste",
                "headline": "Zero-Skill Mock：隐式健康档案与显式偏好冲突",
                "detail": (
                    "跨端档案显示家庭成员处于控糖控卡周期，已自动叠加「轻食/低卡」；"
                    "但您又指定了「重口味」。请先调整偏好后再规划。"
                ),
                "suggestions": ["保留轻食/减肥", "改为重口味（烤肉/火锅）"],
                "conflictingTags": ["轻食", "低卡", "重口味"],
            }
        )

    no_spicy = "禁辣" in profile.dietary or "不辣" in profile.dietary
    spicy_request = "重口味" in profile.dietary or bool(heavy_cuisines)
    spicy_labels: list[str] = []
    if "重口味" in profile.dietary:
        spicy_labels.append("重口味")
    spicy_labels.extend(heavy_cuisines)
    spicy_labels = sorted(set(spicy_labels))
    if no_spicy and spicy_request:
        conflicts.append(
            {
                "code": "no_spicy_vs_heavy",
                "headline": "Zero-Skill Mock：隐式健康档案与显式偏好冲突",
                "detail": (
                    "跨端档案显示成员处于「痔疮/上火恢复期」，已自动禁辣；"
                    f"但您又指定了「{'、'.join(spicy_labels)}」。"
                    "请先调整偏好后再规划（正式版由 LTM 驱动，本 Demo 为 Mock 演示）。"
                ),
                "suggestions": [
                    "去掉重口味/川菜/火锅，保留禁辣",
                    "去掉禁辣，保留当前重口味选择",
                ],
                "conflictingTags": ["禁辣", *spicy_labels],
            }
        )

    return conflicts


def _eat_candidates_matching_near_play(
    research: ResearchResult | None,
    play: POICandidate,
    profile: GroupProfile,
    cuisines: set[str],
) -> list[POICandidate]:
    """在活动地顺路范围内，是否存在符合菜系的餐厅候选。"""
    if research is None or not cuisines:
        return []

    eat_stage = next((s for s in research.stages if s.stage_name == "吃"), None)
    if eat_stage is None:
        return []

    d_play = float(play.metadata.get("distance_km", 0) or 0)
    matches: list[POICandidate] = []
    for candidate in eat_stage.candidates:
        if not _matches_cuisine(candidate, cuisines):
            continue
        d_eat = float(candidate.metadata.get("distance_km", 0) or 0)
        if abs(d_play - d_eat) > _MAX_PLAY_EAT_DIST_KM:
            continue
        if d_eat > profile.distance_limit_km + 1e-6:
            continue
        matches.append(candidate)
    return matches


def _validate_plan_constraints(plan: Plan, profile: GroupProfile | None) -> list[str]:
    """原始约束校验文案（供内部分类）。"""
    if profile is None:
        return []

    issues: list[str] = []
    play = _stage_by_name(plan, "玩")
    eat = _stage_by_name(plan, "吃")

    if eat is not None:
        eat_text = _candidate_text(eat.primary)
        eat_name = eat.primary.name
        if _wants_light_meal(profile):
            if any(k.lower() in eat_text for k in _HEAVY_FOOD_KEYS):
                issues.append(f"轻食约束冲突：{eat_name} 属于重口味/烤肉类")
            elif not any(k.lower() in eat_text for k in _LOW_CAL_KEYS):
                issues.append(f"轻食约束未满足：{eat_name} 缺少轻食/低卡标签")
        for cuisine in _explicit_cuisines(profile):
            if cuisine == "轻食" and _wants_light_meal(profile):
                continue
            if not _matches_cuisine(eat.primary, {cuisine}):
                issues.append(f"菜系约束未满足：{eat_name} 不匹配 {cuisine}")

    if play is not None and eat is not None:
        d_play = float(play.primary.metadata.get("distance_km", 0) or 0)
        d_eat = float(eat.primary.metadata.get("distance_km", 0) or 0)
        if abs(d_play - d_eat) > _MAX_PLAY_EAT_DIST_KM:
            issues.append("顺路约束未满足：玩/吃距离差超过 3km")
        if max(d_play, d_eat) > profile.distance_limit_km:
            issues.append(f"距离约束未满足：超出 {profile.distance_limit_km:.0f}km")

    return issues


def _build_plan_issues(
    plan: Plan,
    profile: GroupProfile | None,
    research: ResearchResult | None,
    pref_conflicts: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str, bool]:
    """把校验结果翻成用户可理解的 issue，并给出 issueKind。"""
    if profile is None:
        return [], "ok", True

    if pref_conflicts:
        return (
            [
                {
                    "code": c["code"],
                    "headline": c["headline"],
                    "detail": c["detail"],
                    "suggestions": c.get("suggestions", []),
                    "allowAcceptAlternative": False,
                }
                for c in pref_conflicts
            ],
            "needs_preference_fix",
            False,
        )

    raw_issues = _validate_plan_constraints(plan, profile)
    if not raw_issues:
        return [], "ok", True

    play = _stage_by_name(plan, "玩")
    eat = _stage_by_name(plan, "吃")
    play_label = _short_poi_name(play.primary.name) if play else "活动地"
    eat_name = eat.primary.name if eat else "当前餐厅"

    structured: list[dict[str, Any]] = []
    issue_kind = "blocked"
    allow_accept = False

    for raw in raw_issues:
        if raw.startswith("菜系约束未满足：") and play and eat:
            missing = raw.split("不匹配 ", 1)[-1].strip()
            eat_short = _short_poi_name(eat_name)
            nearby = _eat_candidates_matching_near_play(
                research, play.primary, profile, {missing}
            )
            if not nearby:
                structured.append(
                    {
                        "code": "cuisine_unavailable",
                        "headline": f"附近找不到「{missing}」餐厅",
                        "detail": (
                            f"您指定了「{missing}」。在「{play_label}」周边 "
                            f"{_MAX_PLAY_EAT_DIST_KM:g}km、且总距离 ≤{profile.distance_limit_km:.0f}km "
                            f"的范围内，Mock 数据里没有符合条件的「{missing}」店。"
                            f"系统暂时用「{eat_short}」凑了一条顺路方案。"
                        ),
                        "suggestions": [
                            f"若可接受轻食/其他口味：点「接受 {eat_short} 替代」",
                            f"若坚持「{missing}」：去掉距离限制或换「海淀区」等活动区域后重规划",
                            f"或修改偏好，去掉「{missing}」",
                        ],
                        "allowAcceptAlternative": True,
                        "missingCuisine": missing,
                        "playArea": play_label,
                    }
                )
                issue_kind = "alternative_available"
                allow_accept = True
                continue

            nearby_names = "、".join(_short_poi_name(c.name) for c in nearby[:3])
            structured.append(
                {
                    "code": "cuisine_not_matched_but_nearby",
                    "headline": f"您要「{missing}」，但当前推荐的不是这类店",
                    "detail": (
                        f"方案里吃饭选的是「{eat_short}」，不符合「{missing}」。"
                        f"其实在「{play_label}」周边 {_MAX_PLAY_EAT_DIST_KM:g}km 内"
                        f"能找到：{nearby_names}。请点击「重新规划」换店。"
                    ),
                    "suggestions": [
                        "点「按新偏好重新规划」自动换川菜店",
                        f"或去掉「{missing}」接受当前「{eat_short}」",
                    ],
                    "allowAcceptAlternative": False,
                    "missingCuisine": missing,
                    "playArea": play_label,
                    "nearbyOptions": nearby_names,
                }
            )
            issue_kind = "needs_preference_fix"
            continue

        if "顺路约束" in raw or "距离约束" in raw:
            structured.append(
                {
                    "code": "distance_limit",
                    "headline": "距离或顺路条件偏紧",
                    "detail": (
                        f"{raw}。可放宽距离上限，或换更近的活动/餐厅组合。"
                    ),
                    "suggestions": [
                        "放宽距离（如改为 15km）",
                        "修改偏好后重新规划",
                    ],
                    "allowAcceptAlternative": False,
                }
            )
            issue_kind = "blocked"
            continue

        structured.append(
            {
                "code": "constraint_mismatch",
                "headline": "方案与偏好不完全匹配",
                "detail": raw,
                "suggestions": ["修改偏好后重新规划"],
                "allowAcceptAlternative": False,
            }
        )

    if not structured:
        structured = [
            {
                "code": "constraint_mismatch",
                "headline": "方案需调整",
                "detail": raw_issues[0],
                "suggestions": ["修改偏好后重新规划"],
                "allowAcceptAlternative": False,
            }
        ]

    _ = allow_accept  # 前端按 issueKind + 用户「接受替代」再放开下单
    return structured, issue_kind, False


def _diff_summary(primary: Plan | None, alt: Plan) -> str:
    if primary is None:
        return "备选方案"

    p_play = _stage_by_name(primary, "玩")
    a_play = _stage_by_name(alt, "玩")
    p_eat = _stage_by_name(primary, "吃")
    a_eat = _stage_by_name(alt, "吃")

    parts: list[str] = []
    if p_play and a_play and p_play.primary.poi_id != a_play.primary.poi_id:
        parts.append(f"玩法改为「{_short_poi_name(a_play.primary.name)}」")
    if p_eat and a_eat and p_eat.primary.poi_id != a_eat.primary.poi_id:
        parts.append(f"餐厅改为「{_short_poi_name(a_eat.primary.name)}」")

    return "；".join(parts) if parts else "同路线备选"


def plan_to_display(
    plan: Plan,
    plan_id: str,
    people_count: int,
    *,
    profile: GroupProfile | None = None,
    primary: Plan | None = None,
    research: ResearchResult | None = None,
    pref_conflicts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """前端行程卡 JSON。"""
    stage_map = {"玩": "play", "吃": "eat", "加餐": "addon"}
    match_reasons = _build_match_reasons(plan, profile)
    conflicts = pref_conflicts if pref_conflicts is not None else detect_preference_conflicts(profile)
    plan_issues, issue_kind, is_valid = _build_plan_issues(
        plan, profile, research, conflicts
    )
    constraint_issues = [i["detail"] for i in plan_issues]
    payload: dict[str, Any] = {
        "id": plan_id,
        "title": plan.summary,
        "order_label": plan.order_label,
        "score": int(round(plan.score * 100)) if plan.score <= 1 else int(plan.score),
        "totalPrice": f"¥{max(plan.total_cost_estimate // max(people_count, 1), 0)}/人",
        "activeConstraints": _build_active_constraints(profile),
        "highlights": match_reasons,
        "matchReasons": match_reasons,
        "planIssues": plan_issues,
        "issueKind": issue_kind,
        "allowAcceptAlternative": any(
            i.get("allowAcceptAlternative") for i in plan_issues
        ),
        "constraintIssues": constraint_issues,
        "isValid": is_valid,
    }

    if plan_id != "primary" and primary is not None:
        payload["diffSummary"] = _diff_summary(primary, plan)
    elif plan_id == "primary":
        payload["diffSummary"] = "综合评分最高"

    for stage in plan.stages:
        key = stage_map.get(stage.name, stage.name)
        meta = stage.primary.metadata or {}
        tags = meta.get("tags") or []
        if not tags and stage.primary.category:
            tags = [stage.primary.category]
        extras = _venue_extras(stage.name, meta)
        payload[key] = {
            "name": stage.primary.name,
            "time": f"{stage.start_time}–{stage.end_time}",
            "desc": stage.primary.reason or "",
            "tags": list(tags),
            **extras,
        }

    if plan.addons:
        payload["addons"] = [
            {
                "addon_id": a.addon_id,
                "type": a.type,
                "description": a.description,
                "price": a.price,
                "target_poi_id": a.target_poi_id,
            }
            for a in plan.addons
        ]

    return payload


def build_plans_payload(state: AgentState) -> list[dict[str, Any]]:
    profile = state.get("group_profile")
    people = profile.people_count if profile else 1
    research = state.get("research_result")
    pref_conflicts = detect_preference_conflicts(profile)
    items: list[dict[str, Any]] = []

    plan = state.get("plan")
    if plan:
        items.append(
            plan_to_display(
                plan,
                "primary",
                people,
                profile=profile,
                primary=None,
                research=research,
                pref_conflicts=pref_conflicts,
            )
        )

    for i, alt in enumerate(state.get("plan_alternatives") or []):
        items.append(
            plan_to_display(
                alt,
                f"alt_{i}",
                people,
                profile=profile,
                primary=plan,
                research=research,
                pref_conflicts=pref_conflicts,
            )
        )

    return items


def profile_chips(profile: GroupProfile | None) -> list[dict[str, Any]]:
    if profile is None:
        return []
    return [t.model_dump(mode="json") for t in profile.editable_tags]
