"""Compensator 公式选店与 409 场景手术。"""
from backend.compensator_scoring import pick_best_alternative
from backend.graph import dry_run_recovery_graph
from backend.mock_meituan.backend import reset_mock_backend
from backend.nodes.compensator import compensator_node
from backend.nodes.dry_run import dry_run_node
from backend.schemas import ToolStatus
from backend.state import AgentState


def _friends_state_with_201_trap() -> AgentState:
    from backend.graph import planning_graph

    reset_mock_backend()
    initial: AgentState = {
        "user_input": "下午想和 4 个朋友（2 男 2 女）一起出去玩几个小时，找点有意思的活动配个晚饭，帮我安排一下。",
        "trace": [],
    }
    return planning_graph.invoke(initial)  # type: ignore[arg-type]


def test_compensator_swaps_poi_rest_201_on_409() -> None:
    state = _friends_state_with_201_trap()
    plan = state.get("plan")
    assert plan
    eat = next(s for s in plan.stages if s.name == "吃")
    if eat.primary.poi_id != "poi_rest_201":
        eat = eat.model_copy(update={"primary": eat.primary.model_copy(update={"poi_id": "poi_rest_201"})})
        plan = plan.model_copy(update={"stages": [s if s.name != "吃" else eat for s in plan.stages]})
        state = {**state, "plan": plan}

    state = {**state, **dry_run_node(state)}
    assert any(c.status == ToolStatus.FAILED for c in state["dry_run_calls"])

    out = compensator_node(state)
    assert not out.get("require_human_interrupt")
    assert out.get("compensator_retry") == "dry_run"
    new_plan = out["plan"]
    new_eat = next(s for s in new_plan.stages if s.name == "吃")
    assert new_eat.primary.poi_id != "poi_rest_201"
    assert new_plan.is_compromised


def test_dry_run_recovery_graph_uses_compensator() -> None:
    state = _friends_state_with_201_trap()
    plan = state.get("plan")
    eat = next(s for s in plan.stages if s.name == "吃")
    if eat.primary.poi_id != "poi_rest_201":
        eat = eat.model_copy(update={"primary": eat.primary.model_copy(update={"poi_id": "poi_rest_201"})})
        plan = plan.model_copy(update={"stages": [s if s.name != "吃" else eat for s in plan.stages]})
    state = {**state, "plan": plan, **dry_run_node({**state, "plan": plan})}

    final = dry_run_recovery_graph.invoke(state)  # type: ignore[arg-type]
    eat_id = next(s.primary.poi_id for s in final["plan"].stages if s.name == "吃")
    assert eat_id != "poi_rest_201"
    assert all(c.status == ToolStatus.OK for c in final.get("dry_run_calls") or [])


def test_pick_best_alternative_respects_friends_pool() -> None:
    from backend.agents.profiler import analyze_profile
    from backend.agents.researcher import run_initial_research

    profile = analyze_profile("下午和三个朋友一起出去，4个人，别太远，想吃重口味")
    research = run_initial_research(profile)
    eat_candidates = next(s.candidates for s in research.stages if s.stage_name.startswith("吃"))
    from backend.agents.planner import build_plans

    plans = build_plans(profile, research, top_k=1)
    best = pick_best_alternative(
        eat_candidates,
        failed_poi_id="poi_rest_201",
        plan=plans[0],
        stage_name="吃",
        profile=profile,
    )
    assert best is not None
    assert best.poi_id != "poi_rest_201"
