"""三类故障自愈 + 动态时间分配 + 并行预检。"""
from __future__ import annotations

import asyncio

from backend.failure_detect import classify_dry_run_failures
from backend.graph import dry_run_recovery_graph
from backend.mock_meituan.backend import reset_mock_backend
from backend.nodes.compensator import compensator_node, execute_poi_substitution
from backend.nodes.dry_run import dry_run_node
from backend.schemas import (
    CollaborativeConsensus,
    FailureType,
    Plan,
    PlanStage,
    POICandidate,
    ToolCall,
    ToolStatus,
)
from backend.timeline_utils import (
    compress_timeline_greedy,
    detect_schedule_conflict,
    execute_time_compression,
    plan_to_timeline,
)
from backend.tools.http_client import mock_parallel_precheck


def _minimal_plan(*, play_end: str = "16:30", eat_start: str = "16:00") -> Plan:
    """故意制造时间重叠 + 超长行程。"""
    return Plan(
        summary="test",
        stages=[
            PlanStage(
                name="玩",
                start_time="14:00",
                end_time=play_end,
                primary=POICandidate(
                    poi_id="poi_act_101",
                    name="测试剧本杀",
                    category="活动",
                    metadata={"distance_km": 2},
                ),
            ),
            PlanStage(
                name="吃",
                start_time=eat_start,
                end_time="18:30",
                primary=POICandidate(
                    poi_id="poi_rest_201",
                    name="测试烤肉",
                    category="烤肉",
                    metadata={"distance_km": 1},
                ),
            ),
        ],
        total_duration_hours=8.0,
    )


def test_schemas_failure_and_consensus_no_real_names() -> None:
    c = CollaborativeConsensus()
    assert c.shared_users == ["User_A", "User_B", "User_C"]
    joined = " ".join(c.shared_users)
    assert not any("\u4e00" <= ch <= "\u9fff" for ch in joined)
    assert FailureType.NO_SEAT.value == "NO_SEAT"


def test_detect_schedule_conflict() -> None:
    plan = _minimal_plan()
    assert detect_schedule_conflict(plan) is True


def test_compress_timeline_keeps_core_min_30() -> None:
    plan = _minimal_plan()
    events = plan_to_timeline(plan)
    compressed = compress_timeline_greedy(events, total_allowed_minutes=300, travel_minutes=30)
    play = next(e for e in compressed if e.stage_name == "玩")
    eat = next(e for e in compressed if e.stage_name == "吃")
    assert eat.duration_minutes >= 30
    assert play.duration_minutes >= 30
    assert eat.is_core_constraint


def test_compensator_conflict_compression() -> None:
    plan = _minimal_plan()
    state = {
        "plan": plan,
        "current_failure_type": FailureType.CONFLICT,
        "group_profile": None,
    }
    out = execute_time_compression(state)
    assert out.get("plan") is not None
    assert out.get("current_failure_type") is None
    assert out.get("compensator_retry") == "dry_run"
    assert not detect_schedule_conflict(out["plan"]) or out["plan"].is_compromised


def test_parallel_precheck_under_3s() -> None:
    reset_mock_backend()

    async def _run() -> list:
        return await mock_parallel_precheck(["poi_rest_201", "poi_rest_202", "poi_act_101"])

    results = asyncio.run(_run())
    assert len(results) == 3
    assert all("seat_available" in r for r in results)


def test_no_seat_recovery_still_works() -> None:
    from backend.graph import planning_graph

    reset_mock_backend()
    initial = {
        "user_input": "下午想和 4 个朋友（2 男 2 女）一起出去玩几个小时，找点有意思的活动配个晚饭，帮我安排一下。",
        "trace": [],
    }
    state = planning_graph.invoke(initial)
    plan = state["plan"]
    eat = next(s for s in plan.stages if s.name == "吃")
    if eat.primary.poi_id != "poi_rest_201":
        eat = eat.model_copy(update={"primary": eat.primary.model_copy(update={"poi_id": "poi_rest_201"})})
        plan = plan.model_copy(update={"stages": [s if s.name != "吃" else eat for s in plan.stages]})
        state = {**state, "plan": plan}

    state = {**state, **dry_run_node(state)}
    assert state.get("current_failure_type") == FailureType.NO_SEAT
    out = execute_poi_substitution(state)
    assert out.get("plan") is not None
    new_eat = next(s for s in out["plan"].stages if s.name == "吃")
    assert new_eat.primary.poi_id != "poi_rest_201"

    final = dry_run_recovery_graph.invoke({**state, **out})
    assert all(c.status == ToolStatus.OK for c in final.get("dry_run_calls") or [])


def test_no_seat_heals_plan_alternatives_not_only_primary() -> None:
    """满座自愈须同步备选方案，避免右侧卡仍展示已满座的川一哥。"""
    from backend.agents.profiler import analyze_profile
    from backend.agents.planner import build_plans
    from backend.nodes.researcher import researcher_node

    reset_mock_backend()
    text = (
        "今天早上带老婆孩子出去玩，孩子5岁，中午12点想吃川一哥火锅，帮我安排。"
    )
    profile = analyze_profile(text)
    research = researcher_node({"group_profile": profile, "trace": []})["research_result"]
    plans = build_plans(profile, research, top_k=2)
    assert len(plans) >= 2
    primary, alt = plans[0], plans[1]
    for p in (primary, alt):
        eat = next(s for s in p.stages if s.name == "吃")
        assert eat.primary.poi_id == "poi_003"

    state = {
        "plan": primary,
        "plan_alternatives": [alt],
        "group_profile": profile,
        "research_result": research,
        "constraints": None,
        "anomaly_encountered": [],
        "dry_run_calls": [
            ToolCall(
                id="d1",
                stage_name="吃",
                tool_name="check_table_availability",
                status=ToolStatus.FAILED,
                args={"poi_id": "poi_003", "people": 3},
                result={"code": 409, "reason": "12:00-14:00 已满座"},
                error="12:00-14:00 已满座",
            )
        ],
    }
    out = execute_poi_substitution(state)
    assert out.get("plan") is not None
    healed_primary = out["plan"]
    healed_alts = out.get("plan_alternatives") or []
    assert len(healed_alts) == 1
    for p in (healed_primary, healed_alts[0]):
        eat = next(s for s in p.stages if s.name == "吃")
        assert eat.primary.poi_id != "poi_003"
        assert p.is_compromised
        assert "满座" in p.compromise_message
    assert "poi_003_full" in out.get("anomaly_encountered", [])


def test_select_plan_clears_stale_dry_run_calls() -> None:
    from backend.hil import select_plan
    from backend.schemas import ToolStatus

    state = {
        "plan": Plan(summary="a", stages=[]),
        "plan_alternatives": [Plan(summary="b", stages=[])],
        "dry_run_calls": [
            ToolCall(
                id="x",
                stage_name="吃",
                tool_name="check_table_availability",
                status=ToolStatus.OK,
            )
        ],
        "current_failure_type": FailureType.NO_SEAT,
    }
    out = select_plan(state, "alt_0")
    assert out.get("dry_run_calls") == []
    assert out.get("current_failure_type") is None


def test_classify_no_ticket_from_code() -> None:
    calls = [
        ToolCall(
            id="t1",
            stage_name="玩",
            tool_name="check_activity_availability",
            status=ToolStatus.FAILED,
            result={"code": 410, "poi_id": "poi_act_101"},
            error="活动票已售罄",
        )
    ]
    assert classify_dry_run_failures(calls) == FailureType.NO_TICKET
    routed = compensator_node(
        {
            "plan": _minimal_plan(play_end="16:00", eat_start="16:30"),
            "current_failure_type": FailureType.NO_TICKET,
            "dry_run_calls": calls,
            "research_result": None,
        }
    )
    assert routed.get("require_human_interrupt") or routed.get("plan")
