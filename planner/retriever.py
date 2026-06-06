"""工具调用层 — 封装所有 Mock API HTTP 请求。

Mock Server 端口 :8001，接口契约见 01 文档 §6。
"""

import time
from typing import Optional

import requests

from planner.state import (
    EnrichedPOI,
    POI,
    RouteResult,
    TableResult,
    WeatherResult,
    TransportMode,
)

# ── 配置 ──────────────────────────────────────────────

MOCK_API_BASE = "http://localhost:8001"
REQUEST_TIMEOUT = 10  # seconds


def _get(path: str, params: Optional[dict] = None) -> dict:
    """GET 请求，带超时和基础错误处理。"""
    url = f"{MOCK_API_BASE}{path}"
    resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _post(path: str, body: Optional[dict] = None) -> dict:
    url = f"{MOCK_API_BASE}{path}"
    resp = requests.post(url, json=body, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


# ── 信息查询类 ────────────────────────────────────────


def search_poi(category: str, location: str,
               filters: Optional[dict] = None, size: int = 5) -> list[POI]:
    """GET /api/poi/search"""
    params = {
        "category": category,
        "location": location,
        "size": size,
    }
    if filters:
        params["filters"] = filters
    t0 = time.time()
    data = _get("/api/poi/search", params)
    elapsed = (time.time() - t0) * 1000

    pois = []
    for item in data.get("pois", []):
        pois.append(POI(
            id=item.get("id", ""),
            name=item.get("name", ""),
            category=item.get("category", category),
            location=item.get("location", ""),
            avg_price=float(item.get("avg_price", 0)),
            tags=item.get("tags", []),
            open_hours=item.get("open_hours", "10:00-22:00"),
            rating=float(item.get("rating", 4.0)),
        ))
    return pois


def get_poi_detail(poi_id: str) -> Optional[POI]:
    """GET /api/poi/{id}"""
    data = _get(f"/api/poi/{poi_id}")
    return POI(
        id=data.get("id", ""),
        name=data.get("name", ""),
        category=data.get("category", ""),
        location=data.get("location", ""),
        avg_price=float(data.get("avg_price", 0)),
        tags=data.get("tags", []),
        open_hours=data.get("open_hours", "10:00-22:00"),
        rating=float(data.get("rating", 4.0)),
    )


def check_table(poi_id: str, time_str: str, people: int) -> TableResult:
    """GET /api/restaurant/{id}/table"""
    data = _get(f"/api/restaurant/{poi_id}/table",
                params={"time": time_str, "people": people})
    return TableResult(
        available=data.get("available", False),
        waiting_minutes=data.get("waiting_minutes", 0),
    )


def check_queue(poi_id: str) -> dict:
    """GET /api/restaurant/{id}/queue"""
    return _get(f"/api/restaurant/{poi_id}/queue")


def get_route(origin: str, dest: str,
              mode: TransportMode = TransportMode.TAXI) -> RouteResult:
    """GET /api/route"""
    data = _get("/api/route", params={
        "from": origin,
        "to": dest,
        "mode": mode.value,
    })
    return RouteResult(
        duration_min=float(data.get("duration_min", 30)),
        distance_km=float(data.get("distance_km", 5)),
        path=data.get("path", ""),
        mode=mode.value,
    )


def get_weather(location: str, time_str: str) -> WeatherResult:
    """GET /api/weather"""
    data = _get("/api/weather", params={"location": location, "time": time_str})
    return WeatherResult(
        condition=data.get("condition", "晴"),
        temp=float(data.get("temp", 20)),
        suitable_outdoor=data.get("suitable_outdoor", True),
    )


# ── 批量操作 ──────────────────────────────────────────


def parallel_retrieve(category: str, location: str,
                      filters: Optional[dict] = None,
                      size: int = 5) -> list[EnrichedPOI]:
    """搜索 POI 并补全桌位/排队信息（餐厅类）。

    当前为同步版本；后续可换 concurrent.futures 做真并发。
    """
    pois = search_poi(category, location, filters, size)
    enriched = []
    for p in pois:
        ep = EnrichedPOI(poi=p)
        if p.category == "餐厅":
            try:
                table = check_table(p.id, "12:00", 2)  # 占位，后续由 composer 覆写
                ep.table_available = table.available
                ep.waiting_minutes = table.waiting_minutes
                ep.queue_length = 0
            except Exception:
                ep.table_available = None
                ep.waiting_minutes = 999
        enriched.append(ep)
    return enriched


def fetch_routes_between(pois_a: list[POI], pois_b: list[POI],
                         mode: TransportMode = TransportMode.TAXI
                         ) -> dict[tuple[str, str], RouteResult]:
    """计算两组 POI 之间的全对全路由矩阵。

    Returns: {(a.id, b.id): RouteResult}
    """
    routes: dict[tuple[str, str], RouteResult] = {}
    for a in pois_a:
        for b in pois_b:
            try:
                r = get_route(a.location, b.location, mode)
                routes[(a.id, b.id)] = r
            except Exception:
                routes[(a.id, b.id)] = RouteResult(
                    duration_min=60, distance_km=20, mode=mode.value
                )
    return routes
