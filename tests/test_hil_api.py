"""HIL：规划暂停、覆盖重搜、确认下单。"""
from fastapi.testclient import TestClient

from backend.server import app


def _stream_until_confirm(client: TestClient, user_input: str) -> tuple[str, dict]:
    buf = ""
    session_id = ""
    payload: dict = {}
    with client.stream(
        "POST",
        "/v1/agent/stream",
        json={"user_input": user_input},
    ) as resp:
        assert resp.status_code == 200
        for chunk in resp.iter_text():
            buf += chunk

    assert '"event": "awaiting_confirm"' in buf or '"event":"awaiting_confirm"' in buf
    for block in buf.split("\n\n"):
        if "awaiting_confirm" not in block:
            continue
        line = block.strip().removeprefix("data: ")
        import json

        payload = json.loads(line)
        session_id = payload.get("session_id", "")
        break

    assert session_id
    assert payload.get("plans")
    assert payload.get("profile_chips") is not None
    return session_id, payload


def test_planning_pauses_before_execution() -> None:
    c = TestClient(app)
    _, payload = _stream_until_confirm(
        c, "想去海淀区，吃川菜，预算100以内"
    )
    assert len(payload["plans"]) >= 1
    # 预检完成但尚未下单
    assert payload.get("dry_run_calls")


def test_replan_light_food_excludes_bbq() -> None:
    c = TestClient(app)
    session_id, _ = _stream_until_confirm(
        c, "下午和三个朋友一起出去，4个人，别太远，想吃重口味"
    )

    buf = ""
    with c.stream(
        "POST",
        "/v1/agent/replan",
        json={
            "session_id": session_id,
            "overrides": [{"key": "dietary", "value": "轻食", "action": "set"}],
        },
    ) as resp:
        assert resp.status_code == 200
        for chunk in resp.iter_text():
            buf += chunk

    assert "awaiting_confirm" in buf
    assert "炙烤大叔" not in buf and "烤肉" not in buf or "Wagas" in buf or "超级碗" in buf
    assert "饮食·轻食/低卡（已匹配餐厅）" in buf or "Wagas" in buf
    assert "菜系·轻食" not in buf


def test_replan_japanese_cuisine_matches_poi() -> None:
    c = TestClient(app)
    session_id, _ = _stream_until_confirm(
        c, "今天下午带老婆孩子出去玩，老婆减肥，孩子5岁"
    )

    buf = ""
    with c.stream(
        "POST",
        "/v1/agent/replan",
        json={
            "session_id": session_id,
            "overrides": [{"key": "dietary", "value": "日料", "action": "add"}],
        },
    ) as resp:
        assert resp.status_code == 200
        for chunk in resp.iter_text():
            buf += chunk

    assert "禾绿回转寿司" in buf or "日料" in buf
    assert "awaiting_confirm" in buf


def test_hil_replan_with_override() -> None:
    c = TestClient(app)
    session_id, first = _stream_until_confirm(c, "下午两个人随便逛逛")

    buf = ""
    with c.stream(
        "POST",
        "/v1/agent/replan",
        json={
            "session_id": session_id,
            "overrides": [
                {"key": "dietary", "value": "川菜", "action": "add"},
                {"key": "district", "value": "海淀区", "action": "set"},
            ],
        },
    ) as resp:
        assert resp.status_code == 200
        for chunk in resp.iter_text():
            buf += chunk

    assert "awaiting_confirm" in buf
    assert session_id in buf


def test_stream_with_initial_overrides_adds_hotpot_to_family() -> None:
    c = TestClient(app)
    buf = ""
    with c.stream(
        "POST",
        "/v1/agent/stream",
        json={
            "user_input": "今天下午带老婆孩子出去玩，孩子5岁，别太远，帮我安排一下",
            "overrides": [{"key": "dietary", "value": "火锅", "action": "add"}],
        },
    ) as resp:
        assert resp.status_code == 200
        for chunk in resp.iter_text():
            buf += chunk

    assert "awaiting_confirm" in buf
    assert "火锅" in buf
    assert "HIL" in buf or "重规划" in buf or "覆盖" in buf


def test_hil_confirm_returns_orders() -> None:
    c = TestClient(app)
    session_id, payload = _stream_until_confirm(
        c, "今天下午带老婆孩子出去玩，别太远，老婆减肥，孩子5岁"
    )

    addons = (payload.get("plans") or [{}])[0].get("addons") or []
    selected = [a["addon_id"] for a in addons] if addons else []

    r = c.post(
        "/v1/agent/confirm",
        json={
            "session_id": session_id,
            "plan_id": "primary",
            "selected_addon_ids": selected,
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["executed"] >= 1
    assert data.get("orders")


def test_all_plan_cards_get_scene_addons() -> None:
    """主方案与备选方案都应带上同类型附加项，送达点绑定各自餐厅/活动 POI。"""
    c = TestClient(app)
    _, payload = _stream_until_confirm(
        c, "下午和三个朋友一起出去，4个人，别太远，想吃重口味"
    )
    plans = payload.get("plans") or []
    assert len(plans) >= 2
    for p in plans:
        assert p.get("addons"), f"{p.get('id')} 缺少附加项"
        eat_name = (p.get("eat") or {}).get("name", "")
        desc = p["addons"][0].get("description", "")
        if eat_name:
            short = eat_name.split("（")[0].strip()
            assert short in desc, f"附加项未绑定到该方案的餐厅：{eat_name}"


def test_plan_payload_includes_hil_addons() -> None:
    c = TestClient(app)
    _, payload = _stream_until_confirm(
        c, "今天下午带老婆孩子出去玩，老婆减肥，孩子5岁，帮我安排一下。"
    )
    primary = payload["plans"][0]
    assert primary.get("addons")
    assert primary["addons"][0].get("addon_id")
    assert primary["addons"][0].get("description")
    assert "加餐" not in (primary.get("order_label") or "")
