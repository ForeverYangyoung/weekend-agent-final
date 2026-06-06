"""独立可启动的 Mock 美团 FastAPI 应用。

直接拉起：
    uvicorn backend.mock_meituan.app:mock_app --port 8001

随后让 Agent 走真 TCP（默认走 in-process ASGI）：
    set MOCK_MEITUAN_BASE_URL=http://localhost:8001          # Windows PowerShell
    export MOCK_MEITUAN_BASE_URL=http://localhost:8001       # macOS / Linux
    python -m backend.demo

接口同时被主服务 `backend.server` 挂在 `/mock-meituan/*`，
方便 demo 时一个进程跑两件事。
"""
from __future__ import annotations

from fastapi import FastAPI

from backend.mock_meituan.routes import mock_router

mock_app = FastAPI(
    title="Mock Meituan API",
    version="0.1.0",
    description=(
        "Weekend Agent 演示用的假美团后台。\n\n"
        "- POI 检索：GET  /poi/search?scene=family&stage=玩\n"
        "- 可用性预检：POST /availability/{activity,table,addon}\n"
        "- 下单 / 取消：POST /order/{buy_ticket,book_table,order_addon,cancel}\n"
        "- 注入失败：写类请求体加 `force_fail`（table_full / sold_out / out_of_stock）"
    ),
)

mock_app.include_router(mock_router)


@mock_app.get("/")
def root() -> dict:
    return {
        "service": "mock-meituan",
        "endpoints": [
            "GET  /poi/search",
            "POST /availability/{activity,table,addon}",
            "POST /order/{buy_ticket,book_table,order_addon,cancel}",
            "GET  /health",
            "GET  /docs",
        ],
    }
