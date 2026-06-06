"""Plan patcher: apply revise feedback on current plan.

MVP strategy:
- Keep it deterministic and explainable (no hidden LLM rewrite).
- Replace stage primary with the first compatible backup when user asks to "换".
- Respect locked stages from frontend.
- Keep addon selection in `selected_addon_ids`.
"""
from __future__ import annotations

from dataclasses import dataclass

from backend.agents.planner import attach_hil_addons
from backend.roles import trace_line
from backend.schemas import POICandidate, Plan, PlanStage, ResearchResult
from backend.state import AgentState


@dataclass
class ReviseEvent:
    event_type: str
    summary: str


def _next_candidate(
    stage: PlanStage,
    research: ResearchResult | None,
) -> POICandidate | None:
    current_id = stage.primary.poi_id
    for cand in stage.backups:
        if cand.poi_id != current_id:
            return cand
    if research is None:
        return None
    for rs in research.stages:
        if rs.stage_name != stage.name:
            continue
        for cand in rs.candidates:
            if cand.poi_id != current_id:
                return cand
    return None


def _replace_stage_primary(
    stage: PlanStage,
    research: ResearchResult | None,
) -> PlanStage | None:
    nxt = _next_candidate(stage, research)
    if nxt is None:
        return None
    remain = [b for b in stage.backups if b.poi_id != nxt.poi_id]
    if research is not None:
        for rs in research.stages:
            if rs.stage_name == stage.name:
                for cand in rs.candidates:
                    if cand.poi_id not in {nxt.poi_id, stage.primary.poi_id}:
                        remain.append(cand)
                break
    return stage.model_copy(
        update={
            "primary": nxt,
            "backups": remain,
            "notes": nxt.reason or stage.notes,
        }
    )


def _contains_any(text: str, keys: tuple[str, ...]) -> bool:
    return any(k in text for k in keys)


def _normalize_locked(locked: list[str]) -> set[str]:
    mapped: set[str] = set()
    for item in locked:
        if item == "food":
            mapped.add("吃")
        elif item == "play":
            mapped.add("玩")
        elif item == "addon":
            mapped.add("加餐")
        else:
            mapped.add(item)
    return mapped


def _rewrite_addon_selection(
    feedback: str,
    plan: Plan,
    selected_addon_ids: list[str],
) -> list[str]:
    all_ids = [a.addon_id for a in plan.addons]
    selected = set(selected_addon_ids or all_ids)
    if _contains_any(feedback, ("不要加餐", "取消加餐", "不需要奶茶", "不需要鲜花")):
        return []
    if _contains_any(feedback, ("来杯奶茶", "买奶茶", "饮品", "果茶")):
        for a in plan.addons:
            if "refresh" in a.type or "奶" in a.description or "茶" in a.description:
                selected.add(a.addon_id)
    if _contains_any(feedback, ("鲜花", "花束", "surprise", "惊喜")):
        for a in plan.addons:
            if "surprise" in a.type or "花" in a.description:
                selected.add(a.addon_id)
    return [i for i in all_ids if i in selected]


def plan_patcher_node(state: AgentState) -> dict:
    plan = state.get("plan")
    feedback = str(state.get("revise_feedback") or "").strip()
    locked_raw = state.get("revise_locked_stages") or []
    selected_addon_ids = list(state.get("selected_addon_ids") or [])

    if not plan:
        return {
            "trace": [trace_line("Revise", "跳过：无可修改方案", phase="微调")],
            "revise_events": [],
        }

    if not feedback:
        return {
            "selected_addon_ids": selected_addon_ids,
            "trace": [trace_line("Revise", "空反馈：保持原方案", phase="微调")],
            "revise_events": [],
        }

    locked = _normalize_locked(list(locked_raw))
    events: list[ReviseEvent] = []
    updated = plan.model_copy(deep=True)
    research = state.get("research_result")
    profile = state.get("group_profile")
    targeted = state.get("targeted_research_result")

    stage_by_name = {s.name: s for s in updated.stages}
    want_food = _contains_any(feedback, ("餐厅", "吃", "日料", "火锅", "烤肉", "川菜", "轻食"))
    want_play = _contains_any(feedback, ("活动", "玩", "公园", "展览", "剧本杀", "户外"))

    if want_food and "吃" not in locked and "吃" in stage_by_name:
        next_stage = _replace_stage_primary(stage_by_name["吃"], research)
        if next_stage is not None:
            old = stage_by_name["吃"].primary.name
            new = next_stage.primary.name
            stage_by_name["吃"] = next_stage
            events.append(ReviseEvent("stage_replaced", f"餐厅由「{old}」改为「{new}」"))
        else:
            events.append(ReviseEvent("stage_locked", "餐厅无可用备选，保持不变"))

    if want_play and "玩" not in locked and "玩" in stage_by_name:
        next_stage = _replace_stage_primary(stage_by_name["玩"], research)
        if next_stage is not None:
            old = stage_by_name["玩"].primary.name
            new = next_stage.primary.name
            stage_by_name["玩"] = next_stage
            events.append(ReviseEvent("stage_replaced", f"活动由「{old}」改为「{new}」"))
        else:
            events.append(ReviseEvent("stage_locked", "活动无可用备选，保持不变"))

    updated.stages = [stage_by_name.get(s.name, s) for s in updated.stages]
    if profile is not None:
        updated = attach_hil_addons(updated, profile, targeted)
    selected_addon_ids = _rewrite_addon_selection(feedback, updated, selected_addon_ids)

    if not events:
        events.append(ReviseEvent("plan_created", "已记录微调偏好，方案保持不变"))

    trace_events = [f"{e.event_type}: {e.summary}" for e in events]
    return {
        "plan": updated,
        "selected_addon_ids": selected_addon_ids,
        "revise_events": [{"event_type": e.event_type, "summary": e.summary} for e in events],
        "trace": [
            trace_line("Revise", f"应用反馈：{feedback}", phase="微调"),
            *[trace_line("Revise", msg, phase="微调") for msg in trace_events],
        ],
    }

