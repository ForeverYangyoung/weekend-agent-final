"""微调：品牌级排除、方案元数据刷新、备选重生。"""
from __future__ import annotations

from backend.agents.planner import (
    _estimate_cost,
    _plan_score_math,
    _summary,
    attach_hil_addons,
    build_plans,
)
from backend.constraints_util import blocked_poi_ids
from backend.schemas import Plan, ResearchResult
from backend.state import AgentState


def brand_key(name: str) -> str:
    """同一连锁不同门店共享品牌键（如 Wagas 奥森 / 万柳 → wagas）。"""
    short = name.split("（")[0].strip()
    lower = short.lower()
    if "wagas" in lower:
        return "wagas"
    if "禾绿" in short:
        return "禾绿"
    if "海底捞" in short:
        return "海底捞"
    if "绿茶" in short:
        return "绿茶"
    head = short.split()[0] if short.split() else short
    return head or short


def tried_brand_keys(state: AgentState | None, stage_name: str) -> set[str]:
    keys: set[str] = set()
    if state is None:
        return keys
    for snap in state.get("plan_snapshots") or []:
        if not isinstance(snap, dict):
            continue
        for s in snap.get("stages") or []:
            if s.get("name") != stage_name:
                continue
            pname = str((s.get("primary") or {}).get("name") or "")
            if pname:
                keys.add(brand_key(pname))
    return keys


def expand_brand_blocks(
    research: ResearchResult,
    stage_name: str,
    brands: set[str],
) -> set[str]:
    blocked: set[str] = set()
    if not brands:
        return blocked
    for stage in research.stages:
        key = stage.stage_name.split("(")[0].strip()
        if key != stage_name:
            continue
        for cand in stage.candidates:
            if brand_key(cand.name) in brands:
                blocked.add(cand.poi_id)
    return blocked


def collect_revise_exclusions(state: AgentState) -> set[str]:
    blocked = blocked_poi_ids(state.get("anomaly_encountered"))
    from backend.nodes.plan_patcher import _revise_blocked_poi_ids

    blocked |= _revise_blocked_poi_ids(state)
    research = state.get("research_result")
    if research is not None:
        blocked |= expand_brand_blocks(
            research, "吃", tried_brand_keys(state, "吃")
        )
    return blocked


def _plan_poi_sig(plan: Plan) -> tuple[str, str]:
    play = next((s for s in plan.stages if s.name == "玩"), None)
    eat = next((s for s in plan.stages if s.name == "吃"), None)
    return (
        play.primary.poi_id if play else "",
        eat.primary.poi_id if eat else "",
    )


def finalize_plan_metadata(plan: Plan, profile) -> Plan:
    if profile is None:
        return plan
    order_label = plan.order_label or " → ".join(s.name for s in plan.stages)
    return plan.model_copy(
        update={
            "total_cost_estimate": _estimate_cost(profile.people_count, plan.stages),
            "summary": _summary(profile.scene, plan.stages, order_label),
            "score": _plan_score_math(plan),
        }
    )


def refresh_revised_plan_bundle(state: AgentState) -> dict:
    """微调后：重算主方案价格/标题，并从 research 重生差异化备选。"""
    plan = state.get("plan")
    profile = state.get("group_profile")
    research = state.get("research_result")
    targeted = state.get("targeted_research_result")
    if plan is None or profile is None or research is None:
        return {}

    plan = finalize_plan_metadata(plan, profile)
    plan = attach_hil_addons(plan, profile, targeted)

    blocked = collect_revise_exclusions(state)
    built = build_plans(profile, research, blocked, top_k=4)
    primary_sig = _plan_poi_sig(plan)

    alternatives: list[Plan] = []
    seen_sigs: set[tuple[str, str]] = {primary_sig}
    for candidate in built:
        sig = _plan_poi_sig(candidate)
        if sig in seen_sigs:
            continue
        seen_sigs.add(sig)
        alt = finalize_plan_metadata(candidate, profile)
        alt = attach_hil_addons(alt, profile, targeted)
        alternatives.append(alt)
        if len(alternatives) >= 2:
            break

    return {"plan": plan, "plan_alternatives": alternatives[:2]}
