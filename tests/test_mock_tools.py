"""假后台与 Executor 路径的单测。"""
from __future__ import annotations

import pytest

from backend.tools import ToolContext, ToolError, invoke
from backend.mock_meituan.backend import reset_mock_backend
from backend.nodes.executor import executor_node
from backend.nodes.dry_run import dry_run_node
from backend.nodes.planner import planner_node
from backend.nodes.profiler import profiler_node
from backend.schemas import ToolCall, ToolStatus


@pytest.fixture(autouse=True)
def _clean_mock() -> None:
    reset_mock_backend()
    yield
    reset_mock_backend()


def test_book_table_success() -> None:
    ctx = ToolContext(idempotency_key="test-1")
    r = invoke(
        "book_table",
        {"poi_id": "poi_rest_021", "time": "18:00", "people": 3},
        ctx=ctx,
        stage_name="吃",
    )
    assert r["order_id"].startswith("M")
    assert r["status"] == "reserved"


def test_book_table_force_failure_409() -> None:
    ctx = ToolContext(force_failure_stage="吃", idempotency_key="test-2")
    with pytest.raises(ToolError) as exc:
        invoke(
            "book_table",
            {"poi_id": "poi_rest_021", "time": "18:00", "people": 3},
            ctx=ctx,
            stage_name="吃",
        )
    assert exc.value.code == 409


def test_idempotency_same_key() -> None:
    ctx = ToolContext(idempotency_key="same-key")
    r1 = invoke(
        "buy_ticket",
        {"poi_id": "poi_park_001", "count": 2},
        ctx=ctx,
        stage_name="玩",
    )
    r2 = invoke(
        "buy_ticket",
        {"poi_id": "poi_park_001", "count": 2},
        ctx=ctx,
        stage_name="玩",
    )
    assert r1["order_id"] == r2["order_id"]


def test_cancel_order() -> None:
    ctx = ToolContext(idempotency_key="cancel-1")
    booked = invoke(
        "book_table",
        {"poi_id": "poi_a", "time": "12:00", "people": 2},
        ctx=ctx,
        stage_name="吃",
    )
    cancelled = invoke("cancel_order", {"order_id": booked["order_id"]}, ctx=ctx)
    assert cancelled["cancelled"] is True


def test_executor_force_failure_triggers_compensator_path() -> None:
    state = {
        "user_input": "周六带孩子和老婆出去",
        "force_failure": "吃",
    }
    state.update(profiler_node(state))
    state.update(planner_node(state))
    state.update(dry_run_node(state))
    out = executor_node(state)
    assert len(out["executed_calls"]) >= 1  # 玩、加餐可能成功
    assert len(out["failed_calls"]) == 1
    assert out["failed_calls"][0].stage_name == "吃"
