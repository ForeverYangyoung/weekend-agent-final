"""微调换活动：不应第二次立刻换回最初那家。"""
from __future__ import annotations

from backend.agents.planner import build_plans
from backend.agents.profiler import analyze_profile
from backend.agents.researcher import run_initial_research
from backend.graph import planning_graph, revise_graph
from backend.mock_meituan.backend import reset_mock_backend
from backend.nodes.plan_patcher import _next_candidate, _tried_poi_ids
from backend.nodes.researcher import researcher_node
from backend.schemas import PlanStage, POICandidate, ToolStatus
from backend.server import _recover_dry_run_failures


def _friends_state():
    reset_mock_backend()
    return planning_graph.invoke(
        {
            "user_input": "下午 4 个朋友聚会，晚饭想吃姜虎东烤肉，再找个活动，帮我安排。",
            "trace": [],
        }
    )


def test_second_change_play_does_not_revert_to_first() -> None:
    state = _friends_state()
    play = next(s for s in state["plan"].stages if s.name == "玩")
    first_id = play.primary.poi_id

    state = {
        **state,
        "revise_feedback": "换活动",
        "revise_locked_stages": [],
        "plan_snapshots": [state["plan"].model_dump(mode="json")],
        "revise_pass": 0,
    }
    out1 = revise_graph.invoke(state)
    play1 = next(s for s in out1["plan"].stages if s.name == "玩")
    assert play1.primary.poi_id != first_id

    state2 = {
        **out1,
        "revise_feedback": "换活动",
        "revise_locked_stages": [],
        "plan_snapshots": [
            state["plan"].model_dump(mode="json"),
            out1["plan"].model_dump(mode="json"),
        ],
        "revise_pass": 0,
    }
    out2 = revise_graph.invoke(state2)
    play2 = next(s for s in out2["plan"].stages if s.name == "玩")
    assert play2.primary.poi_id != first_id
    assert play2.primary.poi_id == play1.primary.poi_id


def test_next_candidate_skips_tried_from_snapshots() -> None:
    from backend.agents.profiler import analyze_profile

    profile = analyze_profile("下午 4 个朋友聚会，想吃烤肉")
    research = run_initial_research(profile)
    play_rs = next(s for s in research.stages if s.stage_name == "玩")
    a, b = play_rs.candidates[0], play_rs.candidates[1]
    stage = PlanStage(
        name="玩",
        start_time="14:00",
        end_time="16:30",
        primary=a,
        backups=[b],
    )
    state = {
        "plan_snapshots": [
            {
                "stages": [
                    {"name": "玩", "primary": {"poi_id": b.poi_id}},
                ]
            }
        ]
    }
    nxt = _next_candidate(stage, research, state=state)  # type: ignore[arg-type]
    assert nxt is None
    tried = _tried_poi_ids(state, "玩")  # type: ignore[arg-type]
    assert b.poi_id in tried


def test_revise_change_food_recovers_from_lunch_full_seat() -> None:
    """多次换餐厅旋到午市满座的川一哥时，应自愈换店而非直接 409。"""
    reset_mock_backend()
    text = (
        "今天早上带老婆孩子出去玩，孩子5岁，中午12点想吃川一哥火锅，帮我安排。"
    )
    profile = analyze_profile(text)
    base = researcher_node({"group_profile": profile, "trace": []})
    research = base["research_result"]
    plan = build_plans(profile, research, top_k=1)[0]

    state = {
        **base,
        "plan": plan,
        "plan_alternatives": [],
        "plan_snapshots": [plan.model_dump(mode="json")],
        "revise_feedback": "换餐厅",
        "revise_locked_stages": [],
        "anomaly_encountered": ["poi_003_full"],
        "revise_pass": 0,
        "trace": [],
    }
    revised = revise_graph.invoke(state)  # type: ignore[arg-type]
    recovered = _recover_dry_run_failures(revised, fresh=False)
    dry_calls = recovered.get("dry_run_calls") or []
    assert dry_calls
    assert all(c.status == ToolStatus.OK for c in dry_calls)
    eat = next(s for s in recovered["plan"].stages if s.name == "吃")
    assert eat.primary.poi_id != "poi_003"


def test_brand_key_blocks_all_wagas_stores() -> None:
    from backend.revise_utils import brand_key, expand_brand_blocks
    from backend.agents.researcher import run_initial_research
    from backend.agents.profiler import analyze_profile

    assert brand_key("Wagas 沙拉轻食（奥森店）") == "wagas"
    assert brand_key("Wagas 轻食（海淀万柳店）") == "wagas"
    profile = analyze_profile("家庭出游，轻食，孩子5岁")
    research = run_initial_research(profile)
    blocked = expand_brand_blocks(research, "吃", {"wagas"})
    assert "poi_rest_021" in blocked
    assert "poi_rest_hd_wagas" in blocked


def test_refresh_revised_plan_bundle_updates_price_and_alternatives() -> None:
    from backend.revise_utils import finalize_plan_metadata, refresh_revised_plan_bundle
    from backend.schemas import PlanStage

    reset_mock_backend()
    text = "家庭出游，轻食，孩子5岁，帮我安排"
    profile = analyze_profile(text)
    base = researcher_node({"group_profile": profile, "trace": []})
    research = base["research_result"]
    plan = build_plans(profile, research, top_k=1)[0]
    eat = next(s for s in plan.stages if s.name == "吃")
    play = next(s for s in plan.stages if s.name == "玩")
    new_eat = next(
        c
        for rs in research.stages
        if rs.stage_name == "吃"
        for c in rs.candidates
        if c.poi_id != eat.primary.poi_id
    )
    patched = plan.model_copy(
        update={
            "stages": [
                play,
                PlanStage(
                    name="吃",
                    start_time=eat.start_time,
                    end_time=eat.end_time,
                    primary=new_eat,
                    backups=eat.backups,
                ),
            ]
        }
    )
    state = {
        **base,
        "group_profile": profile,
        "plan": patched,
        "plan_alternatives": [plan],
        "plan_snapshots": [plan.model_dump(mode="json")],
    }
    out = refresh_revised_plan_bundle(state)  # type: ignore[arg-type]
    refreshed = finalize_plan_metadata(out["plan"], profile)
    per_person = refreshed.total_cost_estimate // max(profile.people_count, 1)
    play_price = int(play.primary.metadata.get("avg_price", 0) or 0)
    eat_price = int(new_eat.metadata.get("avg_price", 0) or 0)
    assert per_person == play_price + eat_price
    alts = out.get("plan_alternatives") or []
    if len(alts) >= 2:
        assert _plan_poi_sig(alts[0]) != _plan_poi_sig(alts[1])


def _plan_poi_sig(plan) -> tuple[str, str]:
    play = next((s for s in plan.stages if s.name == "玩"), None)
    eat = next((s for s in plan.stages if s.name == "吃"), None)
    return (
        play.primary.poi_id if play else "",
        eat.primary.poi_id if eat else "",
    )


def test_next_candidate_skips_anomaly_blocked_poi() -> None:
    from backend.agents.profiler import analyze_profile

    reset_mock_backend()
    profile = analyze_profile("家庭出游，轻食，孩子5岁，帮我安排")
    research = run_initial_research(profile)
    eat_rs = next(s for s in research.stages if s.stage_name == "吃")
    current = next(c for c in eat_rs.candidates if c.poi_id == "poi_rest_021")
    stage = PlanStage(
        name="吃",
        start_time="12:00",
        end_time="14:00",
        primary=current,
        backups=[c for c in eat_rs.candidates if c.poi_id != current.poi_id],
    )
    state = {"anomaly_encountered": ["poi_003_full"], "dry_run_calls": []}
    nxt = _next_candidate(stage, research, state=state, profile=profile)  # type: ignore[arg-type]
    assert nxt is not None
    assert nxt.poi_id != "poi_003"
    assert "wagas" not in nxt.name.lower()
