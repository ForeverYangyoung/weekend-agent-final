"""Mock 美团 HTTP 服务的端到端测试（直接对 FastAPI 走 ASGI）。

`tools.registry.invoke` / `tools.http_client.search_poi` 默认就走 ASGI 内联，
所以单元测试不用拉真端口，速度等于内存版。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.mock_meituan.app import mock_app
from backend.mock_meituan.backend import reset_mock_backend
from backend.tools import ToolContext, ToolError, invoke
from backend.tools.http_client import current_mode, search_poi


@pytest.fixture(autouse=True)
def _clean_backend() -> None:
    reset_mock_backend()
    yield
    reset_mock_backend()


def test_default_mode_is_internal_asgi() -> None:
    mode, base = current_mode()
    assert mode == "internal"
    assert base.startswith("http://")


def test_search_poi_via_http_returns_items() -> None:
    items = search_poi(scene="family", stage="吃", limit=5)
    assert items, "family/吃 应有候选"
    assert any("Wagas" in (i.get("name") or "") for i in items)
    # metadata 必须保留 distance/价格，否则下游五维打分失效
    for it in items:
        meta = it.get("metadata") or {}
        assert "distance_km" in meta
        assert "avg_price" in meta


def test_invoke_book_table_returns_order_id() -> None:
    out = invoke(
        "book_table",
        {"poi_id": "poi_rest_021", "time": "18:00", "people": 3},
        ctx=ToolContext(idempotency_key="http-1"),
        stage_name="吃",
    )
    assert out["status"] == "reserved"
    assert out["order_id"].startswith("M")


def test_force_failure_via_http_returns_409() -> None:
    ctx = ToolContext(force_failure_stage="吃", idempotency_key="http-fail-1")
    with pytest.raises(ToolError) as exc:
        invoke(
            "book_table",
            {"poi_id": "poi_rest_021", "time": "18:00", "people": 3},
            ctx=ctx,
            stage_name="吃",
        )
    assert exc.value.code == 409
    assert "餐厅已满座" in exc.value.message


def test_idempotency_round_trip() -> None:
    ctx = ToolContext(idempotency_key="same-http")
    r1 = invoke("buy_ticket", {"poi_id": "poi_park_001", "count": 2}, ctx=ctx, stage_name="玩")
    r2 = invoke("buy_ticket", {"poi_id": "poi_park_001", "count": 2}, ctx=ctx, stage_name="玩")
    assert r1["order_id"] == r2["order_id"]


# ─────────────────────────── 直接打 mock_app 路由层 ───────────────────────────


def test_health_route() -> None:
    with TestClient(mock_app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["service"] == "mock-meituan"


def test_poi_search_route_with_chinese_stage() -> None:
    with TestClient(mock_app) as client:
        r = client.get("/poi/search", params={"scene": "friends", "stage": "玩", "limit": 5})
        assert r.status_code == 200
        body = r.json()
        assert body["scene"] == "friends"
        assert body["stage"] == "玩"
        assert body["count"] >= 1


def test_admin_reset_clears_orders() -> None:
    invoke(
        "book_table",
        {"poi_id": "poi_x", "time": "12:00", "people": 2},
        ctx=ToolContext(idempotency_key="reset-1"),
        stage_name="吃",
    )
    with TestClient(mock_app) as client:
        # 先确认有订单
        body = client.get("/health").json()
        assert body["orders_open"] >= 1
        client.post("/admin/reset")
        body = client.get("/health").json()
        assert body["orders_open"] == 0
        assert body["orders_cancelled"] == 0
