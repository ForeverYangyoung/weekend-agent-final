"""把 Planner 产出的 Plan 翻译成 DryRun 要「打听」的 Tool 列表。"""
from __future__ import annotations

from uuid import uuid4

from backend.schemas import Plan, ToolCall


def plan_to_dry_run_calls(plan: Plan, *, people: int = 4) -> list[ToolCall]:
    """根据方案每个阶段，生成对应的「只查询、不下单」Tool。"""
    calls: list[ToolCall] = []
    for stage in plan.stages:
        if stage.name == "玩":
            calls.append(
                ToolCall(
                    id=f"tc_{uuid4().hex[:8]}",
                    stage_name=stage.name,
                    tool_name="check_activity_availability",
                    args={
                        "poi_id": stage.primary.poi_id,
                        "start": stage.start_time,
                    },
                )
            )
        elif stage.name == "吃":
            calls.append(
                ToolCall(
                    id=f"tc_{uuid4().hex[:8]}",
                    stage_name=stage.name,
                    tool_name="check_table_availability",
                    args={
                        "poi_id": stage.primary.poi_id,
                        "people": people,
                        "time": stage.start_time,
                    },
                )
            )
        elif stage.name == "加餐":
            meta = stage.primary.metadata or {}
            deliver_to = meta.get("deliver_to_poi_id") or meta.get("target_restaurant")
            if not deliver_to:
                eat_stage = next((s for s in plan.stages if s.name == "吃"), None)
                if eat_stage is not None:
                    deliver_to = eat_stage.primary.poi_id
            addon_args: dict = {"poi_id": stage.primary.poi_id}
            if deliver_to:
                addon_args["delivery_address"] = deliver_to
                addon_args["deliver_to_poi_id"] = deliver_to
            calls.append(
                ToolCall(
                    id=f"tc_{uuid4().hex[:8]}",
                    stage_name=stage.name,
                    tool_name="check_addon_stock",
                    args=addon_args,
                )
            )
    return calls


# DryRun 的「打听」→ Executor 的「真下单」
READ_TO_WRITE_TOOL: dict[str, str] = {
    "check_activity_availability": "buy_ticket",
    "check_table_availability": "book_table",
    "check_addon_stock": "order_addon",
}
