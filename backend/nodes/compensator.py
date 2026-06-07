"""Compensator：三类故障自愈（满座/无票/时间冲突）+ 场景手术，再回预检/下单。"""
from __future__ import annotations

from backend.compensator_scoring import compensator_score, pick_best_alternative
from backend.failure_detect import classify_dry_run_failures
from backend.roles import trace_line
from backend.schemas import FailureType, Plan, PlanStage, ToolStatus
from backend.state import AgentState
from backend.timeline_utils import execute_time_compression, plan_to_timeline
from backend.tools import ToolContext, ToolError, invoke


def _is_full_seat_failure(call) -> bool:
    from backend.failure_detect import classify_call_failure

    return classify_call_failure(call) == FailureType.NO_SEAT


def _failed_seat_calls(state: AgentState) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    for bucket in (state.get("dry_run_calls") or [], state.get("failed_calls") or []):
        for call in bucket:
            if not _is_full_seat_failure(call):
                continue
            pid = (call.args or {}).get("poi_id") or ""
            if pid:
                hits.append((call.stage_name or "吃", str(pid)))
    return hits


def _failed_ticket_calls(state: AgentState) -> list[tuple[str, str]]:
    from backend.failure_detect import classify_call_failure

    hits: list[tuple[str, str]] = []
    for bucket in (state.get("dry_run_calls") or [], state.get("failed_calls") or []):
        for call in bucket:
            if classify_call_failure(call) != FailureType.NO_TICKET:
                continue
            pid = (call.args or {}).get("poi_id") or ""
            if pid:
                hits.append((call.stage_name or "玩", str(pid)))
    return hits


def _candidates_for_stage(state: AgentState, stage_name: str) -> list:
    research = state.get("research_result")
    if research is None:
        return []
    for stage in research.stages:
        key = stage.stage_name.split("(")[0].strip()
        if key == stage_name:
            return list(stage.candidates)
    return []


def _reserved_eat_pois(state: AgentState) -> set[str]:
    reserved: set[str] = set()
    for alt in state.get("plan_alternatives") or []:
        for s in alt.stages:
            if s.name == "吃":
                reserved.add(s.primary.poi_id)
    return reserved


def _rebind_addons(plan: Plan, state: AgentState) -> Plan:
    from backend.agents.planner import attach_hil_addons

    profile = state.get("group_profile")
    targeted = state.get("targeted_research_result")
    if profile is None:
        return plan
    return attach_hil_addons(plan, profile, targeted)


def _patch_plan_stage(
    plan: Plan,
    stage_name: str,
    new_primary,
    *,
    old_name: str,
    msg_prefix: str,
) -> Plan:
    stages: list[PlanStage] = []
    for s in plan.stages:
        if s.name != stage_name:
            stages.append(s)
            continue
        backups = [b for b in s.backups if b.poi_id != new_primary.poi_id]
        backups = [s.primary, *backups]
        stages.append(
            s.model_copy(
                update={
                    "primary": new_primary,
                    "backups": backups[:5],
                    "notes": new_primary.reason or s.notes,
                }
            )
        )
    short_new = new_primary.name.split("（")[0].strip()
    short_old = old_name.split("（")[0].strip()
    msg = f"⚠️ {msg_prefix}「{short_old}」→「{short_new}」"
    return plan.model_copy(
        update={
            "stages": stages,
            "is_compromised": True,
            "compromise_message": msg,
            "compromise_source": "recovery",
        }
    )


def execute_poi_substitution(state: AgentState) -> dict:
    """NO_SEAT：公式选替补，原地换店。"""
    plan = state.get("plan")
    profile = state.get("group_profile")
    failures = _failed_seat_calls(state)
    if plan is None or not failures:
        return {"require_human_interrupt": True}

    updated = plan.model_copy(deep=True)
    traces: list[str] = []
    patched = False

    for stage_name, failed_pid in failures:
        stage = next((s for s in updated.stages if s.name == stage_name), None)
        if stage is None or stage.primary.poi_id != failed_pid:
            continue
        pool = _candidates_for_stage(state, stage_name)
        exclude = _reserved_eat_pois(state) if stage_name == "吃" else set()
        best = pick_best_alternative(
            pool,
            failed_poi_id=failed_pid,
            plan=updated,
            stage_name=stage_name,
            profile=profile,
            exclude_poi_ids=exclude,
        )
        if best is None:
            return {
                "require_human_interrupt": True,
                "trace": [
                    trace_line(
                        "Executor",
                        f"场景手术失败：{stage_name}阶段无可用替代商户",
                        phase="恢复",
                    )
                ],
            }
        anchor = float(
            next(
                (s.primary.metadata.get("distance_km", 0) for s in updated.stages if s.name == "玩"),
                0,
            )
            or 0
        )
        sc = compensator_score(best, anchor_km=anchor, profile=profile)
        old_name = stage.primary.name
        updated = _patch_plan_stage(
            updated,
            stage_name,
            best,
            old_name=old_name,
            msg_prefix="满座，已自动改订",
        )
        patched = True
        traces.append(
            trace_line(
                "Executor",
                f"NO_SEAT·{stage_name}｜{old_name} → {best.name}｜Score={sc:.2f}",
                phase="恢复",
            )
        )

    if not patched:
        return {"require_human_interrupt": True}

    from backend.agents.planner import _plan_score_math

    updated = _rebind_addons(updated, state)
    updated.score = _plan_score_math(updated)
    retry = (
        "dry_run"
        if any(c.status == ToolStatus.FAILED for c in (state.get("dry_run_calls") or []))
        else "executor"
    )
    return {
        "plan": updated,
        "timeline": plan_to_timeline(updated, profile),
        "dry_run_calls": [],
        "require_human_interrupt": False,
        "last_exception_code": None,
        "current_failure_type": None,
        "compensator_retry": retry,
        "plan_iteration": state.get("plan_iteration", 0) + 1,
        "trace": traces,
    }


def execute_ticket_fallback(state: AgentState) -> dict:
    """NO_TICKET：活动售罄时换同阶段备选 POI。"""
    plan = state.get("plan")
    profile = state.get("group_profile")
    failures = _failed_ticket_calls(state)
    if plan is None or not failures:
        return {"require_human_interrupt": True}

    updated = plan.model_copy(deep=True)
    traces: list[str] = []
    patched = False

    for stage_name, failed_pid in failures:
        stage = next((s for s in updated.stages if s.name == stage_name), None)
        if stage is None or stage.primary.poi_id != failed_pid:
            continue
        pool = [c for c in _candidates_for_stage(state, stage_name) if c.poi_id != failed_pid]
        if not pool and stage.backups:
            pool = [b for b in stage.backups if b.poi_id != failed_pid]
        if not pool:
            return {
                "require_human_interrupt": True,
                "trace": [
                    trace_line(
                        "Executor",
                        f"NO_TICKET：{stage_name}阶段无票且无备选活动",
                        phase="恢复",
                    )
                ],
            }
        best = pool[0]
        old_name = stage.primary.name
        updated = _patch_plan_stage(
            updated,
            stage_name,
            best,
            old_name=old_name,
            msg_prefix="无票，已换备选",
        )
        patched = True
        traces.append(
            trace_line(
                "Executor",
                f"NO_TICKET·{stage_name}｜{old_name} → {best.name}",
                phase="恢复",
            )
        )

    if not patched:
        return {"require_human_interrupt": True}

    from backend.agents.planner import _plan_score_math

    updated.score = _plan_score_math(updated)
    return {
        "plan": updated,
        "timeline": plan_to_timeline(updated, profile),
        "dry_run_calls": [],
        "require_human_interrupt": False,
        "current_failure_type": None,
        "compensator_retry": "dry_run",
        "plan_iteration": state.get("plan_iteration", 0) + 1,
        "trace": traces,
    }


def _resolve_failure_type(state: AgentState) -> FailureType | None:
    explicit = state.get("current_failure_type")
    if explicit is not None:
        return explicit
    plan = state.get("plan")
    profile = state.get("group_profile")
    calls = state.get("dry_run_calls") or []
    return classify_dry_run_failures(calls, plan=plan, profile=profile)


def compensator_node(state: AgentState) -> dict:
    failure = _resolve_failure_type(state)

    if failure == FailureType.CONFLICT:
        out = execute_time_compression(state)
        if not out.get("require_human_interrupt"):
            return out
        return out

    if failure == FailureType.NO_TICKET:
        out = execute_ticket_fallback(state)
        if out.get("plan") and not out.get("require_human_interrupt"):
            return out

    if failure == FailureType.NO_SEAT or _failed_seat_calls(state):
        out = execute_poi_substitution(state)
        if out.get("plan") and not out.get("require_human_interrupt"):
            return out
        if out.get("require_human_interrupt"):
            return out

    # 执行阶段回滚 + 再尝试换店
    executed = state.get("executed_calls", []) or []
    failed = state.get("failed_calls", []) or []
    rolled_back = 0
    rollback_errors: list[str] = []
    ctx = ToolContext()

    for call in executed:
        if call.status != ToolStatus.OK or not call.result:
            continue
        order_id = call.result.get("order_id")
        if not order_id:
            continue
        try:
            invoke("cancel_order", {"order_id": order_id}, ctx=ctx, stage_name=call.stage_name)
            call.status = ToolStatus.ROLLED_BACK
            rolled_back += 1
        except ToolError as e:
            rollback_errors.append(f"{order_id}:{e.message}")

    out = execute_poi_substitution(state)
    rollback_trace = trace_line(
        "Executor",
        f"回滚 {rolled_back} 笔成功订单 ↩，失败原因: "
        + "; ".join(f.error or "?" for f in failed)
        + ("；回滚异常: " + ", ".join(rollback_errors) if rollback_errors else ""),
        phase="回滚",
    )
    if out.get("plan") and not out.get("require_human_interrupt"):
        out["trace"] = [rollback_trace, *out.get("trace", [])]
        out["executed_calls"] = []
        out["failed_calls"] = failed
        out["force_failure"] = None
        return out

    return {
        "executed_calls": [],
        "dry_run_calls": [],
        "failed_calls": failed,
        "force_failure": None,
        "require_human_interrupt": out.get("require_human_interrupt", True),
        "plan_iteration": state.get("plan_iteration", 0) + 1,
        "trace": [rollback_trace, *out.get("trace", [])],
    }
