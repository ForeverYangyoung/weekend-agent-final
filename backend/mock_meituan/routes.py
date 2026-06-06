"""Mock 美团 HTTP 路由：所有 Agent 工具都通过这里走 HTTP。

路由清单：
  GET  /poi/search                  搜 POI 候选（替代旧内存 _CATALOG）
  POST /availability/activity       查活动票位（DryRun 用）
  POST /availability/table          查餐厅桌位
  POST /availability/addon          查加餐库存
  POST /order/buy_ticket            真购票
  POST /order/book_table            真订桌
  POST /order/order_addon           真下加餐
  POST /order/cancel                取消订单（Compensator 用）

注入开关：写类路由的请求体里可带 `force_fail`（如 `table_full` / `sold_out` /
`out_of_stock`），mock 服务直接返 4xx，便于演示补偿链。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.mock_meituan import catalog
from backend.mock_meituan.backend import get_mock_backend
from backend.tools.errors import ToolError


mock_router = APIRouter(tags=["mock-meituan"])


def _from_tool_error(e: ToolError) -> HTTPException:
    return HTTPException(
        status_code=e.code,
        detail={"message": e.message, "details": e.details, "mock": True},
    )


# ─────────────────────────── POI 搜索 ───────────────────────────


@mock_router.get("/poi/search")
def poi_search(
    scene: str = Query("family", description="family / friends / couple / solo"),
    stage: str = Query(..., description="玩 / 吃 / 加餐"),
    limit: int = Query(10, ge=1, le=50),
) -> dict[str, Any]:
    items = catalog.search(scene=scene, stage=stage, limit=limit)
    return {"scene": scene, "stage": stage, "count": len(items), "items": items}


# ─────────────────────────── 可用性查询 ───────────────────────────


class ActivityAvailabilityReq(BaseModel):
    poi_id: str
    start: str = ""
    force_fail: str | None = None


@mock_router.post("/availability/activity")
def availability_activity(req: ActivityAvailabilityReq) -> dict[str, Any]:
    try:
        return get_mock_backend().check_activity_availability(
            poi_id=req.poi_id, start=req.start, force_fail=req.force_fail
        )
    except ToolError as e:
        raise _from_tool_error(e) from e


class TableAvailabilityReq(BaseModel):
    poi_id: str
    time: str = ""
    people: int = 4
    force_fail: str | None = None


@mock_router.post("/availability/table")
def availability_table(req: TableAvailabilityReq) -> dict[str, Any]:
    try:
        return get_mock_backend().check_table_availability(
            poi_id=req.poi_id,
            time=req.time,
            people=req.people,
            force_fail=req.force_fail,
        )
    except ToolError as e:
        raise _from_tool_error(e) from e


class AddonAvailabilityReq(BaseModel):
    poi_id: str
    force_fail: str | None = None


@mock_router.post("/availability/addon")
def availability_addon(req: AddonAvailabilityReq) -> dict[str, Any]:
    try:
        return get_mock_backend().check_addon_stock(
            poi_id=req.poi_id, force_fail=req.force_fail
        )
    except ToolError as e:
        raise _from_tool_error(e) from e


# ─────────────────────────── 下单 ───────────────────────────


class BuyTicketReq(BaseModel):
    activity_id: str
    count: int = Field(1, ge=1, le=20)
    idempotency_key: str
    force_fail: str | None = None


@mock_router.post("/order/buy_ticket")
def order_buy_ticket(req: BuyTicketReq) -> dict[str, Any]:
    try:
        return get_mock_backend().buy_ticket(
            activity_id=req.activity_id,
            count=req.count,
            idempotency_key=req.idempotency_key,
            force_fail=req.force_fail,
        )
    except ToolError as e:
        raise _from_tool_error(e) from e


class BookTableReq(BaseModel):
    poi_id: str
    time: str = ""
    people: int = 4
    idempotency_key: str
    force_fail: str | None = None


@mock_router.post("/order/book_table")
def order_book_table(req: BookTableReq) -> dict[str, Any]:
    try:
        return get_mock_backend().book_table(
            poi_id=req.poi_id,
            time=req.time,
            people=req.people,
            idempotency_key=req.idempotency_key,
            force_fail=req.force_fail,
        )
    except ToolError as e:
        raise _from_tool_error(e) from e


class OrderAddonReq(BaseModel):
    poi_id: str
    idempotency_key: str
    items: list[Any] | None = None
    delivery_address: str | None = None
    deliver_to_poi_id: str | None = None
    force_fail: str | None = None


@mock_router.post("/order/order_addon")
def order_order_addon(req: OrderAddonReq) -> dict[str, Any]:
    try:
        return get_mock_backend().order_addon(
            poi_id=req.poi_id,
            idempotency_key=req.idempotency_key,
            items=req.items,
            delivery_address=req.delivery_address,
            deliver_to_poi_id=req.deliver_to_poi_id,
            force_fail=req.force_fail,
        )
    except ToolError as e:
        raise _from_tool_error(e) from e


class CancelOrderReq(BaseModel):
    order_id: str


@mock_router.post("/order/cancel")
def order_cancel(req: CancelOrderReq) -> dict[str, Any]:
    try:
        return get_mock_backend().cancel_order(order_id=req.order_id)
    except ToolError as e:
        raise _from_tool_error(e) from e


# ─────────────────────────── 健康检查 ───────────────────────────


@mock_router.get("/health")
def health() -> dict[str, Any]:
    backend = get_mock_backend()
    return {
        "status": "ok",
        "service": "mock-meituan",
        "orders_open": sum(1 for o in backend.orders.values() if not o.get("cancelled")),
        "orders_cancelled": sum(1 for o in backend.orders.values() if o.get("cancelled")),
    }


@mock_router.post("/admin/reset")
def admin_reset() -> dict[str, Any]:
    """清空订单簿，重置幂等表。Demo 之间快速复位用。"""
    from backend.mock_meituan.backend import reset_mock_backend

    reset_mock_backend()
    return {"reset": True, "service": "mock-meituan"}
