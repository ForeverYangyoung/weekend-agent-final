"""Tool 调用失败时抛出的异常（对应 HTTP 状态码语义）。"""


class ToolError(Exception):
    """假后台返回的业务错误，例如满座 409、售罄 410。"""

    def __init__(self, code: int, message: str, *, details: dict | None = None) -> None:
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(f"[{code}] {message}")
