"""方案 issue 分类：偏好矛盾 vs 附近无菜系。"""
import json

from fastapi.testclient import TestClient

from backend.agents.planner import build_plans
from backend.agents.profiler import (
    analyze_profile,
    apply_explicit_preference_priority,
    apply_profile_overrides,
)
from backend.nodes.researcher import researcher_node
from backend.hil import build_plans_payload, detect_preference_conflicts
from backend.server import app


def _payload_from_stream(buf: str) -> dict:
    for block in buf.split("\n\n"):
        if "awaiting_confirm" not in block:
            continue
        line = block.strip().removeprefix("data: ")
        return json.loads(line)
    raise AssertionError("no awaiting_confirm")


def test_friends_explicit_heavy_does_not_block_or_pick_kids_play() -> None:
    c = TestClient(app)
    buf = ""
    with c.stream(
        "POST",
        "/v1/agent/stream",
        json={
            "user_input": "下午和三个朋友一起出去，4个人，别太远，想吃重口味，帮我安排一下",
        },
    ) as resp:
        assert resp.status_code == 200
        for chunk in resp.iter_text():
            buf += chunk

    payload = _payload_from_stream(buf)
    assert payload.get("preference_conflicts") in (None, [])
    assert "小明" not in buf
    plans = payload.get("plans") or []
    assert plans
    for plan in plans:
        play_name = (plan.get("play") or {}).get("name", "")
        assert "儿童乐园" not in play_name
        assert "亲子" not in play_name


def test_explicit_heavy_removes_archive_no_spicy_for_friends() -> None:
    from backend.nodes.profiler import inject_history_archives

    profile = analyze_profile("下午和三个朋友一起出去，4个人，想吃重口味")
    profile, traces = inject_history_archives(profile, profile.raw_text)
    assert traces
    assert all("小明" not in t for t in traces)
    profile = apply_explicit_preference_priority(profile)
    assert "禁辣" not in profile.dietary
    assert "重辣" not in profile.forbidden_tags
    conflicts = detect_preference_conflicts(profile)
    assert conflicts == []


def test_explicit_sichuan_wins_over_implicit_light_archive() -> None:
    """用户显式点川菜时，应自动拿掉档案低卡，不再拦规划。"""
    profile = analyze_profile("家庭出游，老婆减肥轻食，孩子5岁，还想吃川菜")
    profile = apply_profile_overrides(
        profile,
        [{"key": "dietary", "value": "川菜", "action": "add"}],
    )
    conflicts = detect_preference_conflicts(profile)
    assert conflicts == []
    assert "川菜" in profile.dietary
    assert "低卡" not in profile.dietary


def test_sichuan_family_explains_distance_reason_or_match() -> None:
    c = TestClient(app)
    buf = ""
    with c.stream(
        "POST",
        "/v1/agent/stream",
        json={
            "user_input": "今天下午带老婆孩子出去玩，孩子5岁，别太远，帮我安排一下",
            "overrides": [{"key": "dietary", "value": "川菜", "action": "add"}],
        },
    ) as resp:
        assert resp.status_code == 200
        for chunk in resp.iter_text():
            buf += chunk

    payload = _payload_from_stream(buf)
    primary = payload["plans"][0]
    # 历史档案注入低卡后，再叠加川菜 → 画像层矛盾优先于距离解释
    if payload.get("preference_conflicts"):
        assert payload["preference_conflicts"][0]["code"] == "light_vs_heavy_cuisine"
        assert primary["issueKind"] == "needs_preference_fix"
        assert primary["isValid"] is False
    elif primary.get("issueKind") == "alternative_available":
        issue = primary["planIssues"][0]
        assert issue["code"] == "cuisine_unavailable"
        assert "3km" in issue["detail"] or "3 km" in issue["detail"]
        assert "川菜" in issue["detail"]
        assert "找不到" in issue["detail"] or "没有" in issue["detail"]
    else:
        assert primary.get("isValid") is True
        assert "川味小馆" in primary.get("eat", {}).get("name", "")


def test_cuisine_unavailable_near_play_is_friendly() -> None:
    c = TestClient(app)
    buf = ""
    with c.stream(
        "POST",
        "/v1/agent/stream",
        json={
            "user_input": (
                "今天下午带老婆孩子去奥森玩，孩子5岁，"
                "晚饭想吃川菜，别太远，帮我安排"
            ),
        },
    ) as resp:
        assert resp.status_code == 200
        for chunk in resp.iter_text():
            buf += chunk

    payload = _payload_from_stream(buf)
    primary = payload["plans"][0]
    if payload.get("preference_conflicts"):
        assert primary["issueKind"] == "needs_preference_fix"
        assert primary["isValid"] is False
    elif primary["issueKind"] == "alternative_available":
        assert primary["planIssues"][0]["code"] == "cuisine_unavailable"
        assert "周边" in primary["planIssues"][0]["detail"] or "范围" in primary["planIssues"][0]["detail"]
        assert "川菜" in primary["planIssues"][0]["detail"]
        assert primary["allowAcceptAlternative"] is True
        assert primary["isValid"] is False
    else:
        assert primary["isValid"] is True
        assert "川味小馆" in primary.get("eat", {}).get("name", "")


def test_family_light_food_stays_valid() -> None:
    c = TestClient(app)
    buf = ""
    with c.stream(
        "POST",
        "/v1/agent/stream",
        json={"user_input": "今天下午带老婆孩子出去玩，老婆减肥，孩子5岁"},
    ) as resp:
        assert resp.status_code == 200
        for chunk in resp.iter_text():
            buf += chunk

    payload = _payload_from_stream(buf)
    primary = payload["plans"][0]
    assert primary.get("issueKind", "ok") == "ok"
    assert primary["isValid"] is True


def test_removing_light_constraint_clears_light_conflict() -> None:
    profile = analyze_profile("家庭出游，老婆减肥轻食，孩子5岁，还想吃火锅")
    # 用户在 HIL 中移除轻食/低卡诉求，只保留火锅
    profile = apply_profile_overrides(
        profile,
        [
            {"key": "dietary", "value": "低卡", "action": "remove"},
            {"key": "dietary", "value": "轻食", "action": "remove"},
        ],
    )
    conflicts = detect_preference_conflicts(profile)
    assert conflicts == []


def test_interests_light_should_not_be_hard_constraint() -> None:
    profile = analyze_profile("下午带孩子去公园玩")
    # 模拟历史兴趣里出现“轻食”，但用户并未在 dietary 明确要求
    profile = apply_profile_overrides(
        profile,
        [{"key": "interests", "value": "轻食", "action": "add"}],
    )
    conflicts = detect_preference_conflicts(profile)
    assert conflicts == []


def test_family_sichuan_keeps_sichuan_candidate_in_research() -> None:
    c = TestClient(app)
    buf = ""
    with c.stream(
        "POST",
        "/v1/agent/stream",
        json={
            "user_input": "今天下午带老婆孩子出去玩，孩子5岁，别太远，帮我安排一下",
            "overrides": [{"key": "dietary", "value": "川菜", "action": "add"}],
        },
    ) as resp:
        assert resp.status_code == 200
        for chunk in resp.iter_text():
            buf += chunk

    payload = _payload_from_stream(buf)
    # 历史档案低卡 + 用户加川菜：显式偏好优先，应直接出可下单方案
    assert not payload.get("preference_conflicts")
    primary = payload["plans"][0]
    assert primary.get("issueKind", "ok") == "ok"
    assert primary["isValid"] is True
    eat_name = primary.get("eat", {}).get("name", "")
    assert "川" in eat_name or "蜀" in eat_name


def test_named_venue_chuanyige_extracted_from_utterance() -> None:
    text = (
        "今天早上带老婆孩子出去玩，孩子5岁，中午12点想吃川一哥火锅，帮我安排。"
    )
    profile = analyze_profile(text)
    assert "川一哥" in profile.preferred_venues
    assert profile.meal_time == "12:00"
    assert profile.start_time == "09:00"
    assert "火锅" in profile.dietary


def test_hil_replan_japanese_5km_does_not_pick_6km_sushi() -> None:
    """面板改「日料·5km」后，不应再出 6km 的禾绿并标距离超限。"""
    from backend.agents.planner import build_plans
    from backend.agents.profiler import analyze_profile
    from backend.hil import build_plans_payload
    from backend.nodes.hil import hil_apply_overrides_node
    from backend.nodes.researcher import researcher_node

    text = (
        "今天早上带老婆孩子出去玩，孩子5岁，中午12点想吃川一哥火锅，帮我安排。"
    )
    profile = analyze_profile(text)
    state = hil_apply_overrides_node(
        {
            "group_profile": profile,
            "profile_overrides": [
                {"key": "distance_limit_km", "value": "5", "action": "set"},
                {"key": "dietary", "value": "日料", "action": "set"},
            ],
            "trace": [],
        }
    )
    profile = state["group_profile"]
    assert profile.preferred_venues == []
    assert profile.dietary == ["日料"]
    research = researcher_node({**state, "trace": []})["research_result"]
    plans = build_plans(profile, research, top_k=2)
    assert plans
    for plan in plans:
        for stage in plan.stages:
            dist = float(stage.primary.metadata.get("distance_km", 0) or 0)
            assert dist <= 5.0, f"{stage.primary.name} dist={dist}"
        eat = next(s for s in plan.stages if s.name == "吃")
        assert eat.primary.poi_id != "poi_rest_jp_001"
    payloads = build_plans_payload(
        {
            **state,
            "research_result": research,
            "plan": plans[0],
            "plan_alternatives": plans[1:],
        }
    )
    assert payloads[0]["issueKind"] in ("needs_preference_fix", "alternative_available", "blocked")


def test_named_venue_chuanyige_wins_over_higher_scored_hotpot() -> None:
    text = (
        "今天早上带老婆孩子出去玩，孩子5岁，中午12点想吃川一哥火锅，帮我安排。"
    )
    profile = analyze_profile(text)
    state = researcher_node({"group_profile": profile, "trace": []})
    research = state["research_result"]
    plans = build_plans(profile, research, top_k=1)
    assert plans
    eat = next(s for s in plans[0].stages if s.name == "吃")
    assert eat.primary.poi_id == "poi_003"
    assert eat.start_time == "12:00"
