"""方案 issue 分类：偏好矛盾 vs 附近无菜系。"""
import json

from fastapi.testclient import TestClient

from backend.agents.profiler import analyze_profile, apply_profile_overrides
from backend.hil import build_plans_payload, detect_preference_conflicts
from backend.server import app


def _payload_from_stream(buf: str) -> dict:
    for block in buf.split("\n\n"):
        if "awaiting_confirm" not in block:
            continue
        line = block.strip().removeprefix("data: ")
        return json.loads(line)
    raise AssertionError("no awaiting_confirm")


def test_friends_stream_exposes_no_spicy_conflict() -> None:
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
    assert payload.get("preference_conflicts")
    assert payload["preference_conflicts"][0]["code"] == "no_spicy_vs_heavy"
    assert "历史档案唤醒" in buf or "禁辣" in buf


def test_history_archive_no_spicy_vs_heavy_friends() -> None:
    from backend.nodes.profiler import inject_history_archives

    profile = analyze_profile("下午和三个朋友一起出去，4个人，想吃重口味")
    profile, traces = inject_history_archives(profile, profile.raw_text)
    assert "禁辣" in profile.dietary
    assert "重辣" in profile.forbidden_tags
    assert traces
    conflicts = detect_preference_conflicts(profile)
    assert conflicts
    assert conflicts[0]["code"] == "no_spicy_vs_heavy"


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
