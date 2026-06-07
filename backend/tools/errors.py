"""Tool 调用失败时抛出的异常（对应 HTTP 状态码语义）。"""


class ToolError(Exception):
    """假后台返回的业务错误，例如满座 409、售罄 410。"""

    def __init__(self, code: int, message: str, *, details: dict | None = None) -> None:
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(f"[{code}] {message}")


class MerchantFullException(ToolError):
    """409 满座：触发 Compensator 拉黑商户 + 疲劳度修正。"""

    def __init__(
        self,
        message: str = "餐厅已满座，该时段无空位",
        *,
        poi_id: str = "",
        time_slot: str = "",
    ) -> None:
        super().__init__(
            409,
            message,
            details={"poi_id": poi_id, "time_slot": time_slot, "exception": "MerchantFullException"},
        )


class TicketSoldOutException(ToolError):
    """410 售罄：触发 Compensator 换备选活动。"""

    def __init__(
        self,
        message: str = "库存熔断：该时段票/桌位已被抢光",
        *,
        poi_id: str = "",
    ) -> None:
        super().__init__(
            410,
            message,
            details={"poi_id": poi_id, "exception": "TicketSoldOutException"},
        )
