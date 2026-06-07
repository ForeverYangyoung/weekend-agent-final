"""从 ToolCall / Plan 推断 current_failure_type。"""
from __future__ import annotations

from backend.schemas import FailureType, GroupProfile, Plan, ToolCall, ToolStatus
from backend.timeline_utils import detect_schedule_conflict


def _reason_text(call: ToolCall) -> str:
    return str((call.result or {}).get("reason") or call.error or "")


def classify_call_failure(call: ToolCall) -> FailureType | None:
    if call.status != ToolStatus.FAILED:
        return None
    code = (call.result or {}).get("code")
    reason = _reason_text(call)
    if (
        code == 409
        or (call.result or {}).get("exception") == "MerchantFullException"
        or "MerchantFullException" in reason
        or any(k in reason for k in ("满座", "已满", "无大桌", "桌位"))
    ):
        return FailureType.NO_SEAT
    if (
        code in (404, 410)
        or (call.result or {}).get("exception") == "TicketSoldOutException"
        or "TicketSoldOutException" in reason
        or any(k in reason for k in ("售罄", "无票", "sold_out", "熔断"))
    ):
        return FailureType.NO_TICKET
    if call.tool_name == "check_activity_availability":
        res = call.result or {}
        if not res.get("available", True) or int(res.get("tickets_left", 1) or 0) <= 0:
            return FailureType.NO_TICKET
    if call.tool_name == "check_table_availability":
        res = call.result or {}
        if not res.get("available", True):
            return FailureType.NO_SEAT
    return None


def classify_dry_run_failures(
    calls: list[ToolCall],
    *,
    plan: Plan | None = None,
    profile: GroupProfile | None = None,
) -> FailureType | None:
    priority = (FailureType.NO_SEAT, FailureType.NO_TICKET, FailureType.CONFLICT)
    found: set[FailureType] = set()
    for call in calls:
        ft = classify_call_failure(call)
        if ft:
            found.add(ft)
    if plan and detect_schedule_conflict(plan, profile):
        found.add(FailureType.CONFLICT)
    for ft in priority:
        if ft in found:
            return ft
    return None
