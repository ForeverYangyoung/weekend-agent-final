"""Mock 美团后台：以 HTTP 协议（FastAPI）暴露 POI 搜索 + 订单全流程。

部署形态：
  - 默认（内联）：`tools.http_client` 用 httpx + ASGITransport 直接打到 `mock_app`，零端口。
  - 独立：`uvicorn backend.mock_meituan.app:mock_app --port 8001`，
          再设 `MOCK_MEITUAN_BASE_URL=http://localhost:8001` 即可让 Agent 走真 TCP。

测试要点：内联 / 独立两种形态下，Agent 代码完全一致；切换只改 env。
"""

from backend.mock_meituan.app import mock_app
from backend.mock_meituan.backend import (
    MockBackend,
    get_mock_backend,
    reset_mock_backend,
)
from backend.mock_meituan.routes import mock_router

__all__ = [
    "MockBackend",
    "get_mock_backend",
    "mock_app",
    "mock_router",
    "reset_mock_backend",
]
