"""Mock 美团后台的「业务状态」：订单簿 + 幂等表 + 注入开关。

路由（`routes.py`）只是 HTTP 适配层；真正的业务逻辑在这里。
和旧 `tools/mock_client.MockBackend` 行为对齐，方便老测试照样通过。
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from uuid import uuid4

from backend.tools.errors import MerchantFullException, TicketSoldOutException, ToolError

# 演示用：哪些 poi_id 在「查桌位」时永远没位（方便测 DryRun 失败路径）
ALWAYS_FULL_POIS = frozenset({"poi_rest_full"})


def _time_to_slot(time: str) -> str:
    """把 HH:MM 映射到演示时段桶。"""
    try:
        hour = int(time.split(":", 1)[0])
    except (ValueError, IndexError):
        return "12:00-14:00"
    if 11 <= hour <= 14:
        return "12:00-14:00"
    if 17 <= hour <= 20:
        return "18:00-20:00"
    return "12:00-14:00"


@dataclass
class MockBackend:
    """一次会话内的订单簿（进程内内存）。"""

    orders: dict[str, dict] = field(default_factory=dict)
    idempotency_index: dict[str, str] = field(default_factory=dict)  # key -> order_id
    booking_registry: dict[str, dict[str, int]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # 火锅高峰时段满座陷阱（演示 409）
        self.booking_registry.setdefault("poi_003", {})["12:00-14:00"] = 100

    def _new_order_id(self) -> str:
        return f"M{uuid4().hex[:10].upper()}"

    def book_service(
        self,
        *,
        poi_id: str,
        time_slot: str,
        party_size: int,
    ) -> dict:
        """有状态订位：满座 / 库存熔断注入点。"""
        reg = self.booking_registry.get(poi_id, {})
        load = reg.get(time_slot, 0)
        if load >= 100:
            raise MerchantFullException(
                f"商户 {poi_id} 在 {time_slot} 已无空位",
                poi_id=poi_id,
                time_slot=time_slot,
            )
        if party_size >= 4 and poi_id in {"poi_003", "poi_rest_201"} and random.random() < 0.3:
            raise TicketSoldOutException(
                "库存熔断：该时段窗边4人桌已被抢光",
                poi_id=poi_id,
            )
        booking_id = f"BK-{poi_id}-{random.randint(1000, 9999)}"
        reg[time_slot] = load + party_size
        self.booking_registry[poi_id] = reg
        return {
            "status": "SUCCESS",
            "booking_id": booking_id,
            "message": f"订单已锁定，Mock 已触发下单动作（{poi_id}）",
            "mock": True,
        }

    # ── 读类（DryRun 用）────────────────────────────────────────

    def check_activity_availability(
        self, *, poi_id: str, start: str, force_fail: str | None = None
    ) -> dict:
        if force_fail == "sold_out":
            raise ToolError(410, "活动票已售罄", details={"poi_id": poi_id})
        return {
            "available": True,
            "tickets_left": 20,
            "poi_id": poi_id,
            "start": start,
            "mock": True,
        }

    def check_table_availability(
        self,
        *,
        poi_id: str,
        time: str,
        people: int,
        force_fail: str | None = None,
    ) -> dict:
        slot = _time_to_slot(time)
        if self.booking_registry.get(poi_id, {}).get(slot, 0) >= 100:
            return {
                "available": False,
                "waiting_minutes": 90,
                "poi_id": poi_id,
                "mock": True,
                "reason": f"{slot} 已满座",
                "code": 409,
            }
        # 朋友场景 4 人聚餐陷阱：热门烤肉店无大桌 → 演示预检失败后换备选
        if poi_id == "poi_rest_201" and people >= 4:
            return {
                "available": False,
                "waiting_minutes": 120,
                "poi_id": poi_id,
                "mock": True,
                "reason": "4人桌已满，建议换备选餐厅",
            }
        if force_fail == "table_full" or poi_id in ALWAYS_FULL_POIS:
            return {
                "available": False,
                "waiting_minutes": 45,
                "poi_id": poi_id,
                "mock": True,
            }
        return {
            "available": True,
            "waiting_minutes": 0,
            "poi_id": poi_id,
            "time": time,
            "people": people,
            "mock": True,
        }

    def check_addon_stock(self, *, poi_id: str, force_fail: str | None = None) -> dict:
        if force_fail == "out_of_stock":
            return {"in_stock": False, "poi_id": poi_id, "mock": True}
        return {"in_stock": True, "poi_id": poi_id, "mock": True}

    # ── 写类（Executor 用）────────────────────────────────────────

    def buy_ticket(
        self,
        *,
        activity_id: str,
        count: int,
        idempotency_key: str,
        force_fail: str | None = None,
    ) -> dict:
        existing = self._idempotent_hit(idempotency_key)
        if existing:
            return existing
        if force_fail == "sold_out":
            raise ToolError(410, "购票失败：已售罄", details={"activity_id": activity_id})
        order_id = self._new_order_id()
        body = {
            "order_id": order_id,
            "status": "confirmed",
            "ticket_codes": [f"T{i:04d}" for i in range(count)],
            "mock": True,
        }
        self._remember_order(order_id, "ticket", body, idempotency_key)
        return body

    def book_table(
        self,
        *,
        poi_id: str,
        time: str,
        people: int,
        idempotency_key: str,
        force_fail: str | None = None,
    ) -> dict:
        existing = self._idempotent_hit(idempotency_key)
        if existing:
            return existing
        if force_fail == "table_full":
            raise MerchantFullException("订位失败：餐厅已满座", poi_id=poi_id, time_slot=_time_to_slot(time))
        slot = _time_to_slot(time)
        booked = self.book_service(poi_id=poi_id, time_slot=slot, party_size=people)
        order_id = self._new_order_id()
        body = {
            "order_id": order_id,
            "status": "reserved",
            "qr_code": f"QR-{order_id[-6:]}",
            "booking_id": booked.get("booking_id"),
            "mock": True,
        }
        self._remember_order(order_id, "reserve", body, idempotency_key)
        return body

    def order_addon(
        self,
        *,
        poi_id: str,
        idempotency_key: str,
        items: list | None = None,
        delivery_address: str | None = None,
        deliver_to_poi_id: str | None = None,
        force_fail: str | None = None,
    ) -> dict:
        existing = self._idempotent_hit(idempotency_key)
        if existing:
            return existing
        if force_fail == "out_of_stock":
            raise ToolError(409, "加餐下单失败：库存不足", details={"poi_id": poi_id})
        order_id = self._new_order_id()
        deliver_target = deliver_to_poi_id or delivery_address
        body = {
            "order_id": order_id,
            "eta_minutes": 25,
            "total": 68,
            "deliver_to_poi_id": deliver_target,
            "delivery_address": deliver_target,
            "mock": True,
        }
        self._remember_order(order_id, "food", body, idempotency_key)
        return body

    # ── 回滚（Compensator 用）────────────────────────────────────

    def cancel_order(self, *, order_id: str) -> dict:
        order = self.orders.get(order_id)
        if not order:
            raise ToolError(404, f"订单不存在: {order_id}")
        if order.get("cancelled"):
            return {
                "cancelled": True,
                "refund_amount": order.get("refund_amount", 0),
                "mock": True,
            }
        order["cancelled"] = True
        order["refund_amount"] = order.get("total", 0) or 50
        return {
            "cancelled": True,
            "refund_amount": order["refund_amount"],
            "order_id": order_id,
            "mock": True,
        }

    # ── 内部 ────────────────────────────────────────────────────

    def _idempotent_hit(self, idempotency_key: str) -> dict | None:
        oid = self.idempotency_index.get(idempotency_key)
        if oid and oid in self.orders:
            return dict(self.orders[oid]["payload"])
        return None

    def _remember_order(
        self, order_id: str, kind: str, payload: dict, idempotency_key: str
    ) -> None:
        self.orders[order_id] = {
            "kind": kind,
            "payload": payload,
            "cancelled": False,
            "total": payload.get("total", 0),
        }
        self.idempotency_index[idempotency_key] = order_id


# 全进程共用一个假后台（Demo / 单用户足够）
_default_backend = MockBackend()


def get_mock_backend() -> MockBackend:
    return _default_backend


def reset_mock_backend() -> None:
    """测试用：清空订单簿（同时重置幂等表）。"""
    global _default_backend
    _default_backend = MockBackend()
