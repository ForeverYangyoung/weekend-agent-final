"""赛题场景手术：4人满座陷阱、顺路距离、加餐送达闭环。"""
from fastapi.testclient import TestClient

from backend.graph import agent_graph
from backend.mock_meituan.backend import get_mock_backend, reset_mock_backend
from backend.state import AgentState


def test_four_person_table_trap_replans_to_backup_restaurant() -> None:
    reset_mock_backend()
    initial: AgentState = {
        "user_input": "下午想和 4 个朋友（2 男 2 女）一起出去玩几个小时，找点有意思的活动配个晚饭，帮我安排一下。",
        "trace": [],
    }
    final: AgentState = agent_graph.invoke(initial)  # type: ignore[arg-type]

    eat_stages = [s for s in (final.get("plan") or {}).stages if s.name == "吃"]  # type: ignore[union-attr]
    assert eat_stages
    assert eat_stages[0].primary.poi_id != "poi_rest_201"

    traces = " ".join(final.get("trace") or [])
    assert "预检" in traces or "重规划" in traces


def test_addon_delivery_links_to_play_exit_on_confirm() -> None:
    """HIL：附加项仅在 confirm + selected_addon_ids 时下单，家庭场景送至玩阶段出口。"""
    reset_mock_backend()
    client = TestClient(__import__("backend.server", fromlist=["app"]).app)

    buf = ""
    with client.stream(
        "POST",
        "/v1/agent/stream",
        json={
            "user_input": "今天下午带老婆孩子出去玩，老婆减肥，孩子5岁，帮我安排一下。",
        },
    ) as resp:
        assert resp.status_code == 200
        for chunk in resp.iter_text():
            buf += chunk

    import json

    session_id = ""
    addon_id = ""
    for block in buf.split("\n\n"):
        if "awaiting_confirm" not in block:
            continue
        line = block.strip().removeprefix("data: ")
        payload = json.loads(line)
        session_id = payload.get("session_id", "")
        plans = payload.get("plans") or []
        if plans and plans[0].get("addons"):
            addon_id = plans[0]["addons"][0]["addon_id"]
        break

    assert session_id
    assert addon_id

    r = client.post(
        "/v1/agent/confirm",
        json={
            "session_id": session_id,
            "plan_id": "primary",
            "selected_addon_ids": [addon_id],
        },
    )
    assert r.status_code == 200
    data = r.json()
    traces = " ".join(data.get("trace") or [])
    assert "附加下单成功" in traces or data.get("executed", 0) >= 1

    addon_orders = [
        o for o in data.get("orders") or [] if o.get("stage") == "附加"
    ]
    if not addon_orders:
        addon_calls = [
            c
            for c in (data.get("trace") or [])
            if "order_addon" in c or "deliver_to_poi_id" in c
        ]
        assert addon_calls or "附加下单成功" in traces


def test_play_eat_within_distance_band() -> None:
    reset_mock_backend()
    initial: AgentState = {
        "user_input": "今天下午带老婆孩子出去玩，别太远，老婆减肥，孩子5岁，帮我安排一下。",
        "trace": [],
    }
    final: AgentState = agent_graph.invoke(initial)  # type: ignore[arg-type]
    plan = final.get("plan")
    assert plan
    play = next((s for s in plan.stages if s.name == "玩"), None)
    eat = next((s for s in plan.stages if s.name == "吃"), None)
    assert play and eat
    d_play = float(play.primary.metadata.get("distance_km", 0) or 0)
    d_eat = float(eat.primary.metadata.get("distance_km", 0) or 0)
    assert abs(d_play - d_eat) <= 3.0


def test_profile_sanitize_removes_conflicting_people_tags() -> None:
    from backend.agents.profiler import analyze_profile, apply_profile_overrides

    profile = analyze_profile("下午自己出去走走")
    assert profile.scene == "solo"
    assert profile.people_count == 1

    merged = apply_profile_overrides(
        profile,
        [
            {"key": "people_count", "value": "3", "action": "set"},
            {"key": "interests", "value": "3人", "action": "add"},
            {"key": "dietary", "value": "火锅", "action": "add"},
        ],
    )
    labels = [t.label for t in merged.editable_tags]
    assert merged.people_count == 3
    assert merged.scene == "friends"
    assert "3 人" in labels
    assert "独自" not in labels
    assert "3人" not in labels


def test_plan_payload_includes_price_and_distance() -> None:
    from backend.graph import planning_graph
    from backend.hil import build_plans_payload

    reset_mock_backend()
    initial: AgentState = {
        "user_input": "下午和三个朋友一起出去，4个人，别太远，想吃重口味",
        "trace": [],
    }
    final: AgentState = planning_graph.invoke(initial)  # type: ignore[arg-type]
    play = build_plans_payload(final)[0].get("play") or {}
    assert play.get("priceLabel")
    assert play.get("distanceLabel")


def test_friends_light_food_excludes_bbq_restaurants() -> None:
    from backend.agents.planner import build_plans
    from backend.agents.profiler import analyze_profile, apply_profile_overrides
    from backend.agents.researcher import run_initial_research
    from backend.graph import planning_graph
    from backend.hil import build_plans_payload, create_session, get_session

    reset_mock_backend()
    initial: AgentState = {
        "user_input": "下午和三个朋友一起出去，4个人，别太远，想吃重口味",
        "trace": [],
    }
    final: AgentState = planning_graph.invoke(initial)  # type: ignore[arg-type]
    sid = create_session(final)
    base = get_session(sid)
    assert base is not None
    profile = apply_profile_overrides(
        base["group_profile"],
        [{"key": "dietary", "value": "轻食", "action": "set"}],
    )
    research = run_initial_research(profile)
    plans = build_plans(profile, research, blocked={"poi_rest_201"}, top_k=2)
    assert plans
    eat_names = [
        next(s.primary.name for s in p.stages if s.name == "吃") for p in plans
    ]
    assert all("烤肉" not in n and "炙烤" not in n for n in eat_names)
    assert any("轻食" in n or "Wagas" in n or "超级碗" in n for n in eat_names)
    if len(set(eat_names)) >= 2:
        assert len(set(eat_names)) == 2


def test_match_reasons_only_when_restaurant_matches() -> None:
    from backend.agents.profiler import apply_profile_overrides
    from backend.agents.researcher import run_initial_research
    from backend.agents.planner import build_plans
    from backend.hil import build_plans_payload

    reset_mock_backend()
    profile = apply_profile_overrides(
        __import__("backend.agents.profiler", fromlist=["analyze_profile"]).analyze_profile(
            "下午和三个朋友一起出去，4个人，别太远"
        ),
        [{"key": "dietary", "value": "轻食", "action": "set"}],
    )
    research = run_initial_research(profile)
    plans = build_plans(profile, research, top_k=1)
    assert plans
    payload = build_plans_payload(
        {"group_profile": profile, "plan": plans[0], "plan_alternatives": []}
    )[0]
    reasons = payload.get("matchReasons") or []
    assert any("轻食" in r for r in reasons)
    assert not any("重口味" in r for r in reasons)
    eat = payload.get("eat") or {}
    assert eat.get("priceLabel")
    assert eat.get("distanceLabel")


def test_profiler_extracts_heavy_flavor_constraint() -> None:
    from backend.agents.profiler import analyze_profile

    profile = analyze_profile("下午和三个朋友一起出去，4个人，别太远，想吃重口味")
    assert "重口味" in profile.dietary
    chip_labels = [t.label for t in profile.editable_tags]
    assert "重口味" in chip_labels


def test_plan_payload_shows_match_reasons() -> None:
    from backend.graph import planning_graph
    from backend.hil import build_plans_payload

    reset_mock_backend()
    initial: AgentState = {
        "user_input": "下午和三个朋友一起出去，4个人，别太远，想吃重口味",
        "trace": [],
    }
    final: AgentState = planning_graph.invoke(initial)  # type: ignore[arg-type]
    payloads = build_plans_payload(final)
    assert payloads
    reasons = payloads[0].get("matchReasons") or []
    assert any("重口味" in r for r in reasons)
    if len(payloads) >= 2:
        assert payloads[1].get("diffSummary")
        assert "玩法" in payloads[1]["diffSummary"] or "餐厅" in payloads[1]["diffSummary"]


def test_friends_top_k_plans_use_different_venues() -> None:
    """备选方案应是不同店组合，而非同一套店只换顺序。"""
    reset_mock_backend()
    initial: AgentState = {
        "user_input": "下午和三个朋友一起出去，4个人，别太远，想吃重口味",
        "trace": [],
    }
    from backend.hil import build_plans_payload

    final: AgentState = agent_graph.invoke(initial)  # type: ignore[arg-type]
    payloads = build_plans_payload(final)
    assert len(payloads) >= 2

    def venue_key(p: dict) -> frozenset[str]:
        names = []
        if p.get("play"):
            names.append(p["play"]["name"])
        if p.get("eat"):
            names.append(p["eat"]["name"])
        return frozenset(names)

    assert venue_key(payloads[0]) != venue_key(payloads[1])


def test_mock_table_trap_api() -> None:
    reset_mock_backend()
    backend = get_mock_backend()
    r = backend.check_table_availability(
        poi_id="poi_rest_201", time="18:00", people=4
    )
    assert r["available"] is False
