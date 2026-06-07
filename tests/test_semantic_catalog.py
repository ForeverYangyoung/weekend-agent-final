"""语义化 catalog + 有状态满座 + 硬约束自愈。"""
from __future__ import annotations

import pytest

from backend.constraints_util import (
    apply_full_seat_constraint_update,
    blocked_poi_ids,
    build_constraints,
    candidate_passes_constraints,
)
from backend.mock_meituan.backend import MockBackend, reset_mock_backend
from backend.mock_meituan.catalog import MOCK_MERCHANTS, search
from backend.nodes.compensator import execute_poi_substitution
from backend.nodes.dry_run import dry_run_node
from backend.schemas import POICandidate
from backend.tools.errors import MerchantFullException, TicketSoldOutException


def test_mock_merchants_semantic_metadata() -> None:
    light = MOCK_MERCHANTS["poi_001"]["metadata"]
    kids = MOCK_MERCHANTS["poi_002"]["metadata"]
    hotpot = MOCK_MERCHANTS["poi_003"]["metadata"]
    assert light["avg_calories_per_meal"] == 350
    assert kids["suitable_ages"] == [3, 4, 5, 6, 7]
    assert hotpot["avg_calories_per_meal"] == 1200
    assert hotpot["max_party_size"] == 8


def test_catalog_search_injects_semantic_rows() -> None:
    eat = search("family", "吃", limit=20)
    ids = {r["poi_id"] for r in eat}
    assert "poi_001" in ids
    assert "poi_003" in ids
    play = search("family", "玩", limit=20)
    assert any(r["poi_id"] == "poi_002" for r in play)
    friends_play = search("friends", "玩", limit=20)
    assert all(r["poi_id"] != "poi_002" for r in friends_play)


def test_book_service_full_seat_on_poi_003_lunch() -> None:
    reset_mock_backend()
    backend = MockBackend()
    with pytest.raises(MerchantFullException):
        backend.book_service(poi_id="poi_003", time_slot="12:00-14:00", party_size=4)


def test_book_service_ticket_fuse_probabilistic() -> None:
    reset_mock_backend()
    backend = MockBackend()
    # 非陷阱时段应可订
    ok = backend.book_service(poi_id="poi_001", time_slot="18:00-20:00", party_size=2)
    assert ok["status"] == "SUCCESS"


def test_constraint_update_on_full_seat() -> None:
    c = build_constraints(None)
    updated = apply_full_seat_constraint_update(c, failed_poi_id="poi_003")
    assert updated.child_fatigue_index == 20
    assert updated.remaining_calories < c.remaining_calories


def test_blocked_poi_from_anomaly_list() -> None:
    assert "poi_003" in blocked_poi_ids(["poi_003_full", "poi_rest_201_full"])


def test_high_calorie_blocked_by_constraint() -> None:
    c = build_constraints(None)
    c = c.model_copy(update={"remaining_calories": 400.0})
    hotpot = POICandidate(
        poi_id="poi_003",
        name="火锅",
        category="火锅",
        metadata={"avg_calories_per_meal": 1200, "tags": ["火锅"]},
    )
    light = POICandidate(
        poi_id="poi_001",
        name="轻食",
        category="轻食",
        metadata={"avg_calories_per_meal": 350, "tags": ["轻食", "低卡"]},
    )
    assert not candidate_passes_constraints(hotpot, c, stage_name="吃")
    assert candidate_passes_constraints(light, c, stage_name="吃")


def test_poi_003_lunch_dry_run_triggers_compensator_state() -> None:
    from backend.graph import planning_graph
    from backend.schemas import Plan, PlanStage

    reset_mock_backend()
    state = planning_graph.invoke(
        {
            "user_input": "今天下午带老婆孩子出去玩，老婆减肥，孩子5岁，帮我安排一下。",
            "trace": [],
        }
    )
    plan: Plan = state["plan"]
    eat = PlanStage(
        name="吃",
        start_time="12:30",
        end_time="14:00",
        primary=POICandidate(
            poi_id="poi_003",
            name="川一哥地道老火锅",
            category="火锅",
            metadata=MOCK_MERCHANTS["poi_003"]["metadata"],
        ),
    )
    stages = [s if s.name != "吃" else eat for s in plan.stages]
    plan = plan.model_copy(update={"stages": stages})
    state = {**state, "plan": plan, **dry_run_node({**state, "plan": plan})}
    assert state.get("current_failure_type") is not None
    out = execute_poi_substitution(state)
    assert out.get("anomaly_encountered")
    assert "poi_003_full" in out["anomaly_encountered"]
    assert out["constraints"].child_fatigue_index >= 20
