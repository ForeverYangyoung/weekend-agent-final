"""时间轴：Plan ↔ Timeline 互转，冲突检测与动态压缩。"""
from __future__ import annotations

from backend.schemas import FailureType, GroupProfile, Plan, PlanStage, TimelineEvent

_MIN_EVENT_MINUTES = 30
_DEFAULT_WINDOW_MINUTES = 480
_TRANSIT_MINUTES = 30


def _time_to_minutes(t: str) -> int:
    h, m = (int(x) for x in t.split(":", 1))
    return h * 60 + m


def _minutes_to_time(total: int) -> str:
    total = total % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def _stage_duration_minutes(stage: PlanStage) -> int:
    return max(_MIN_EVENT_MINUTES, _time_to_minutes(stage.end_time) - _time_to_minutes(stage.start_time))


def _is_core_stage(stage_name: str, profile: GroupProfile | None) -> bool:
    if stage_name == "吃":
        return True
    if profile and profile.scene == "family" and stage_name == "玩":
        return True
    return False


def plan_to_timeline(plan: Plan, profile: GroupProfile | None = None) -> list[TimelineEvent]:
    events: list[TimelineEvent] = []
    for stage in plan.stages:
        if stage.name == "通勤":
            continue
        core = _is_core_stage(stage.name, profile)
        dur = _stage_duration_minutes(stage)
        events.append(
            TimelineEvent(
                stage_name=stage.name,
                poi_id=stage.primary.poi_id,
                name=stage.primary.name,
                start_time=stage.start_time,
                end_time=stage.end_time,
                duration_minutes=dur,
                is_core_constraint=core,
                weight=3.0 if core else 1.0,
            )
        )
    return events


def _travel_minutes(plan: Plan) -> int:
    commute = sum(_stage_duration_minutes(s) for s in plan.stages if s.name == "通勤")
    if commute:
        return commute
    main = [s for s in plan.stages if s.name in ("玩", "吃")]
    return max(0, len(main) - 1) * _TRANSIT_MINUTES


def _window_minutes(profile: GroupProfile | None) -> int:
    if profile and profile.duration_hours:
        return max(_MIN_EVENT_MINUTES, int(profile.duration_hours * 60))
    return _DEFAULT_WINDOW_MINUTES


def detect_schedule_conflict(plan: Plan, profile: GroupProfile | None = None) -> bool:
    """活动时间 + 通勤超出窗口，或阶段时间重叠。"""
    events = plan_to_timeline(plan, profile)
    if not events:
        return False

    ordered = sorted(events, key=lambda e: _time_to_minutes(e.start_time))
    for i in range(len(ordered) - 1):
        if _time_to_minutes(ordered[i].end_time) > _time_to_minutes(ordered[i + 1].start_time):
            return True

    activity_mins = sum(e.duration_minutes for e in events)
    travel = _travel_minutes(plan)
    return activity_mins + travel > _window_minutes(profile)


def compress_timeline_greedy(
    events: list[TimelineEvent],
    *,
    total_allowed_minutes: int,
    travel_minutes: int,
) -> list[TimelineEvent]:
    """贪心版 min Σ w_i(T_i-T'_i)²：先压非核心，每段最少 30min。"""
    actual = sum(e.duration_minutes for e in events) + travel_minutes
    overflow = actual - total_allowed_minutes
    if overflow <= 0:
        return events

    mutable = [e.model_copy(deep=True) for e in events]
    # 非核心、权重低者优先压缩
    order = sorted(
        range(len(mutable)),
        key=lambda i: (mutable[i].is_core_constraint, mutable[i].weight),
    )
    for idx in order:
        if overflow <= 0:
            break
        ev = mutable[idx]
        if ev.is_core_constraint:
            continue
        reducible = ev.duration_minutes - _MIN_EVENT_MINUTES
        if reducible <= 0:
            continue
        cut = min(reducible, overflow)
        ev.duration_minutes -= cut
        ev.end_time = _minutes_to_time(_time_to_minutes(ev.start_time) + ev.duration_minutes)
        overflow -= cut

    return mutable


def apply_timeline_to_plan(plan: Plan, events: list[TimelineEvent]) -> Plan:
    by_stage = {e.stage_name: e for e in events}
    stages: list[PlanStage] = []
    for stage in plan.stages:
        if stage.name not in by_stage:
            stages.append(stage)
            continue
        ev = by_stage[stage.name]
        stages.append(
            stage.model_copy(
                update={
                    "start_time": ev.start_time,
                    "end_time": ev.end_time,
                }
            )
        )
    total_hours = sum(e.duration_minutes for e in events) / 60.0
    return plan.model_copy(
        update={
            "stages": stages,
            "total_duration_hours": round(total_hours, 1),
            "is_compromised": True,
            "compromise_message": "行程超时，已自动压缩非核心活动时长（动态时间分配）",
            "compromise_source": "recovery",
        }
    )


def execute_time_compression(state: dict) -> dict:
    """CONFLICT：动态时间分配，压缩非核心活动。"""
    from backend.roles import trace_line

    plan = state.get("plan")
    profile = state.get("group_profile")
    if plan is None:
        return {"require_human_interrupt": True}

    events = plan_to_timeline(plan, profile)
    window = _window_minutes(profile)
    travel = _travel_minutes(plan)
    compressed = compress_timeline_greedy(events, total_allowed_minutes=window, travel_minutes=travel)
    updated = apply_timeline_to_plan(plan, compressed)

    before = sum(e.duration_minutes for e in events)
    after = sum(e.duration_minutes for e in compressed)
    return {
        "plan": updated,
        "timeline": compressed,
        "current_failure_type": None,
        "require_human_interrupt": False,
        "compensator_retry": "dry_run",
        "trace": [
            trace_line(
                "Executor",
                f"动态时间分配｜窗口={window}min 活动 {before}→{after}min "
                f"（核心约束保留，非核心≥{_MIN_EVENT_MINUTES}min）",
                phase="恢复",
            )
        ],
    }
