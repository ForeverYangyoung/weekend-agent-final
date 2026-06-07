"""Plan patcher: apply revise feedback on current plan.

MVP strategy:
- Keep it deterministic and explainable (no hidden LLM rewrite).
- Replace stage primary with the first compatible backup when user asks to "换".
- Respect locked stages from frontend.
- Keep addon selection in `selected_addon_ids`.
"""
from __future__ import annotations

from dataclasses import dataclass

from backend.agents.planner import _passes_hard_filter, attach_hil_addons
from backend.revise_utils import brand_key, tried_brand_keys
from backend.schemas import GroupProfile
from backend.nodes.dry_run import dry_run_node
from backend.roles import trace_line
from backend.schemas import POICandidate, Plan, PlanStage, ResearchResult, ToolStatus
from backend.state import AgentState


@dataclass
class ReviseEvent:
    event_type: str
    summary: str


def _stage_key(stage_name: str) -> str:
    return stage_name.split("(")[0].strip()


def _tried_poi_ids(state: AgentState | None, stage_name: str) -> set[str]:
    """从微调历史快照收集该阶段已出现过的 POI，避免「换活动」立刻换回上一家。"""
    tried: set[str] = set()
    if state is None:
        return tried
    for snap in state.get("plan_snapshots") or []:
        if not isinstance(snap, dict):
            continue
        for s in snap.get("stages") or []:
            if s.get("name") != stage_name:
                continue
            pid = (s.get("primary") or {}).get("poi_id")
            if pid:
                tried.add(str(pid))
    return tried


def _candidate_pool(
    stage: PlanStage,
    research: ResearchResult | None,
) -> list[POICandidate]:
    pool: list[POICandidate] = []
    seen: set[str] = set()
    key = stage.name
    if research is not None:
        for rs in research.stages:
            if _stage_key(rs.stage_name) != key:
                continue
            for cand in rs.candidates:
                if cand.poi_id in seen:
                    continue
                pool.append(cand)
                seen.add(cand.poi_id)
    for cand in stage.backups:
        if cand.poi_id in seen:
            continue
        pool.append(cand)
        seen.add(cand.poi_id)
    return pool


def _next_candidate(
    stage: PlanStage,
    research: ResearchResult | None,
    *,
    state: AgentState | None = None,
    respect_tried: bool = True,
    profile: GroupProfile | None = None,
) -> POICandidate | None:
    current_id = stage.primary.poi_id
    tried: set[str] = set()
    if respect_tried:
        tried = _tried_poi_ids(state, stage.name)
        tried.add(current_id)
    else:
        tried = {current_id}
    blocked = _revise_blocked_poi_ids(state)
    rejected_brands: set[str] = set()
    if respect_tried and state is not None:
        rejected_brands = tried_brand_keys(state, stage.name)
        rejected_brands.add(brand_key(stage.primary.name))
    for cand in _candidate_pool(stage, research):
        if cand.poi_id in tried or cand.poi_id in blocked:
            continue
        if rejected_brands and brand_key(cand.name) in rejected_brands:
            continue
        if profile is not None and not _passes_hard_filter(cand, stage.name, profile):
            continue
        return cand
    return None


def _replace_stage_primary(
    stage: PlanStage,
    research: ResearchResult | None,
    *,
    state: AgentState | None = None,
    respect_tried: bool = True,
    profile: GroupProfile | None = None,
) -> PlanStage | None:
    nxt = _next_candidate(
        stage, research, state=state, respect_tried=respect_tried, profile=profile
    )
    if nxt is None:
        return None
    remain = [c for c in _candidate_pool(stage, research) if c.poi_id != nxt.poi_id]
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


def _blocked_poi_ids(state: AgentState) -> set[str]:
    blocked: set[str] = set()
    for call in state.get("dry_run_calls", []) or []:
        if call.status == ToolStatus.FAILED:
            pid = (call.args or {}).get("poi_id")
            if pid:
                blocked.add(str(pid))
    for call in state.get("failed_calls", []) or []:
        pid = (call.args or {}).get("poi_id")
        if pid:
            blocked.add(str(pid))
    return blocked


def _revise_blocked_poi_ids(state: AgentState | None) -> set[str]:
    """微调换店须跳过预检失败 + 满座拉黑商户，避免反复旋回川一哥等。"""
    blocked = _blocked_poi_ids(state) if state is not None else set()
    if state is not None:
        from backend.constraints_util import blocked_poi_ids as anomaly_blocked

        blocked |= anomaly_blocked(state.get("anomaly_encountered"))
    return blocked


def _critic_blocked_stages(state: AgentState) -> set[str]:
    fb = state.get("critic_feedback")
    if fb is None or fb.approved:
        return set()
    stages: set[str] = set()
    for issue in fb.issues:
        if issue.severity != "block":
            continue
        field = issue.field or ""
        if "玩" in field:
            stages.add("玩")
        if "吃" in field:
            stages.add("吃")
    return stages


def _auto_patch_blocked_stages(
    plan: Plan,
    research: ResearchResult | None,
    *,
    state: AgentState,
    blocked_pois: set[str],
    critic_stages: set[str],
    locked: set[str],
    profile: GroupProfile | None = None,
) -> tuple[Plan, list[ReviseEvent]]:
    events: list[ReviseEvent] = []
    updated = plan.model_copy(deep=True)
    stage_by_name = {s.name: s for s in updated.stages}

    for name, stage in list(stage_by_name.items()):
        if name in locked:
            continue
        should_swap = stage.primary.poi_id in blocked_pois or name in critic_stages
        if not should_swap:
            continue
        next_stage = _replace_stage_primary(
            stage,
            research,
            state=state,
            respect_tried=False,
            profile=state.get("group_profile"),
        )
        if next_stage is None:
            reason = "预检满座" if stage.primary.poi_id in blocked_pois else "审计未通过"
            events.append(
                ReviseEvent("stage_locked", f"{name}阶段无可用备选（{reason}）")
            )
            continue
        old = stage.primary.name
        new = next_stage.primary.name
        stage_by_name[name] = next_stage
        events.append(ReviseEvent("stage_replaced", f"{name}由「{old}」改为「{new}」"))

    updated.stages = [stage_by_name.get(s.name, s) for s in updated.stages]
    return updated, events


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

    locked = _normalize_locked(list(locked_raw))
    events: list[ReviseEvent] = []
    updated = plan.model_copy(deep=True)
    research = state.get("research_result")
    profile = state.get("group_profile")
    targeted = state.get("targeted_research_result")
    blocked_pois = _revise_blocked_poi_ids(state)
    critic_stages = _critic_blocked_stages(state)
    retry_loop = bool(blocked_pois or critic_stages)
    iteration = state.get("plan_iteration", 0)
    revise_pass = int(state.get("revise_pass") or 0) + 1
    # 仅图内第 2+ 轮（预检失败回退）跳过用户反馈；新的 /revise 请求从 revise_pass=0 开始
    apply_user_feedback = bool(feedback) and revise_pass == 1

    stage_by_name = {s.name: s for s in updated.stages}

    if apply_user_feedback:
        want_food = _contains_any(
            feedback, ("餐厅", "吃", "日料", "火锅", "烤肉", "川菜", "轻食")
        )
        want_play = _contains_any(
            feedback, ("活动", "玩", "公园", "展览", "剧本杀", "户外")
        )

        if want_food and "吃" not in locked and "吃" in stage_by_name:
            next_stage = _replace_stage_primary(
                stage_by_name["吃"], research, state=state, profile=profile
            )
            if next_stage is not None:
                old = stage_by_name["吃"].primary.name
                new = next_stage.primary.name
                stage_by_name["吃"] = next_stage
                events.append(ReviseEvent("stage_replaced", f"餐厅由「{old}」改为「{new}」"))
            else:
                events.append(ReviseEvent("stage_locked", "餐厅无可用备选，保持不变"))

        if want_play and "玩" not in locked and "玩" in stage_by_name:
            next_stage = _replace_stage_primary(
                stage_by_name["玩"], research, state=state, profile=profile
            )
            if next_stage is not None:
                old = stage_by_name["玩"].primary.name
                new = next_stage.primary.name
                stage_by_name["玩"] = next_stage
                events.append(ReviseEvent("stage_replaced", f"活动由「{old}」改为「{new}」"))
            else:
                events.append(ReviseEvent("stage_locked", "活动无可用备选，保持不变"))

        updated.stages = [stage_by_name.get(s.name, s) for s in updated.stages]

    if retry_loop:
        updated, auto_events = _auto_patch_blocked_stages(
            updated,
            research,
            state=state,
            blocked_pois=blocked_pois,
            critic_stages=critic_stages,
            locked=locked,
            profile=profile,
        )
        events.extend(auto_events)

    if profile is not None:
        updated = attach_hil_addons(updated, profile, targeted)
    if feedback and any(e.event_type == "stage_replaced" for e in events):
        updated = updated.model_copy(
            update={
                "is_compromised": False,
                "compromise_message": "",
                "compromise_source": "",
            }
        )
    if feedback:
        selected_addon_ids = _rewrite_addon_selection(feedback, updated, selected_addon_ids)

    if not events:
        return {
            "selected_addon_ids": selected_addon_ids,
            "trace": [trace_line("Revise", "空反馈：保持原方案", phase="微调")],
            "revise_events": [],
        }

    replaced = any(e.event_type == "stage_replaced" for e in events)
    if profile is not None and (replaced or retry_loop):
        from backend.revise_utils import finalize_plan_metadata

        updated = finalize_plan_metadata(updated, profile)
    locked_out = any(e.event_type == "stage_locked" for e in events)
    patch_exhausted = retry_loop and not replaced and locked_out
    new_iteration = iteration + 1 if (apply_user_feedback or retry_loop or replaced) else iteration

    trace_head = (
        trace_line("Revise", f"应用反馈：{feedback}", phase="微调")
        if feedback
        else trace_line("Revise", "这家店订不到了，正在换一家备选", phase="微调")
    )
    trace_events = [f"{e.event_type}: {e.summary}" for e in events]

    result: dict = {
        "plan": updated,
        "selected_addon_ids": selected_addon_ids,
        "plan_iteration": new_iteration,
        "revise_pass": revise_pass,
        "patch_exhausted": patch_exhausted,
        "executed_calls": [],
        "failed_calls": [],
        "revise_events": [{"event_type": e.event_type, "summary": e.summary} for e in events],
        "trace": [trace_head, *[trace_line("Revise", msg, phase="微调") for msg in trace_events]],
    }

    if patch_exhausted:
        result["trace"].append(
            trace_line(
                "Revise",
                "附近暂无更多备选，停止自动换店",
                phase="微调",
            )
        )

    if replaced:
        result["patch_exhausted"] = False
        dry_patch = dry_run_node({**state, **result})
        result["dry_run_calls"] = dry_patch.get("dry_run_calls", [])
        result["trace"].extend(dry_patch.get("trace") or [])

    return result

