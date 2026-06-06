"""Critic 节点：规则校验方案是否覆盖所有硬约束（低卡/亲子等）。"""
from __future__ import annotations

from backend.agents.planner import (
    _HEAVY_FOOD_KEYS,
    _KIDS_KEYS,
    _LOW_CAL_KEYS,
    _candidate_text,
    _explicit_cuisines,
    _matches_cuisine,
    _wants_light_meal,
    merge_targeted_addon,
)
from backend.roles import trace_line
from backend.schemas import CriticFeedback, CriticIssue
from backend.state import AgentState


def critic_node(state: AgentState) -> dict:
    profile = state.get("group_profile")
    plan = state.get("plan")
    issues: list[CriticIssue] = []
    plan_updates: dict = {}

    targeted = state.get("targeted_research_result")

    if profile and plan:
        merged = merge_targeted_addon(plan, profile, targeted)
        if merged is not plan:
            plan = merged
            plan_updates["plan"] = merged

        alts = list(state.get("plan_alternatives") or [])
        if alts:
            new_alts: list = []
            alt_changed = False
            for alt in alts:
                merged_alt = merge_targeted_addon(alt, profile, targeted)
                if merged_alt is not alt:
                    alt_changed = True
                new_alts.append(merged_alt)
            if alt_changed:
                plan_updates["plan_alternatives"] = new_alts

        eats = [s for s in plan.stages if s.name == "吃"]
        plays = [s for s in plan.stages if s.name == "玩"]

        # 1. 轻食/低卡硬红线
        if _wants_light_meal(profile) and eats:
            eat = eats[0].primary
            text = _candidate_text(eat)
            if any(k.lower() in text for k in _HEAVY_FOOD_KEYS):
                issues.append(
                    CriticIssue(
                        severity="block",
                        field="stages[吃].primary",
                        message="轻食/低卡约束未满足：不可推荐烤肉/火锅等重口味",
                    )
                )
            elif not any(k.lower() in text for k in _LOW_CAL_KEYS):
                issues.append(
                    CriticIssue(
                        severity="block",
                        field="stages[吃].primary",
                        message="轻食/低卡约束未满足：餐厅须含轻食/沙拉/低卡标签",
                    )
                )

        # 2. 显式菜系硬红线（非轻食路径）
        cuisines = _explicit_cuisines(profile)
        if cuisines and eats and not _wants_light_meal(profile):
            eat = eats[0].primary
            if not _matches_cuisine(eat, cuisines):
                issues.append(
                    CriticIssue(
                        severity="block",
                        field="stages[吃].primary",
                        message=f"菜系约束未满足：须匹配 {sorted(cuisines)}",
                    )
                )

        # 3. 亲子硬红线：有孩子或亲子兴趣时，玩阶段须亲子友好
        needs_kids = bool(profile.kids_ages) or "亲子" in profile.interests
        if profile.scene == "family" and needs_kids and plays:
            play = plays[0].primary
            text = _candidate_text(play)
            if not any(k.lower() in text for k in _KIDS_KEYS):
                issues.append(
                    CriticIssue(
                        severity="block",
                        field="stages[玩].primary",
                        message="家庭场景下未给出亲子友好活动",
                    )
                )

        # 4. 阶段完整性
        if len(plan.stages) < 2:
            issues.append(
                CriticIssue(
                    severity="block",
                    field="stages",
                    message="方案阶段过少（至少应包含 玩 + 吃）",
                )
            )

    approved = not any(i.severity == "block" for i in issues)
    feedback = CriticFeedback(approved=approved, issues=issues)

    trace_msgs = [
        trace_line(
            "Critic",
            f"approved={approved} issues={len(issues)} "
            + ("✓" if approved else "✗ 触发重规划"),
            phase="校验",
        )
    ]
    plans_with_addons = [plan] if plan and plan.addons else []
    for alt in plan_updates.get("plan_alternatives") or state.get("plan_alternatives") or []:
        if alt.addons:
            plans_with_addons.append(alt)
    if plans_with_addons:
        trace_msgs.append(
            trace_line(
                "Critic",
                f"HIL附加项已为 {len(plans_with_addons)} 套方案生成（按各店 POI 绑定送达点）",
                phase="校验",
            )
        )
        for idx, p in enumerate(plans_with_addons):
            for addon in p.addons:
                trace_msgs.append(
                    trace_line(
                        "Critic",
                        f"  方案#{idx + 1} [{addon.type}] {addon.description} "
                        f"→ target_poi_id={addon.target_poi_id}",
                        phase="校验",
                    )
                )

    return {
        **plan_updates,
        "critic_feedback": feedback,
        "trace": trace_msgs,
    }
